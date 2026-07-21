import os
import json
import time
import uuid
import hashlib
from pypdf import PdfReader
from google import genai
from google.genai import errors as genai_errors
from app.database import insert_chunk, search_chunks, save_document, get_document, get_document_by_hash

_client = None

MIN_EXTRACTED_CHARS = 100
EMBED_BATCH_SIZE = 20  # chunks per embed_content call; keeps request size modest
                        # since each chunk is already capped at 500 chars

# Summary/facts are generated from a prefix of the document, not the whole
# thing — gemini-2.0-flash's context window could fit far more, but keeping
# this bounded controls latency/cost per upload. 15,000 chars covers most
# short reports and several pages of a longer one, well past the old 3,000
# char (~1 page) limit, which silently summarized only the introduction of
# anything longer with no indication that had happened. When a document
# exceeds this, load_pdf() now says so explicitly in the summary text and
# in a `summary_truncated` flag, instead of staying quiet about it.
SUMMARY_CONTEXT_CHARS = 15000


def get_client():
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY"),
            http_options={"api_version": "v1"}
        )
    return _client


class QuotaError(RuntimeError):
    """Carries whatever we could determine about the quota failure instead
    of collapsing it to a bare string. is_daily defaults to True (the safer
    assumption — don't retry something that might not resolve for hours)
    until you've confirmed the real field name from a logged 429 body."""
    def __init__(self, raw: str, is_daily: bool = True):
        self.raw = raw
        self.is_daily = is_daily
        super().__init__("QUOTA_EXCEEDED")


class ChatEngine:
    def __init__(self):
        self.client = get_client()

    def _classify_quota_error(self, e) -> QuotaError:
        raw = str(e)
        print("RAW GEMINI ERROR:", raw)  # check Render logs, then refine the heuristic below
        # Best-guess heuristic until you've seen a real payload. Common Gemini
        # per-minute errors mention "PerMinute" or "RPM"; daily errors mention
        # "PerDay" or "RPD". Replace this once you know the real string.
        lowered = raw.lower()
        is_daily = not any(tok in lowered for tok in ["perminute", "rpm", "per minute"])
        return QuotaError(raw=raw, is_daily=is_daily)

    def _call_with_retry(self, fn, max_attempts: int = 3):
        for attempt in range(max_attempts):
            try:
                return fn()
            except QuotaError as e:
                if e.is_daily or attempt == max_attempts - 1:
                    raise
                time.sleep(2 ** attempt)  # 1s, 2s, 4s

    def _embed(self, text: str) -> list:
        def call():
            try:
                response = self.client.models.embed_content(
                    model="gemini-embedding-001",
                    contents=text
                )
                return response.embeddings[0].values
            except genai_errors.ClientError as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    raise self._classify_quota_error(e)
                raise
        return self._call_with_retry(call)

    def _embed_batch(self, texts: list) -> list:
        """Embed multiple chunks in one API call instead of one call per chunk.

        The Gemini SDK is documented to accept a list of strings and return
        one embedding per string, but there are unresolved reports of it
        instead collapsing the list into a single embedding. Rather than
        trust either behavior blindly, this checks that the response
        actually has one embedding per input text before using it — if the
        count doesn't match, it falls back to embedding the batch one at a
        time so chunks and vectors never get silently mismatched.
        """
        def call():
            try:
                response = self.client.models.embed_content(
                    model="gemini-embedding-001",
                    contents=texts
                )
                return response.embeddings
            except genai_errors.ClientError as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    raise self._classify_quota_error(e)
                raise
        embeddings = self._call_with_retry(call)

        if not embeddings or len(embeddings) != len(texts):
            print(
                f"WARN: batch embed returned {len(embeddings) if embeddings else 0} "
                f"embeddings for {len(texts)} inputs — falling back to per-chunk calls."
            )
            return [self._embed(t) for t in texts]

        return [e.values for e in embeddings]

    def _chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 80) -> list:
        """Split text into chunks for embedding.

        Two things changed from the original version:
          1. Long paragraphs are now split on word boundaries instead of a
             blind `para[i:i+chunk_size]` slice, so words are never cut
             in half.
          2. A second pass prepends a small tail of each chunk onto the
             next one (`overlap` chars). Without this, a fact sitting
             right at a chunk boundary could end up split across two
             chunks and not fully present in either — with fixed top_k=3
             retrieval, that made it structurally unrecoverable, not just
             harder to find.
        """
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        raw_chunks = []
        current = ""

        def push_current():
            if current:
                raw_chunks.append(current.strip())

        for para in paragraphs:
            if len(para) > chunk_size:
                push_current()
                current = ""
                words = para.split(" ")
                piece = ""
                for word in words:
                    candidate = f"{piece} {word}".strip()
                    if len(candidate) > chunk_size and piece:
                        raw_chunks.append(piece.strip())
                        piece = word
                    else:
                        piece = candidate
                current = piece
                continue
            candidate = f"{current} {para}".strip()
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                push_current()
                current = para
        push_current()

        if not overlap or len(raw_chunks) < 2:
            return raw_chunks

        overlapped = [raw_chunks[0]]
        for i in range(1, len(raw_chunks)):
            tail = raw_chunks[i - 1][-overlap:]
            overlapped.append((tail + " " + raw_chunks[i]).strip())
        return overlapped

    def _generate(self, prompt: str) -> str:
        def call():
            try:
                response = self.client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt
                )
                return response.text
            except genai_errors.ClientError as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    raise self._classify_quota_error(e)
                raise
        return self._call_with_retry(call)

    def load_pdf(self, contents: bytes, filename: str, force_reingest: bool = False) -> dict:
        content_hash = hashlib.sha256(contents).hexdigest()

        if not force_reingest:
            existing = get_document_by_hash(content_hash)
            if existing and not existing.get("partial"):
                existing["reused"] = True
                return existing

        import io
        reader = PdfReader(io.BytesIO(contents), strict=False)
        full_text = "".join(page.extract_text() or "" for page in reader.pages)

        if len(full_text.strip()) < MIN_EXTRACTED_CHARS:
            raise ValueError(
                "Could not extract readable text from this PDF. "
                "It may be a scanned or image-only document — try a text-based PDF instead."
            )

        doc_id = str(uuid.uuid4())
        chunks = self._chunk_text(full_text)

        embedded_count = 0
        try:
            for batch_start in range(0, len(chunks), EMBED_BATCH_SIZE):
                batch = chunks[batch_start:batch_start + EMBED_BATCH_SIZE]
                embeddings = self._embed_batch(batch)
                for chunk, embedding in zip(batch, embeddings):
                    insert_chunk(chunk, embedding, doc_id)
                    embedded_count += 1
        except QuotaError:
            if embedded_count == 0:
                raise
            summary = (
                f"Document partially indexed ({embedded_count}/{len(chunks)} chunks) — "
                "Gemini embedding quota was reached mid-upload. Chat will only search "
                "the indexed portion until you re-upload."
            )
            facts = ["Key facts unavailable — quota limit reached during indexing."]
            save_document(doc_id, filename, content_hash, summary, json.dumps(facts),
                          chunk_count=embedded_count, is_partial=True)
            return {
                "doc_id": doc_id,
                "filename": filename,
                "summary": summary,
                "facts": facts,
                "chunks": embedded_count,
                "reused": False,
                "partial": True,
            }

        doc_truncated = len(full_text) > SUMMARY_CONTEXT_CHARS
        text_for_summary = full_text[:SUMMARY_CONTEXT_CHARS]

        try:
            summary = self._generate(
                "Summarize this document in 3-4 sentences. Be concise and clear.\n\n"
                "Document:\n" + text_for_summary + "\n\nSummary:"
            )
            if doc_truncated:
                summary += (
                    f" (Note: this summary and the facts below are based on the first "
                    f"~{SUMMARY_CONTEXT_CHARS:,} characters of a longer document — chat "
                    f"answers still search the full text via embeddings, so the two may "
                    f"cover different parts of the document.)"
                )
        except QuotaError as e:
            wait_note = "Please wait a minute and try again." if not e.is_daily else "Quota resets daily — try again later."
            summary = f"Summary unavailable — Gemini quota limit reached. {wait_note}"

        facts_raw = None
        try:
            facts_raw = self._generate(
                "Extract key facts from this document. Return a JSON array of strings.\n"
                "Each string is one key fact, date, name, or important number.\n"
                "Return ONLY the JSON array, nothing else.\n\n"
                "Document:\n" + text_for_summary + "\n\nFacts:"
            )
            facts_clean = facts_raw.strip().replace("```json", "").replace("```", "").strip()
            facts = json.loads(facts_clean)
        except QuotaError as e:
            wait_note = "Please wait a minute and try again." if not e.is_daily else "Quota resets daily — try again later."
            facts = [f"Key facts unavailable — Gemini quota limit reached. {wait_note}"]
        except Exception:
            # facts_raw may be None here — e.g. _generate() itself raised
            # before returning anything (a non-quota ClientError, timeout,
            # etc.) — or it may hold text that just failed to parse as
            # JSON. Handle both instead of assuming facts_raw was always
            # successfully assigned before this branch runs.
            facts = [facts_raw] if facts_raw is not None else [
                "Key facts unavailable — an unexpected error occurred during extraction."
            ]

        save_document(doc_id, filename, content_hash, summary, json.dumps(facts),
                      chunk_count=len(chunks), is_partial=False)
        return {
            "doc_id": doc_id,
            "filename": filename,
            "summary": summary,
            "facts": facts,
            "chunks": len(chunks),
            "reused": False,
            "summary_truncated": doc_truncated,
        }

    def ask(self, question: str, doc_id: str) -> str:
        query_embedding = self._embed(question)
        relevant_chunks = search_chunks(query_embedding, doc_id, top_k=3)
        if not relevant_chunks:
            return "No relevant content found for this document."
        context = "\n\n".join(relevant_chunks)
        prompt = (
            "You are a helpful assistant. Answer the question based only on the context below.\n"
            "Be specific and concise.\n\n"
            "Context:\n" + context + "\n\n"
            "Question: " + question + "\n\nAnswer:"
        )
        return self._generate(prompt)

    def get_document_info(self, doc_id: str) -> dict:
        return get_document(doc_id)

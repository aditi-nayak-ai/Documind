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

    def _chunk_text(self, text: str, chunk_size: int = 500) -> list:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks = []
        current = ""
        for para in paragraphs:
            if len(para) > chunk_size:
                if current:
                    chunks.append(current.strip())
                    current = ""
                for i in range(0, len(para), chunk_size):
                    chunks.append(para[i:i + chunk_size].strip())
                continue
            if len(current) + len(para) <= chunk_size:
                current += " " + para
            else:
                if current:
                    chunks.append(current.strip())
                current = para
        if current:
            chunks.append(current.strip())
        return chunks

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
            for chunk in chunks:
                embedding = self._embed(chunk)
                insert_chunk(chunk, embedding, doc_id)
                embedded_count += 1
        except QuotaError as e:
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

        try:
            summary = self._generate(
                "Summarize this document in 3-4 sentences. Be concise and clear.\n\n"
                "Document:\n" + full_text[:3000] + "\n\nSummary:"
            )
        except QuotaError as e:
            wait_note = "Please wait a minute and try again." if not e.is_daily else "Quota resets daily — try again later."
            summary = f"Summary unavailable — Gemini quota limit reached. {wait_note}"

        try:
            facts_raw = self._generate(
                "Extract key facts from this document. Return a JSON array of strings.\n"
                "Each string is one key fact, date, name, or important number.\n"
                "Return ONLY the JSON array, nothing else.\n\n"
                "Document:\n" + full_text[:3000] + "\n\nFacts:"
            )
            facts_clean = facts_raw.strip().replace("```json", "").replace("```", "").strip()
            facts = json.loads(facts_clean)
        except QuotaError as e:
            wait_note = "Please wait a minute and try again." if not e.is_daily else "Quota resets daily — try again later."
            facts = [f"Key facts unavailable — Gemini quota limit reached. {wait_note}"]
        except Exception:
            facts = [facts_raw]

        save_document(doc_id, filename, content_hash, summary, json.dumps(facts),
                      chunk_count=len(chunks), is_partial=False)
        return {
            "doc_id": doc_id,
            "filename": filename,
            "summary": summary,
            "facts": facts,
            "chunks": len(chunks),
            "reused": False,
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

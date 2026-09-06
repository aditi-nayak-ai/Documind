import hashlib
import json
import uuid

from app import embeddings, llm, pdf_extraction
from app.database import (
    get_document,
    get_document_by_hash,
    insert_chunk,
    save_document,
    search_chunks,
)
from app.exceptions import QuotaError
from app.gemini_client import call_with_retry, classify_quota_error, get_client

# Summary/facts are generated from a prefix of the document, not the whole
# thing — gemini-2.0-flash's context window could fit far more, but keeping
# this bounded controls latency/cost per upload. 15,000 chars covers most
# short reports and several pages of a longer one, well past the old 3,000
# char (~1 page) limit, which silently summarized only the introduction of
# anything longer with no indication that had happened. When a document
# exceeds this, load_pdf() now says so explicitly in the summary text and
# in a `summary_truncated` flag, instead of staying quiet about it.
SUMMARY_CONTEXT_CHARS = 15000


class RagService:
    """Orchestrates ingestion (extract -> chunk -> embed -> store ->
    summarize) and querying (embed question -> retrieve -> generate
    answer).

    The `_embed`, `_embed_batch`, `_generate`, and `_chunk_text` methods
    below are thin wrappers over the module-level functions in
    embeddings.py/llm.py/pdf_extraction.py. load_pdf() and ask() call
    THESE methods rather than the module functions directly -- that's
    deliberate: it makes a single instance's Gemini-calling behavior
    overridable (e.g. `monkeypatch.setattr(instance, "_embed", ...)` in
    tests) without needing to patch the underlying module everywhere it's
    imported. Calling the module functions directly from load_pdf/ask
    would bypass any such per-instance override silently.
    """

    def __init__(self):
        self.client = get_client()

    def _classify_quota_error(self, e) -> QuotaError:
        return classify_quota_error(e)

    def _call_with_retry(self, fn, max_attempts: int = 3):
        return call_with_retry(fn, max_attempts)

    def _embed(self, text: str) -> list:
        return embeddings.embed_one(text)

    def _embed_batch(self, texts: list) -> list:
        return embeddings.embed_batch(texts)

    def _chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 80) -> list:
        return pdf_extraction.chunk_text(text, chunk_size, overlap)

    def _generate(self, prompt: str) -> str:
        return llm.generate(prompt)

    def load_pdf(self, contents: bytes, filename: str, force_reingest: bool = False) -> dict:
        content_hash = hashlib.sha256(contents).hexdigest()

        if not force_reingest:
            existing = get_document_by_hash(content_hash)
            if existing and not existing.get("partial"):
                existing["reused"] = True
                return existing

        full_text = pdf_extraction.extract_text(contents)

        doc_id = str(uuid.uuid4())
        chunks = self._chunk_text(full_text)

        embedded_count = 0
        try:
            for batch_start in range(0, len(chunks), embeddings.EMBED_BATCH_SIZE):
                batch = chunks[batch_start:batch_start + embeddings.EMBED_BATCH_SIZE]
                batch_embeddings = self._embed_batch(batch)
                for chunk, embedding in zip(batch, batch_embeddings):
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
        except Exception:  # noqa: BLE001 -- deliberately broad: covers both a raised ClientError/timeout from self._generate() and a JSONDecodeError from a malformed response, so fact extraction degrades gracefully either way
            # facts_raw may be None here — e.g. self._generate() itself
            # raised before returning anything (a non-quota ClientError,
            # timeout, etc.) — or it may hold text that just failed to
            # parse as JSON. Handle both instead of assuming facts_raw
            # was always successfully assigned before this branch runs.
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

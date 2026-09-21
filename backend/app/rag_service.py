import hashlib
import json
import logging
import uuid
 
from app import embeddings, llm, pdf_extraction
from app.database import (
    delete_chunks,
    delete_document,
    get_document,
    get_document_by_hash,
    insert_chunks,
    save_document,
    search_chunks,
)
from app.exceptions import QuotaError, RetryableGeminiError
from app.gemini_client import call_with_retry, classify_quota_error, get_client
 
logger = logging.getLogger("documind")
 
# Summary/facts are generated from a prefix of the document, not the whole
# thing — gemini-3.6-flash's context window could fit far more, but keeping
# this bounded controls latency/cost per upload. 15,000 chars covers most
# short reports and several pages of a longer one, well past the old 3,000
# char (~1 page) limit, which silently summarized only the introduction of
# anything longer with no indication that had happened. When a document
# exceeds this, load_pdf() now says so explicitly in the summary text and
# in a `summary_truncated` flag, instead of staying quiet about it.
SUMMARY_CONTEXT_CHARS = 15000
 
# Prefixes used both to *produce* the fallback text when generation fails
# (below) and to *recognize* it later, on a subsequent upload of the same
# file, so a quota failure isn't cached as gospel forever -- see
# _summary_or_facts_unavailable().
_SUMMARY_FAILURE_PREFIX = "Summary unavailable"
_FACTS_FAILURE_PREFIX = "Key facts unavailable"
 
 
def normalize_facts(value) -> list[str]:
    """Coerce whatever we were given -- a list, a JSON string, a dict, None,
    or a list holding numbers/objects -- into a clean list of non-empty
    strings. LLM output and old database rows are not guaranteed to have
    the shape we asked for, and everything downstream (the API response,
    the React list) assumes a list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except (ValueError, TypeError):
            return [stripped]  # legacy row: plain text that was never JSON
        if isinstance(parsed, str):
            return [parsed.strip()] if parsed.strip() else []
        return normalize_facts(parsed)
    if isinstance(value, dict):
        # {"facts": [...]} -> use the inner list; otherwise use the values.
        value = next(iter(value.values())) if len(value) == 1 and isinstance(next(iter(value.values())), list) \
            else list(value.values())
    if not isinstance(value, list):
        return []
    facts = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, bool):
            continue
        elif isinstance(item, (int, float)):
            text = str(item)
        elif isinstance(item, dict):
            text = "; ".join(f"{k}: {v}" for k, v in item.items() if v not in (None, ""))
        else:
            continue
        if text:
            facts.append(text)
    return facts
 
 
def failure_flags(summary, facts) -> tuple[bool, bool]:
    """(summary_failed, facts_failed): True when the stored text is one of
    OUR fallback messages rather than real generated content. Matches the
    exact prefix we wrote, never a substring of the text -- a genuine
    summary of a report about sales quotas must not be mistaken for a
    quota failure."""
    summary_failed = (summary or "").startswith(_SUMMARY_FAILURE_PREFIX)
    facts_failed = any(f.startswith(_FACTS_FAILURE_PREFIX) for f in normalize_facts(facts))
    return summary_failed, facts_failed
 
 
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
 
    @staticmethod
    def _summary_or_facts_unavailable(summary: str, facts) -> bool:
        """True if a previous attempt's summary and/or facts are actually
        the failure-fallback text (quota exhausted, unexpected error,
        etc.) rather than real generated content. Used to decide whether
        a re-upload of an already-fully-indexed document should just
        return the cached row as-is, or retry generation -- without
        this check, a document that failed to summarize once (e.g. during
        the daily quota window, or while the model name was stale) would
        show that failure message FOREVER on every future re-upload,
        since the chunks themselves indexed fine and the file looks
        "already done" by content hash.
        """
        return any(failure_flags(summary, facts))
 
    def _generate_summary_and_facts(self, full_text: str) -> tuple[str, list, bool]:
        """Shared by both a fresh ingest and a retry-on-reuse (see
        load_pdf below) -- the actual Gemini calls and their
        quota/error-fallback handling live in exactly one place instead
        of being duplicated between the two call sites."""
        doc_truncated = len(full_text) > SUMMARY_CONTEXT_CHARS
        text_for_summary = full_text[:SUMMARY_CONTEXT_CHARS]
 
        try:
            summary = self._generate(
                "Summarize this document in 3-4 sentences. Be concise and clear.\n\n"
                "Document:\n" + text_for_summary + "\n\nSummary:"
            )
            if not isinstance(summary, str) or not summary.strip():
                raise ValueError("model returned an empty summary")
            if doc_truncated:
                summary += (
                    f" (Note: this summary and the facts below are based on the first "
                    f"~{SUMMARY_CONTEXT_CHARS:,} characters of a longer document — chat "
                    f"answers still search the full text via embeddings, so the two may "
                    f"cover different parts of the document.)"
                )
        except QuotaError as e:
            wait_note = "Please wait a minute and try again." if not e.is_daily else "Quota resets daily — try again later."
            summary = f"{_SUMMARY_FAILURE_PREFIX} — Gemini quota limit reached. {wait_note}"
        except RetryableGeminiError:
            # TransientServerError (503, Google's infra under load) after
            # exhausting retries -- distinct message from a quota issue,
            # since "try again later today" isn't the right framing for
            # "Google's servers were briefly overloaded."
            summary = f"{_SUMMARY_FAILURE_PREFIX} — Gemini's servers are temporarily overloaded. Please try again shortly."
        except Exception:
            # The chunks are already embedded and stored, so any other
            # failure here degrades to a retryable fallback message (see
            # load_pdf's reuse path) instead of throwing that work away.
            logger.exception("summary generation failed")
            summary = f"{_SUMMARY_FAILURE_PREFIX} — an unexpected error occurred while summarizing. Please try again."
 
        facts_raw = None
        try:
            facts_raw = self._generate(
                "Extract key facts from this document. Return a JSON array of strings.\n"
                "Each string is one key fact, date, name, or important number.\n"
                "Return ONLY the JSON array, nothing else.\n\n"
                "Document:\n" + text_for_summary + "\n\nFacts:"
            )
            facts_clean = (facts_raw or "").strip().replace("```json", "").replace("```", "").strip()
            facts = normalize_facts(json.loads(facts_clean))
            if not facts:
                facts = [f"{_FACTS_FAILURE_PREFIX} — the model returned no usable facts. Please try again."]
        except QuotaError as e:
            wait_note = "Please wait a minute and try again." if not e.is_daily else "Quota resets daily — try again later."
            facts = [f"{_FACTS_FAILURE_PREFIX} — Gemini quota limit reached. {wait_note}"]
        except RetryableGeminiError:
            facts = [f"{_FACTS_FAILURE_PREFIX} — Gemini's servers are temporarily overloaded. Please try again shortly."]
        except Exception:
            # Covers a raised ClientError/timeout from self._generate() AND
            # text that failed to parse as JSON. Never store the raw model
            # output as if it were a fact: it would not be flagged as a
            # failure, so it would never be retried on re-upload.
            logger.exception("fact extraction failed")
            facts = [f"{_FACTS_FAILURE_PREFIX} — an unexpected error occurred during extraction."]
 
        return summary, facts, doc_truncated
 
    def load_pdf(self, contents: bytes, filename: str, force_reingest: bool = False, user_id: int | None = None) -> dict:
        content_hash = hashlib.sha256(contents).hexdigest()
 
        existing = None
        if not force_reingest:
            existing = get_document_by_hash(content_hash, user_id)
            if existing and not existing.get("partial"):
                if not self._summary_or_facts_unavailable(existing.get("summary"), existing.get("facts")):
                    existing["reused"] = True
                    return existing
                # Chunks are already indexed and embedded -- no need to
                # re-chunk or re-embed (that's the expensive, quota-heavy
                # part). Just re-extract the text (cheap, local, no
                # network call) and retry generating summary/facts,
                # overwriting the same doc_id's row in place.
                full_text = pdf_extraction.extract_text(contents)
                summary, facts, doc_truncated = self._generate_summary_and_facts(full_text)
                save_document(
                    existing["doc_id"], existing["filename"], content_hash, summary,
                    json.dumps(facts), chunk_count=existing.get("chunk_count", 0),
                    is_partial=False, user_id=user_id,
                )
                return {
                    "doc_id": existing["doc_id"],
                    "filename": existing["filename"],
                    "summary": summary,
                    "facts": facts,
                    "chunks": existing.get("chunk_count", 0),
                    "reused": True,
                    "summary_truncated": doc_truncated,
                }
 
        # A previous upload of this exact file that only got partway through
        # indexing. It is superseded by this attempt, but is deleted only
        # AFTER this attempt succeeds, so a failed retry never leaves the
        # user with nothing.
        stale_partial = existing if existing and existing.get("partial") else None
 
        full_text = pdf_extraction.extract_text(contents)
 
        doc_id = str(uuid.uuid4())
        chunks = self._chunk_text(full_text)
 
        try:
            result = self._ingest_new(doc_id, filename, content_hash, full_text, chunks, user_id)
        except Exception:
            # Any failure that is not the deliberate "partial" outcome
            # handled inside _ingest_new: remove whatever chunks were
            # already written so they don't sit orphaned with no documents
            # row pointing at them. Cleanup is best-effort -- it must never
            # hide the original error.
            try:
                removed = delete_chunks(doc_id)
                logger.warning("ingest failed; rolled back %d chunks", removed, extra={"doc_id": doc_id})
            except Exception:
                logger.exception("rollback of chunks failed", extra={"doc_id": doc_id})
            raise
 
        if stale_partial and (not result.get("partial") or result["chunks"] >= stale_partial.get("chunk_count", 0)):
            try:
                delete_document(stale_partial["doc_id"], user_id)
            except Exception:
                logger.exception("could not delete superseded partial document",
                                 extra={"doc_id": stale_partial["doc_id"]})
        return result
 
    def _ingest_new(self, doc_id: str, filename: str, content_hash: str, full_text: str,
                    chunks: list, user_id: int | None) -> dict:
        embedded_count = 0
        try:
            for batch_start in range(0, len(chunks), embeddings.EMBED_BATCH_SIZE):
                batch = chunks[batch_start:batch_start + embeddings.EMBED_BATCH_SIZE]
                batch_embeddings = self._embed_batch(batch)
                insert_chunks(batch, batch_embeddings, doc_id)
                embedded_count += len(batch)
        except RetryableGeminiError:
            if embedded_count == 0:
                raise
            summary = (
                f"Document partially indexed ({embedded_count}/{len(chunks)} chunks) — "
                "Gemini was temporarily unavailable mid-upload. Chat will only search "
                "the indexed portion until you re-upload."
            )
            facts = [f"{_FACTS_FAILURE_PREFIX} — indexing was interrupted before the whole document was processed."]
            save_document(doc_id, filename, content_hash, summary, json.dumps(facts),
                          chunk_count=embedded_count, is_partial=True, user_id=user_id)
            return {
                "doc_id": doc_id,
                "filename": filename,
                "summary": summary,
                "facts": facts,
                "chunks": embedded_count,
                "reused": False,
                "partial": True,
            }
 
        summary, facts, doc_truncated = self._generate_summary_and_facts(full_text)
 
        save_document(doc_id, filename, content_hash, summary, json.dumps(facts),
                      chunk_count=len(chunks), is_partial=False, user_id=user_id)
        return {
            "doc_id": doc_id,
            "filename": filename,
            "summary": summary,
            "facts": facts,
            "chunks": len(chunks),
            "reused": False,
            "summary_truncated": doc_truncated,
        }
 
    def delete_document(self, doc_id: str, user_id: int) -> bool:
        """Delete one of the caller's documents and its chunks. False means
        not found or not owned (deliberately indistinguishable)."""
        return delete_document(doc_id, user_id)
 
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
 
    def get_document_info(self, doc_id: str, user_id: int) -> dict:
        return get_document(doc_id, user_id)

"""Backward-compatible alias over the Phase 2 module split.

The actual logic now lives in focused modules:
  - pdf_extraction.py  : extract_text, chunk_text (pure functions)
  - gemini_client.py   : get_client, classify_quota_error, call_with_retry
  - embeddings.py      : embed_one, embed_batch
  - llm.py             : generate
  - rag_service.py     : RagService -- the actual orchestration, plus the
                          _embed/_embed_batch/_generate/_chunk_text instance
                          methods that load_pdf()/ask() call through (see
                          the docstring on RagService for why that
                          indirection exists)
  - exceptions.py      : QuotaError, ExtractionError, EmbeddingMismatchError

This module exists so `from app.chat_engine import ChatEngine, QuotaError`
keeps working everywhere it's already used (api.py, the existing test
suite) without changes. New code should import from the specific modules
above instead of this facade.
"""

from app.exceptions import (
    QuotaError,  # noqa: F401 -- re-exported for backward compatibility
)
from app.rag_service import RagService


class ChatEngine(RagService):
    """Kept as a distinct name for backward compatibility. All behavior
    is inherited from RagService unchanged."""

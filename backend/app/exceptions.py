class DocuMindError(Exception):
    """Base class for all DocuMind-specific errors, so calling code can
    catch `except DocuMindError` to mean 'something in our domain logic
    failed' as distinct from an unrelated library exception."""


class QuotaError(DocuMindError):
    """Carries whatever we could determine about a Gemini quota failure
    instead of collapsing it to a bare string. is_daily defaults to True
    (the safer assumption -- don't retry something that might not resolve
    for hours) until you've confirmed the real field name from a logged
    429 body. See app/gemini_client.py:classify_quota_error.
    """

    def __init__(self, raw: str, is_daily: bool = True):
        self.raw = raw
        self.is_daily = is_daily
        super().__init__("QUOTA_EXCEEDED")


class ExtractionError(DocuMindError, ValueError):
    """Raised when a PDF's text can't be meaningfully extracted (e.g. a
    scanned/image-only document). Subclasses ValueError too, so the
    existing `except ValueError` -> HTTP 422 mapping in api.py keeps
    working unchanged even though the raise site now lives in
    pdf_extraction.py instead of chat_engine.py.
    """


class EmbeddingMismatchError(DocuMindError):
    """Raised if a batch embed call returns a different number of vectors
    than inputs, in the rare case the caller needs to treat that as fatal
    rather than falling back to per-chunk embedding (the current default
    behavior in app/embeddings.py just logs and falls back, so this is
    currently unused but kept available for callers that want strict
    behavior instead).
    """

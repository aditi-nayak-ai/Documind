import time

from google import genai

from app.config import settings
from app.exceptions import QuotaError, RetryableGeminiError, TransientServerError
from app.logging_config import setup_logging

_client = None
logger = setup_logging("documind")


def get_client():
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options={"api_version": "v1"},
        )
    return _client


def classify_gemini_error(e) -> RetryableGeminiError:
    """Turns a raw Gemini ClientError/ServerError into either a QuotaError
    (429, your account's usage limits) or a TransientServerError (503,
    Google's own infrastructure under load) -- see exceptions.py for why
    both share the RetryableGeminiError base. Only call this after
    confirming the error is one of these two cases (see the "429"/
    "RESOURCE_EXHAUSTED"/"503"/"UNAVAILABLE" checks in embeddings.py and
    llm.py); anything else should propagate as a normal exception instead
    of being forced into one of these two boxes.
    """
    raw = str(e)
    if "503" in raw or "UNAVAILABLE" in raw:
        logger.warning("Gemini transient server error", extra={"raw_error": raw})
        return TransientServerError(raw=raw)

    logger.warning("Gemini quota error", extra={"raw_error": raw})
    # Best-guess heuristic until you've seen a real 429 payload logged
    # from Render. Common Gemini per-minute errors mention "PerMinute" or
    # "RPM"; daily errors mention "PerDay" or "RPD". Replace this once
    # you know the real string -- see the log line above, check Render
    # logs the next time a real quota error fires.
    lowered = raw.lower()
    is_daily = not any(tok in lowered for tok in ["perminute", "rpm", "per minute"])
    return QuotaError(raw=raw, is_daily=is_daily)


# Kept as an alias -- classify_quota_error was the original, narrower name
# before TransientServerError (503) was added alongside QuotaError (429).
# Existing imports/tests referencing this name keep working unchanged.
classify_quota_error = classify_gemini_error


def call_with_retry(fn, max_attempts: int = 3):
    """Retries any RetryableGeminiError (a per-minute QuotaError, or a
    TransientServerError) with exponential backoff (1s, 2s, 4s); a daily
    QuotaError raises immediately since retrying something that won't
    resolve for hours just wastes attempts. TransientServerError always
    has is_daily=False (see exceptions.py), so it always gets the same
    retry treatment as a per-minute quota error.
    """
    for attempt in range(max_attempts):
        try:
            return fn()
        except RetryableGeminiError as e:
            if e.is_daily or attempt == max_attempts - 1:
                raise
            time.sleep(2 ** attempt)

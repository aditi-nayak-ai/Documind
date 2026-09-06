import time

from google import genai

from app.config import settings
from app.exceptions import QuotaError
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


def classify_quota_error(e) -> QuotaError:
    """Best-guess heuristic until you've seen a real 429 payload logged
    from Render. Common Gemini per-minute errors mention "PerMinute" or
    "RPM"; daily errors mention "PerDay" or "RPD". Replace this once
    you know the real string -- see the log line below, check Render logs
    the next time a real quota error fires."""
    raw = str(e)
    logger.warning("Gemini quota error", extra={"raw_error": raw})
    lowered = raw.lower()
    is_daily = not any(tok in lowered for tok in ["perminute", "rpm", "per minute"])
    return QuotaError(raw=raw, is_daily=is_daily)


def call_with_retry(fn, max_attempts: int = 3):
    """Retries a per-minute QuotaError with exponential backoff (1s, 2s,
    4s); a daily QuotaError raises immediately since retrying something
    that won't resolve for hours just wastes attempts."""
    for attempt in range(max_attempts):
        try:
            return fn()
        except QuotaError as e:
            if e.is_daily or attempt == max_attempts - 1:
                raise
            time.sleep(2 ** attempt)

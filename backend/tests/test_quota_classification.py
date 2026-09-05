"""Unit tests for ChatEngine._classify_quota_error.

The source comment on this method is explicit that the per-minute vs.
per-day heuristic is a best guess pending a real observed 429 payload.
These tests pin down the CURRENT documented behavior so:
  1. A refactor doesn't silently change which errors get retried.
  2. Whoever eventually swaps in the real Gemini error field sees these
     tests fail in an obvious, intentional way, prompting an update here
     alongside the fix -- rather than the heuristic drifting unnoticed.
"""

import pytest


@pytest.mark.parametrize(
    "raw_error_text",
    [
        "429 RESOURCE_EXHAUSTED: Quota exceeded for quota metric 'PerMinute'",
        "Rate limit exceeded: RPM limit reached",
        "requests per minute quota exceeded",
    ],
)
def test_per_minute_errors_classified_as_not_daily(chat_engine, raw_error_text):
    err = chat_engine._classify_quota_error(Exception(raw_error_text))
    assert err.is_daily is False


@pytest.mark.parametrize(
    "raw_error_text",
    [
        "429 RESOURCE_EXHAUSTED: Quota exceeded for quota metric 'PerDay'",
        "Daily quota limit reached, resets at midnight UTC",
        "Something unrecognized with no rate-limit keywords at all",
    ],
)
def test_unrecognized_or_daily_errors_default_to_daily(chat_engine, raw_error_text):
    """Explicit daily mentions, AND anything unrecognized, should default
    to is_daily=True -- the safer assumption, since retrying something
    that won't resolve for hours just wastes attempts."""
    err = chat_engine._classify_quota_error(Exception(raw_error_text))
    assert err.is_daily is True


def test_raw_message_is_preserved_for_debugging(chat_engine):
    original = "429 some very specific Gemini error body"
    err = chat_engine._classify_quota_error(Exception(original))
    assert err.raw == original


def test_call_with_retry_retries_per_minute_errors(chat_engine, monkeypatch):
    """A per-minute QuotaError should be retried up to max_attempts before
    giving up; a daily one should raise immediately without retrying."""
    from app.chat_engine import QuotaError

    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise QuotaError(raw="PerMinute exceeded", is_daily=False)
        return "success"

    monkeypatch.setattr("time.sleep", lambda _: None)  # don't actually wait in tests
    result = chat_engine._call_with_retry(flaky, max_attempts=3)
    assert result == "success"
    assert calls["count"] == 3


def test_call_with_retry_gives_up_immediately_on_daily_quota(chat_engine):
    from app.chat_engine import QuotaError

    calls = {"count": 0}

    def always_daily():
        calls["count"] += 1
        raise QuotaError(raw="PerDay exceeded", is_daily=True)

    with pytest.raises(QuotaError):
        chat_engine._call_with_retry(always_daily, max_attempts=3)
    assert calls["count"] == 1  # no retries for a daily quota error


"""Step 5 tests: security hardening.
 
Covers four independent fixes:
  1. JWT_SECRET_KEY is validated at startup (missing or too short).
  2. Login takes the same code path (and roughly the same time) whether
     the email exists or not, so timing can't be used to enumerate accounts.
     Email is also case-normalized.
  3. /ingest never echoes raw exception text back to the client.
  4. A per-user (not per-IP) cap on total ingests, so one account can't
     drain the shared Gemini quota regardless of X-Forwarded-For spoofing.
"""
 
import time
import uuid
 
import pytest
from fastapi.testclient import TestClient
 
from app import database
from app.api import app, chat
from app.auth import (
    _DUMMY_PASSWORD_HASH,
    hash_password,
    normalize_email,
    verify_password,
)
from app.config import validate_settings_or_raise
 
# ---- config validation ------------------------------------------------------
 
 
def test_validate_settings_rejects_missing_secret(monkeypatch):
    from app import config
 
    monkeypatch.setattr(config.settings, "jwt_secret_key", "")
    with pytest.raises(RuntimeError, match="not set"):
        validate_settings_or_raise()
 
 
def test_validate_settings_rejects_short_secret(monkeypatch):
    from app import config
 
    monkeypatch.setattr(config.settings, "jwt_secret_key", "short")  # 5 bytes, the original 1-byte-accepting bug
    with pytest.raises(RuntimeError, match="too short"):
        validate_settings_or_raise()
 
 
def test_validate_settings_accepts_a_32_byte_secret(monkeypatch):
    from app import config
 
    monkeypatch.setattr(config.settings, "jwt_secret_key", "x" * 32)
    validate_settings_or_raise()  # must not raise
 
 
def test_conftests_own_test_secret_is_valid():
    """Sanity check: the fixture used by every other test file must itself
    pass this validation, or the whole suite would be resting on an
    invalid deployment config."""
    validate_settings_or_raise()  # must not raise, using the real env-loaded settings
 
 
# ---- normalize_email --------------------------------------------------------
 
 
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("User@Example.com", "user@example.com"),
        ("  a@b.com  ", "a@b.com"),
        ("already@lower.com", "already@lower.com"),
    ],
)
def test_normalize_email(raw, expected):
    assert normalize_email(raw) == expected
 
 
# ---- login timing / enumeration ---------------------------------------------
 
 
def test_dummy_hash_is_a_real_bcrypt_hash_not_a_placeholder():
    # If this were a plain string instead of a real hash, verify_password
    # would raise on an unknown-email login instead of returning False.
    assert verify_password("anything", _DUMMY_PASSWORD_HASH) is False
 
 
def test_login_runs_bcrypt_for_both_known_and_unknown_email(monkeypatch):
    """The core regression test: verify_password must be called exactly
    once per login attempt, regardless of whether the email exists.
    Before the fix, `not user or not verify_password(...)` short-circuited
    on `or` and skipped the call entirely for an unknown email -- this
    test would have caught that by observing zero calls."""
    import app.api as api_module
 
    calls = []
    real_verify = api_module.verify_password
 
    def spy(password, password_hash):
        calls.append(password_hash)
        return real_verify(password, password_hash)
 
    monkeypatch.setattr(api_module, "verify_password", spy)
    app.state.limiter.reset()
    client = TestClient(app)
 
    client.post("/auth/login", json={"email": f"{uuid.uuid4()}@nowhere.example", "password": "whatever123"})
    assert len(calls) == 1
    assert calls[0] == _DUMMY_PASSWORD_HASH  # compared against the dummy hash, not skipped
 
    database.create_user("real@example.com", hash_password("correct-password-1"))
    client.post("/auth/login", json={"email": "real@example.com", "password": "wrong-password"})
    assert len(calls) == 2
    assert calls[1] != _DUMMY_PASSWORD_HASH  # compared against the real stored hash
 
 
def test_login_timing_is_not_measurably_different_for_unknown_vs_known_email():
    """A coarser, end-to-end version of the test above: actually time both
    paths. This is inherently a little noisy, so it asserts an order-of-
    magnitude bound, not an exact match -- the point is that an unknown
    email must NOT be the fast path anymore."""
    app.state.limiter.reset()
    client = TestClient(app)
    database.create_user("timing@example.com", hash_password("correct-password-1"))
 
    def time_login(email, password, n=8):
        app.state.limiter.reset()  # each batch must fit under the 10/minute login limit on its own
        start = time.perf_counter()
        for _ in range(n):
            client.post("/auth/login", json={"email": email, "password": password})
        return (time.perf_counter() - start) / n
 
    unknown_avg = time_login(f"{uuid.uuid4()}@nowhere.example", "whatever123")
    wrong_password_avg = time_login("timing@example.com", "wrong-password-here")
 
    # Both paths now run one real bcrypt check, so neither should be
    # dramatically faster than the other. 2x is a generous margin for
    # test-environment noise; the pre-fix gap (skipping bcrypt entirely)
    # is typically an order of magnitude, not a small percentage.
    ratio = max(unknown_avg, wrong_password_avg) / min(unknown_avg, wrong_password_avg)
    assert ratio < 2.0, f"timing gap too large (ratio={ratio:.2f}); unknown-email login may be the fast path again"
 
 
def test_login_accepts_different_case_than_used_at_registration():
    app.state.limiter.reset()
    client = TestClient(app)
    client.post("/auth/register", json={"email": "MixedCase@Example.com", "password": "a-real-password-8plus"})
 
    response = client.post("/auth/login", json={"email": "mixedcase@example.com", "password": "a-real-password-8plus"})
    assert response.status_code == 200
 
 
def test_register_is_case_insensitive_for_duplicates():
    app.state.limiter.reset()
    client = TestClient(app)
    client.post("/auth/register", json={"email": "dup@example.com", "password": "a-real-password-8plus"})
 
    response = client.post("/auth/register", json={"email": "DUP@EXAMPLE.COM", "password": "another-password-1"})
    assert response.status_code == 409
 
 
# ---- /ingest no longer leaks raw exception text -----------------------------
 
 
def test_ingest_unexpected_error_does_not_leak_exception_text(monkeypatch):
    from tests.test_api import _minimal_pdf_bytes
 
    app.state.limiter.reset()
    client = TestClient(app)
    token = client.post(
        "/auth/register", json={"email": f"{uuid.uuid4()}@example.com", "password": "a-real-password-8plus"}
    ).json()["access_token"]
 
    def boom(*args, **kwargs):
        raise RuntimeError("/etc/secrets/db_password_hunter2 could not be read")
 
    monkeypatch.setattr(chat, "load_pdf", boom)
    response = client.post(
        "/ingest",
        files={"file": ("t.pdf", _minimal_pdf_bytes(), "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 500
    assert "hunter2" not in response.text
    assert "/etc/secrets" not in response.text
    assert response.json()["detail"] == "Something went wrong while processing this file. Please try again."
 
 
# ---- per-user ingest cap -----------------------------------------------------
 
 
def test_get_ingest_count_reflects_increments(test_user):
    assert database.get_ingest_count(test_user["id"]) == 0
    database.increment_user_usage(test_user["id"], "ingests")
    database.increment_user_usage(test_user["id"], "ingests")
    assert database.get_ingest_count(test_user["id"]) == 2
 
 
def test_get_ingest_count_is_zero_for_a_user_with_no_activity(test_user):
    # user_usage row exists (created alongside the user) but every count is 0.
    assert database.get_ingest_count(test_user["id"]) == 0
 
 
def test_ingest_is_blocked_once_the_per_user_cap_is_reached(monkeypatch):
    from tests.test_api import _minimal_pdf_bytes
 
    monkeypatch.setattr("app.api.settings.max_ingests_per_user", 2)
    monkeypatch.setattr(chat, "_embed_batch", lambda texts: [[0.001 * i for i in range(3072)] for _ in texts])
    monkeypatch.setattr(
        chat, "_generate", lambda prompt: "[]" if "Extract key facts" in prompt else "A summary."
    )
    app.state.limiter.reset()
    client = TestClient(app)
    token = client.post(
        "/auth/register", json={"email": f"{uuid.uuid4()}@example.com", "password": "a-real-password-8plus"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
 
    for i in range(2):
        response = client.post(
            "/ingest", files={"file": (f"{i}.pdf", _minimal_pdf_bytes() + bytes([i]), "application/pdf")},
            headers=headers,
        )
        assert response.status_code == 200, response.text
 
    blocked = client.post(
        "/ingest", files={"file": ("third.pdf", _minimal_pdf_bytes() + b"\x02", "application/pdf")}, headers=headers
    )
    assert blocked.status_code == 429
    assert "limit" in blocked.json()["detail"].lower()
 
 
def test_ingest_cap_is_per_user_not_shared(monkeypatch):
    """One user hitting the cap must not affect a different user."""
    from tests.test_api import _minimal_pdf_bytes
 
    monkeypatch.setattr("app.api.settings.max_ingests_per_user", 1)
    monkeypatch.setattr(chat, "_embed_batch", lambda texts: [[0.001 * i for i in range(3072)] for _ in texts])
    monkeypatch.setattr(
        chat, "_generate", lambda prompt: "[]" if "Extract key facts" in prompt else "A summary."
    )
    app.state.limiter.reset()
    client = TestClient(app)
    token_a = client.post(
        "/auth/register", json={"email": f"{uuid.uuid4()}@example.com", "password": "a-real-password-8plus"}
    ).json()["access_token"]
    token_b = client.post(
        "/auth/register", json={"email": f"{uuid.uuid4()}@example.com", "password": "a-real-password-8plus"}
    ).json()["access_token"]
 
    r1 = client.post(
        "/ingest", files={"file": ("a.pdf", _minimal_pdf_bytes(), "application/pdf")},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r1.status_code == 200
 
    r2 = client.post(
        "/ingest", files={"file": ("b.pdf", _minimal_pdf_bytes() + b"\x01", "application/pdf")},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r2.status_code == 200  # user B has their own, unused quota

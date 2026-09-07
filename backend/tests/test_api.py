"""API-level tests: real HTTP requests via FastAPI's TestClient, against
the real pgvector DB, with only the outbound Gemini calls mocked (see
`mocked_chat` fixture below). This exercises the actual request/response
cycle, rate limiting, error-to-HTTP-status mapping, and auth.
"""

import io
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api import app, chat
from app.chat_engine import QuotaError


@pytest.fixture
def client():
    """Reset slowapi's in-memory rate-limit storage before each test.
    Without this, tests share one client IP (TestClient's default) and
    the per-minute limits get exhausted partway through the test file,
    causing later tests to fail with 429s that have nothing to do with
    what's actually being tested."""
    app.state.limiter.reset()
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    """Registers a fresh user (unique email per call, so tests can run in
    any order without colliding on the UNIQUE constraint) and returns
    Authorization headers ready to attach to a request."""
    email = f"{uuid.uuid4()}@example.com"
    response = client.post("/auth/register", json={"email": email, "password": "a-real-password-8plus"})
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mocked_chat(monkeypatch):
    """Stub out the three Gemini-calling methods on the module-level `chat`
    instance used by the API routes, so /ingest and /query exercise real
    chunking + real DB + real error-mapping without hitting the network."""
    monkeypatch.setattr(chat, "_embed", lambda text: [0.001 * i for i in range(3072)])
    monkeypatch.setattr(
        chat, "_embed_batch", lambda texts: [[0.001 * i for i in range(3072)] for _ in texts]
    )
    monkeypatch.setattr(
        chat,
        "_generate",
        lambda prompt: '["Fact one", "Fact two"]' if "Extract key facts" in prompt else "A generated summary.",
    )
    return chat


def _minimal_pdf_bytes() -> bytes:
    """A tiny valid PDF with extractable text, built with pypdf so the test
    doesn't depend on a fixture binary file living in the repo."""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 750, "This is a test document with enough readable text " * 5)
    c.save()
    buf.seek(0)
    return buf.read()


# --- Health / stats / request-id (unauthenticated) -----------------------

def test_health_check(client):
    """/health now checks real DB connectivity (see database.check_connection),
    not just that the process is alive -- the test DB is always reachable
    in this suite, so this exercises the healthy path."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"


def test_health_check_reports_unhealthy_when_db_unreachable(client, monkeypatch):
    monkeypatch.setattr("app.api.check_connection", lambda: False)
    response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["database"] == "unreachable"


def test_response_includes_request_id_header(client):
    response = client.get("/health")
    assert "x-request-id" in response.headers


def test_request_id_is_echoed_back_when_client_supplies_one(client):
    response = client.get("/health", headers={"X-Request-ID": "test-fixed-id-123"})
    assert response.headers["x-request-id"] == "test-fixed-id-123"


def test_stats_endpoint_returns_counters(client):
    response = client.get("/stats")
    assert response.status_code == 200
    body = response.json()
    assert "ingests_total" in body
    assert "queries_total" in body
    assert "quota_errors_total" in body


def test_root(client):
    response = client.get("/")
    assert response.status_code == 200


# --- Auth ------------------------------------------------------------

def test_register_returns_a_usable_token(client):
    response = client.post(
        "/auth/register",
        json={"email": f"{uuid.uuid4()}@example.com", "password": "a-real-password-8plus"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_register_rejects_short_password(client):
    response = client.post(
        "/auth/register",
        json={"email": f"{uuid.uuid4()}@example.com", "password": "short"},
    )
    assert response.status_code == 422


def test_register_rejects_duplicate_email(client):
    email = f"{uuid.uuid4()}@example.com"
    first = client.post("/auth/register", json={"email": email, "password": "a-real-password-8plus"})
    assert first.status_code == 200
    second = client.post("/auth/register", json={"email": email, "password": "a-different-password"})
    assert second.status_code == 409


def test_login_with_correct_credentials_returns_token(client):
    email = f"{uuid.uuid4()}@example.com"
    client.post("/auth/register", json={"email": email, "password": "a-real-password-8plus"})
    response = client.post("/auth/login", json={"email": email, "password": "a-real-password-8plus"})
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_with_wrong_password_returns_401(client):
    email = f"{uuid.uuid4()}@example.com"
    client.post("/auth/register", json={"email": email, "password": "a-real-password-8plus"})
    response = client.post("/auth/login", json={"email": email, "password": "wrong-password"})
    assert response.status_code == 401


def test_login_with_unknown_email_returns_401(client):
    response = client.post(
        "/auth/login", json={"email": f"{uuid.uuid4()}@example.com", "password": "whatever12345"}
    )
    assert response.status_code == 401


def test_me_requires_auth(client):
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_me_returns_current_user(client, auth_headers):
    response = client.get("/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert "email" in response.json()


# --- Document routes require auth -----------------------------------

def test_ingest_requires_auth(client):
    response = client.post(
        "/ingest", files={"file": ("test.pdf", _minimal_pdf_bytes(), "application/pdf")}
    )
    assert response.status_code == 401


def test_query_requires_auth(client):
    response = client.post("/query", json={"question": "anything", "doc_id": "some-id"})
    assert response.status_code == 401


def test_get_document_route_requires_auth(client):
    response = client.get("/document/some-id")
    assert response.status_code == 401


def test_ingest_rejects_non_pdf(client, auth_headers):
    response = client.post(
        "/ingest", files={"file": ("notes.txt", b"just text", "text/plain")}, headers=auth_headers
    )
    assert response.status_code == 400


def test_ingest_rejects_oversized_upload(client, auth_headers):
    huge = b"x" * (11 * 1024 * 1024)  # over the 10 MB MAX_UPLOAD_BYTES
    response = client.post(
        "/ingest",
        files={"file": ("big.pdf", huge, "application/pdf")},
        headers=auth_headers,
    )
    assert response.status_code == 413


def test_ingest_and_query_full_roundtrip(client, mocked_chat, auth_headers):
    pdf_bytes = _minimal_pdf_bytes()

    ingest_response = client.post(
        "/ingest", files={"file": ("test.pdf", pdf_bytes, "application/pdf")}, headers=auth_headers
    )
    assert ingest_response.status_code == 200
    body = ingest_response.json()
    assert body["summary"] == "A generated summary."
    assert body["facts"] == ["Fact one", "Fact two"]
    assert body["reused"] is False
    doc_id = body["doc_id"]

    query_response = client.post(
        "/query", json={"question": "What is this about?", "doc_id": doc_id}, headers=auth_headers
    )
    assert query_response.status_code == 200
    assert "answer" in query_response.json()


def test_ingest_dedupes_identical_content(client, mocked_chat, auth_headers):
    pdf_bytes = _minimal_pdf_bytes()

    first = client.post(
        "/ingest", files={"file": ("a.pdf", pdf_bytes, "application/pdf")}, headers=auth_headers
    )
    second = client.post(
        "/ingest", files={"file": ("a.pdf", pdf_bytes, "application/pdf")}, headers=auth_headers
    )

    assert first.json()["reused"] is False
    assert second.json()["reused"] is True
    assert first.json()["doc_id"] == second.json()["doc_id"]


def test_ingest_maps_quota_error_to_429(client, mocked_chat, auth_headers, monkeypatch):
    def raise_quota(texts):
        raise QuotaError(raw="PerDay exceeded", is_daily=True)

    monkeypatch.setattr(mocked_chat, "_embed_batch", raise_quota)

    response = client.post(
        "/ingest",
        files={"file": ("test.pdf", _minimal_pdf_bytes(), "application/pdf")},
        headers=auth_headers,
    )
    assert response.status_code == 429


def test_query_unknown_document_returns_404(client, mocked_chat, auth_headers):
    """The doc doesn't exist for this (or any) user, so the ownership
    check in the /query route itself returns 404 before chat.ask() is
    ever called -- this replaced the old 'no relevant content' 200 path
    now that every doc_id must resolve to something the caller owns."""
    response = client.post(
        "/query", json={"question": "anything", "doc_id": "nonexistent-doc-id"}, headers=auth_headers
    )
    assert response.status_code == 404


def test_get_document_route_404_for_unknown_id(client, auth_headers):
    response = client.get("/document/does-not-exist", headers=auth_headers)
    assert response.status_code == 404


def test_get_document_route_returns_saved_document(client, mocked_chat, auth_headers):
    pdf_bytes = _minimal_pdf_bytes()
    ingest_response = client.post(
        "/ingest", files={"file": ("test.pdf", pdf_bytes, "application/pdf")}, headers=auth_headers
    )
    doc_id = ingest_response.json()["doc_id"]

    response = client.get(f"/document/{doc_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["doc_id"] == doc_id
    assert isinstance(response.json()["facts"], list)


def test_stats_increments_after_successful_ingest(client, mocked_chat, auth_headers):
    before = client.get("/stats").json()["ingests_total"]
    client.post(
        "/ingest", files={"file": ("test.pdf", _minimal_pdf_bytes(), "application/pdf")}, headers=auth_headers
    )
    after = client.get("/stats").json()["ingests_total"]
    assert after == before + 1


def test_stats_increments_quota_errors_on_429(client, mocked_chat, auth_headers, monkeypatch):
    def raise_quota(texts):
        raise QuotaError(raw="PerDay exceeded", is_daily=True)

    monkeypatch.setattr(mocked_chat, "_embed_batch", raise_quota)
    before = client.get("/stats").json()["quota_errors_total"]
    client.post(
        "/ingest", files={"file": ("test.pdf", _minimal_pdf_bytes(), "application/pdf")}, headers=auth_headers
    )
    after = client.get("/stats").json()["quota_errors_total"]
    assert after == before + 1


# --- Cross-user isolation --------------------------------------------

def test_user_cannot_access_another_users_document(client, mocked_chat):
    """The core guarantee the whole auth system exists for: user A's
    document must be completely unreachable to user B, even with the
    correct doc_id, through every route that takes one."""
    email_a = f"{uuid.uuid4()}@example.com"
    email_b = f"{uuid.uuid4()}@example.com"
    token_a = client.post("/auth/register", json={"email": email_a, "password": "password-a-12345"}).json()["access_token"]
    token_b = client.post("/auth/register", json={"email": email_b, "password": "password-b-12345"}).json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    ingest_response = client.post(
        "/ingest",
        files={"file": ("a-owns-this.pdf", _minimal_pdf_bytes(), "application/pdf")},
        headers=headers_a,
    )
    doc_id = ingest_response.json()["doc_id"]

    # User A can read their own document.
    assert client.get(f"/document/{doc_id}", headers=headers_a).status_code == 200

    # User B gets a 404, not the document, not a 403 that would confirm
    # the doc_id is valid -- a 404 is indistinguishable from "never existed".
    assert client.get(f"/document/{doc_id}", headers=headers_b).status_code == 404
    assert client.post(
        "/query", json={"question": "anything", "doc_id": doc_id}, headers=headers_b
    ).status_code == 404

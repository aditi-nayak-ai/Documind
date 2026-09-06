"""API-level tests: real HTTP requests via FastAPI's TestClient, against
the real pgvector DB, with only the outbound Gemini calls mocked (see
`mocked_chat` fixture below). This exercises the actual request/response
cycle, rate limiting, and error-to-HTTP-status mapping.
"""

import io

import pytest
from fastapi.testclient import TestClient

from app.api import app, chat
from app.chat_engine import QuotaError


@pytest.fixture
def client():
    """Reset slowapi's in-memory rate-limit storage before each test.
    Without this, tests share one client IP (TestClient's default) and
    the 5/minute /ingest limit gets exhausted partway through the test
    file, causing later tests to fail with 429s that have nothing to do
    with what's actually being tested."""
    app.state.limiter.reset()
    return TestClient(app)


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


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root(client):
    response = client.get("/")
    assert response.status_code == 200


def test_ingest_rejects_non_pdf(client):
    response = client.post(
        "/ingest", files={"file": ("notes.txt", b"just text", "text/plain")}
    )
    assert response.status_code == 400


def test_ingest_rejects_oversized_upload(client):
    huge = b"x" * (11 * 1024 * 1024)  # over the 10 MB MAX_UPLOAD_BYTES
    response = client.post(
        "/ingest",
        files={"file": ("big.pdf", huge, "application/pdf")},
    )
    assert response.status_code == 413


def test_ingest_and_query_full_roundtrip(client, mocked_chat):
    pdf_bytes = _minimal_pdf_bytes()

    ingest_response = client.post(
        "/ingest", files={"file": ("test.pdf", pdf_bytes, "application/pdf")}
    )
    assert ingest_response.status_code == 200
    body = ingest_response.json()
    assert body["summary"] == "A generated summary."
    assert body["facts"] == ["Fact one", "Fact two"]
    assert body["reused"] is False
    doc_id = body["doc_id"]

    query_response = client.post(
        "/query", json={"question": "What is this about?", "doc_id": doc_id}
    )
    assert query_response.status_code == 200
    assert "answer" in query_response.json()


def test_ingest_dedupes_identical_content(client, mocked_chat):
    pdf_bytes = _minimal_pdf_bytes()

    first = client.post("/ingest", files={"file": ("a.pdf", pdf_bytes, "application/pdf")})
    second = client.post("/ingest", files={"file": ("a.pdf", pdf_bytes, "application/pdf")})

    assert first.json()["reused"] is False
    assert second.json()["reused"] is True
    assert first.json()["doc_id"] == second.json()["doc_id"]


def test_ingest_maps_quota_error_to_429(client, mocked_chat, monkeypatch):
    def raise_quota(texts):
        raise QuotaError(raw="PerDay exceeded", is_daily=True)

    monkeypatch.setattr(mocked_chat, "_embed_batch", raise_quota)

    response = client.post(
        "/ingest",
        files={"file": ("test.pdf", _minimal_pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 429


def test_query_unknown_document_does_not_500(client, mocked_chat):
    response = client.post(
        "/query", json={"question": "anything", "doc_id": "nonexistent-doc-id"}
    )
    # No chunks match -> chat_engine.ask() returns its "no relevant content"
    # message rather than raising, so this should be a 200, not a 500.
    assert response.status_code == 200


def test_get_document_route_404_for_unknown_id(client):
    response = client.get("/document/does-not-exist")
    assert response.status_code == 404


def test_get_document_route_returns_saved_document(client, mocked_chat):
    pdf_bytes = _minimal_pdf_bytes()
    ingest_response = client.post(
        "/ingest", files={"file": ("test.pdf", pdf_bytes, "application/pdf")}
    )
    doc_id = ingest_response.json()["doc_id"]

    response = client.get(f"/document/{doc_id}")
    assert response.status_code == 200
    assert response.json()["doc_id"] == doc_id
    assert isinstance(response.json()["facts"], list)

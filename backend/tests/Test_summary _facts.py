"""Step 3 tests: LLM output and old database rows are untrusted. Whatever
the model returns, the API must hand the frontend a list of strings plus
explicit failure flags -- never raw model text, never a dict, and never a
guess based on a word appearing in the text."""
 
import json
import uuid
 
import pytest
from fastapi.testclient import TestClient
 
from app import database, pdf_extraction
from app.api import app, chat
from app.exceptions import QuotaError
from app.rag_service import failure_flags, normalize_facts
 
# ---- normalize_facts -------------------------------------------------------
 
 
@pytest.mark.parametrize(
    "raw, expected",
    [
        (["a", " b ", ""], ["a", "b"]),
        ('["a", "b"]', ["a", "b"]),
        ({"facts": ["a", "b"]}, ["a", "b"]),
        ({"x": "a", "y": "b"}, ["a", "b"]),
        ([1, 2.5, True, None, "c"], ["1", "2.5", "c"]),
        ([{"name": "Ada", "year": 1843}], ["name: Ada; year: 1843"]),
        ("plain legacy text", ["plain legacy text"]),
        ('"just a string"', ["just a string"]),
        (None, []),
        ("", []),
        (42, []),
    ],
)
def test_normalize_facts_always_returns_list_of_strings(raw, expected):
    assert normalize_facts(raw) == expected
 
 
# ---- failure_flags: exact prefix, never substring --------------------------
 
 
def test_summary_that_merely_mentions_quota_is_not_a_failure():
    summary = "The report reviews sales quota attainment across four regions."
    facts = ["The Q3 quota was 1.2M", "Quota attainment was 87%"]
    assert failure_flags(summary, facts) == (False, False)
 
 
def test_real_fallback_messages_are_flagged():
    summary = "Summary unavailable — Gemini quota limit reached. Quota resets daily — try again later."
    facts = ["Key facts unavailable — Gemini quota limit reached."]
    assert failure_flags(summary, facts) == (True, True)
 
 
def test_failure_flags_accepts_facts_stored_as_json_string():
    assert failure_flags("ok", json.dumps(["Key facts unavailable — x"])) == (False, True)
 
 
# ---- generation degrades instead of crashing -------------------------------
 
 
@pytest.fixture
def engine(chat_engine, monkeypatch):
    monkeypatch.setattr(pdf_extraction, "extract_text", lambda contents: "Some document text. " * 50)
    monkeypatch.setattr(chat_engine, "_embed_batch", lambda texts: [[0.001 * i for i in range(3072)] for _ in texts])
    return chat_engine
 
 
def _generate_with(summary, facts):
    def fake(prompt):
        value = facts if "Extract key facts" in prompt else summary
        if isinstance(value, Exception):
            raise value
        return value
 
    return fake
 
 
def test_unreadable_facts_are_flagged_not_stored_as_a_fact(engine, monkeypatch, test_user):
    monkeypatch.setattr(engine, "_generate", _generate_with("A fine summary.", "Sure! Here are some facts: ..."))
    result = engine.load_pdf(b"f1", "a.pdf", user_id=test_user["id"])
    assert len(result["facts"]) == 1
    assert result["facts"][0].startswith("Key facts unavailable")
    assert failure_flags(result["summary"], result["facts"]) == (False, True)
 
 
def test_facts_returned_as_a_json_object_are_normalized(engine, monkeypatch, test_user):
    monkeypatch.setattr(engine, "_generate", _generate_with("A fine summary.", '{"facts": ["One", "Two"]}'))
    result = engine.load_pdf(b"f2", "a.pdf", user_id=test_user["id"])
    assert result["facts"] == ["One", "Two"]
 
 
def test_empty_summary_degrades_and_keeps_the_indexed_document(engine, monkeypatch, test_user):
    monkeypatch.setattr(engine, "_generate", _generate_with(None, '["One"]'))
    result = engine.load_pdf(b"f3", "a.pdf", user_id=test_user["id"])
    assert result["summary"].startswith("Summary unavailable")
    assert database.get_document(result["doc_id"], test_user["id"]) is not None  # chunks kept
 
 
def test_unexpected_summary_error_degrades_and_keeps_the_indexed_document(engine, monkeypatch, test_user):
    monkeypatch.setattr(engine, "_generate", _generate_with(RuntimeError("model 400"), '["One"]'))
    result = engine.load_pdf(b"f4", "a.pdf", user_id=test_user["id"])
    assert result["summary"].startswith("Summary unavailable")
    assert database.get_document(result["doc_id"], test_user["id"]) is not None
 
 
def test_reupload_retries_a_degraded_summary(engine, monkeypatch, test_user):
    monkeypatch.setattr(engine, "_generate", _generate_with(QuotaError("q", is_daily=True), '["One"]'))
    first = engine.load_pdf(b"f5", "a.pdf", user_id=test_user["id"])
    assert first["summary"].startswith("Summary unavailable")
 
    monkeypatch.setattr(engine, "_generate", _generate_with("A real summary.", '["One"]'))
    second = engine.load_pdf(b"f5", "a.pdf", user_id=test_user["id"])
    assert second["doc_id"] == first["doc_id"]  # same document, chunks not re-embedded
    assert second["summary"] == "A real summary."
 
 
# ---- what the HTTP API returns ---------------------------------------------
 
 
@pytest.fixture
def client():
    app.state.limiter.reset()
    return TestClient(app)
 
 
@pytest.fixture
def auth_headers(client):
    r = client.post("/auth/register", json={"email": f"{uuid.uuid4()}@example.com", "password": "a-real-password-8plus"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
 
 
def test_get_document_normalizes_legacy_dict_facts_and_adds_flags(client, auth_headers, test_user):
    # A row written by the old code, when facts could be a JSON object.
    me = client.get("/auth/me", headers=auth_headers).json()
    doc_id = str(uuid.uuid4())
    database.save_document(doc_id, "old.pdf", "h", "The sales quota report.", json.dumps({"a": "Fact A", "b": "Fact B"}),
                           chunk_count=1, is_partial=False, user_id=me["id"])
    body = client.get(f"/document/{doc_id}", headers=auth_headers).json()
    assert body["facts"] == ["Fact A", "Fact B"]
    assert body["summary_failed"] is False and body["facts_failed"] is False
 
 
def test_ingest_response_includes_failure_flags(client, auth_headers, monkeypatch):
    from tests.test_api import _minimal_pdf_bytes
 
    monkeypatch.setattr(chat, "_embed_batch", lambda texts: [[0.001 * i for i in range(3072)] for _ in texts])
    monkeypatch.setattr(chat, "_generate", _generate_with(QuotaError("q", is_daily=True), '{"facts": ["Only fact"]}'))
    body = client.post("/ingest", files={"file": ("t.pdf", _minimal_pdf_bytes(), "application/pdf")},
                       headers=auth_headers).json()
    assert body["summary_failed"] is True
    assert body["facts_failed"] is False
    assert body["facts"] == ["Only fact"]

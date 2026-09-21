"""Step 2 tests: an ingest either fully succeeds, is deliberately kept as a
"partial" document, or leaves NOTHING behind. Also covers owner-scoped
deletion. Only the Gemini calls are faked; chunking, batching and every
database write are real.
"""
 
import pytest
from sqlalchemy import text
 
from app import database, pdf_extraction
from app.exceptions import QuotaError
 
# ~31,500 characters -> well over 60 chunks -> at least 3 embedding batches of 20.
LONG_TEXT = "The quick brown fox jumps over the lazy dog. " * 700
GOOD_VECTOR = [0.001 * i for i in range(3072)]
 
 
def _count_chunks(doc_id: str | None = None) -> int:
    with database.get_engine().connect() as conn:
        if doc_id is None:
            return conn.execute(text("SELECT count(*) FROM document_chunks")).scalar()
        return conn.execute(
            text("SELECT count(*) FROM document_chunks WHERE document_name = :d"), {"d": doc_id}
        ).scalar()
 
 
def _count_documents() -> int:
    with database.get_engine().connect() as conn:
        return conn.execute(text("SELECT count(*) FROM documents")).scalar()
 
 
@pytest.fixture
def engine(chat_engine, monkeypatch):
    """A ChatEngine whose text extraction returns LONG_TEXT and whose Gemini
    calls succeed. Individual tests override _embed_batch / _generate to
    inject failures."""
    monkeypatch.setattr(pdf_extraction, "extract_text", lambda contents: LONG_TEXT)
    monkeypatch.setattr(chat_engine, "_embed_batch", lambda texts: [GOOD_VECTOR for _ in texts])
    monkeypatch.setattr(
        chat_engine,
        "_generate",
        lambda prompt: '["Fact one", "Fact two"]' if "Extract key facts" in prompt else "A generated summary.",
    )
    return chat_engine
 
 
def _fail_after_first_batch(exc):
    """An _embed_batch replacement: the first call succeeds, the second raises exc."""
    calls = {"n": 0}
 
    def fake(texts):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise exc
        return [GOOD_VECTOR for _ in texts]
 
    return fake
 
 
# ---- insert_chunks ---------------------------------------------------------
 
 
def test_insert_chunks_writes_every_row(doc_id):
    database.insert_chunks(["a", "b", "c"], [GOOD_VECTOR] * 3, doc_id)
    assert _count_chunks(doc_id) == 3
 
 
def test_insert_chunks_is_all_or_nothing(doc_id):
    # The middle vector has the wrong dimension, so Postgres rejects it.
    # The two valid rows in the same call must NOT be left behind.
    bad = [1.0, 2.0, 3.0]
    with pytest.raises(Exception):  # noqa: B017 -- driver-specific DataError, any DB error proves the point
        database.insert_chunks(["a", "b", "c"], [GOOD_VECTOR, bad, GOOD_VECTOR], doc_id)
    assert _count_chunks(doc_id) == 0
 
 
def test_insert_chunks_rejects_length_mismatch(doc_id):
    with pytest.raises(ValueError):
        database.insert_chunks(["a", "b"], [GOOD_VECTOR], doc_id)
    assert _count_chunks(doc_id) == 0
 
 
# ---- rollback on failure ---------------------------------------------------
 
 
def test_non_retryable_error_midway_rolls_back_every_chunk(engine, monkeypatch, test_user):
    monkeypatch.setattr(engine, "_embed_batch", _fail_after_first_batch(RuntimeError("bad request")))
    with pytest.raises(RuntimeError):
        engine.load_pdf(b"file-a", "a.pdf", user_id=test_user["id"])
    assert _count_chunks() == 0  # the 20 chunks from batch one were removed
    assert _count_documents() == 0
 
 
def test_failure_after_all_chunks_stored_still_rolls_back(engine, monkeypatch, test_user):
    # Every chunk embeds and is stored, then saving the documents row fails.
    # Before Step 2 this left the whole document's chunks orphaned.
    def boom(*args, **kwargs):
        raise RuntimeError("database write failed")
 
    monkeypatch.setattr("app.rag_service.save_document", boom)
    with pytest.raises(RuntimeError):
        engine.load_pdf(b"file-a", "a.pdf", user_id=test_user["id"])
    assert _count_chunks() == 0
    assert _count_documents() == 0
 
 
# ---- deliberate partial ----------------------------------------------------
 
 
def test_quota_error_midway_keeps_a_partial_document(engine, monkeypatch, test_user):
    monkeypatch.setattr(engine, "_embed_batch", _fail_after_first_batch(QuotaError("quota", is_daily=True)))
    result = engine.load_pdf(b"file-a", "a.pdf", user_id=test_user["id"])
    assert result["partial"] is True
    assert result["chunks"] == 20
    assert _count_chunks(result["doc_id"]) == 20
    stored = database.get_document(result["doc_id"], test_user["id"])
    assert stored["is_partial"] is True
 
 
def test_reupload_replaces_the_old_partial_document(engine, monkeypatch, test_user):
    monkeypatch.setattr(engine, "_embed_batch", _fail_after_first_batch(QuotaError("quota", is_daily=True)))
    partial = engine.load_pdf(b"file-a", "a.pdf", user_id=test_user["id"])
    old_id = partial["doc_id"]
 
    # Quota is back: same file, working embeddings.
    monkeypatch.setattr(engine, "_embed_batch", lambda texts: [GOOD_VECTOR for _ in texts])
    full = engine.load_pdf(b"file-a", "a.pdf", user_id=test_user["id"])
 
    assert full["doc_id"] != old_id
    assert not full.get("partial")
    assert database.get_document(old_id, test_user["id"]) is None
    assert _count_chunks(old_id) == 0
    assert _count_chunks(full["doc_id"]) == full["chunks"]
    assert _count_documents() == 1
 
 
def test_failed_retry_keeps_the_old_partial_document(engine, monkeypatch, test_user):
    monkeypatch.setattr(engine, "_embed_batch", _fail_after_first_batch(QuotaError("quota", is_daily=True)))
    partial = engine.load_pdf(b"file-a", "a.pdf", user_id=test_user["id"])
 
    monkeypatch.setattr(engine, "_embed_batch", _fail_after_first_batch(RuntimeError("bad request")))
    with pytest.raises(RuntimeError):
        engine.load_pdf(b"file-a", "a.pdf", user_id=test_user["id"])
 
    # The user still has the partial document; the failed retry left nothing extra.
    assert database.get_document(partial["doc_id"], test_user["id"]) is not None
    assert _count_chunks() == partial["chunks"]
 
 
# ---- delete_document -------------------------------------------------------
 
 
def test_delete_document_removes_row_and_chunks(doc_id, test_user):
    database.insert_chunks(["a", "b"], [GOOD_VECTOR] * 2, doc_id)
    database.save_document(doc_id, "f.pdf", "h", "s", "[]", chunk_count=2, is_partial=False, user_id=test_user["id"])
 
    assert database.delete_document(doc_id, test_user["id"]) is True
    assert database.get_document(doc_id, test_user["id"]) is None
    assert _count_chunks(doc_id) == 0
 
 
def test_delete_document_refuses_someone_elses_document(doc_id, test_user):
    from app.auth import hash_password
 
    other = database.create_user("intruder@example.com", hash_password("another-password-1"))
    database.insert_chunks(["a"], [GOOD_VECTOR], doc_id)
    database.save_document(doc_id, "f.pdf", "h", "s", "[]", chunk_count=1, is_partial=False, user_id=test_user["id"])
 
    assert database.delete_document(doc_id, other["id"]) is False
    assert database.get_document(doc_id, test_user["id"]) is not None  # untouched
    assert _count_chunks(doc_id) == 1
 
 
def test_delete_document_unknown_id_returns_false(test_user):
    assert database.delete_document("does-not-exist", test_user["id"]) is False

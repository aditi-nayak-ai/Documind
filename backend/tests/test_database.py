"""Integration tests against a REAL pgvector Postgres instance.

These deliberately do NOT mock the DB layer. The things worth catching here
-- the halfvec cast for >2000-dim vectors, HNSW index creation, cosine
distance ordering, ON CONFLICT upsert behavior -- only exist in real SQL
execution. A mocked DB layer would happily pass while any of these silently
broke.

Run locally against docker-compose's `db` service, or in CI against the
postgres-pgvector service container (see ci.yml).
"""

from app import database


def test_init_db_is_idempotent():
    """init_db() runs on every app startup (see lifespan() in api.py) --
    it must be safe to call repeatedly against an already-initialized DB."""
    database.init_db()
    database.init_db()  # should not raise


def test_insert_and_search_chunks_roundtrip(doc_id, fake_embedding):
    database.insert_chunk("The sky is blue.", fake_embedding, doc_id)
    database.insert_chunk("Water boils at 100 degrees.", fake_embedding, doc_id)

    results = database.search_chunks(fake_embedding, doc_id, top_k=5)

    assert len(results) == 2
    assert "The sky is blue." in results
    assert "Water boils at 100 degrees." in results


def test_search_chunks_respects_top_k(doc_id, fake_embedding):
    for i in range(5):
        database.insert_chunk(f"Chunk number {i}", fake_embedding, doc_id)

    results = database.search_chunks(fake_embedding, doc_id, top_k=2)
    assert len(results) == 2


def test_search_chunks_is_scoped_to_document(doc_id, fake_embedding):
    """A chunk belonging to a different doc_id must never leak into another
    document's search results -- this is the index the source comment says
    exists specifically to make this filter fast, so it's worth also
    asserting it's *correct*, not just present."""
    other_doc_id = "some-other-document-id"
    database.insert_chunk("Belongs to other_doc_id", fake_embedding, other_doc_id)
    database.insert_chunk("Belongs to doc_id", fake_embedding, doc_id)

    results = database.search_chunks(fake_embedding, doc_id, top_k=10)
    assert results == ["Belongs to doc_id"]


def test_search_chunks_orders_by_cosine_distance():
    """Closest vector should come back first."""
    import uuid
    doc = str(uuid.uuid4())
    close_vec = [1.0] + [0.0] * 3071
    far_vec = [-1.0] + [0.0] * 3071
    query_vec = [1.0] + [0.0] * 3071

    database.insert_chunk("far", far_vec, doc)
    database.insert_chunk("close", close_vec, doc)

    results = database.search_chunks(query_vec, doc, top_k=2)
    assert results[0] == "close"


def test_save_and_get_document_roundtrip(doc_id):
    database.save_document(
        doc_id=doc_id,
        filename="report.pdf",
        content_hash="abc123",
        summary="A short summary.",
        facts='["fact one", "fact two"]',
        chunk_count=4,
        is_partial=False,
    )

    doc = database.get_document(doc_id)
    assert doc is not None
    assert doc["filename"] == "report.pdf"
    assert doc["summary"] == "A short summary."
    assert doc["chunk_count"] == 4
    assert doc["is_partial"] is False


def test_save_document_upserts_on_conflict(doc_id):
    """save_document is called once at initial ingest, and again if a
    partial (quota-interrupted) document later gets force-reingested --
    the second save must overwrite, not duplicate or error."""
    database.save_document(doc_id, "v1.pdf", "hash1", "old summary", "[]", chunk_count=1, is_partial=True)
    database.save_document(doc_id, "v1.pdf", "hash1", "new summary", "[]", chunk_count=10, is_partial=False)

    doc = database.get_document(doc_id)
    assert doc["summary"] == "new summary"
    assert doc["chunk_count"] == 10
    assert doc["is_partial"] is False


def test_get_document_returns_none_for_unknown_id():
    assert database.get_document("does-not-exist") is None


def test_get_document_by_hash_returns_most_recent(doc_id):
    database.save_document(doc_id, "a.pdf", "same-hash", "summary", "[]", chunk_count=1, is_partial=False)

    existing = database.get_document_by_hash("same-hash")
    assert existing is not None
    assert existing["doc_id"] == doc_id


def test_get_document_by_hash_returns_none_for_unknown_hash():
    assert database.get_document_by_hash("no-such-hash") is None


def test_clear_document_removes_chunks_and_metadata(doc_id, fake_embedding):
    database.insert_chunk("some content", fake_embedding, doc_id)
    database.save_document(doc_id, "f.pdf", "h", "s", "[]", chunk_count=1, is_partial=False)

    database.clear_document(doc_id)

    assert database.get_document(doc_id) is None
    assert database.search_chunks(fake_embedding, doc_id, top_k=5) == []

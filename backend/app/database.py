import os
from sqlalchemy import create_engine, text

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            os.getenv("DATABASE_URL"),
            pool_pre_ping=True,
            pool_recycle=300,
        )
    return _engine


def init_db():
    with get_engine().connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id SERIAL PRIMARY KEY,
                content TEXT NOT NULL,
                embedding vector(3072),
                document_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS documents (
                id SERIAL PRIMARY KEY,
                doc_id TEXT UNIQUE NOT NULL,
                filename TEXT NOT NULL,
                content_hash TEXT,
                summary TEXT,
                facts TEXT,
                chunk_count INTEGER DEFAULT 0,
                is_partial BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # Migration-safe: add columns if the table pre-dates them.
        conn.execute(text("""
            ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_count INTEGER DEFAULT 0
        """))
        conn.execute(text("""
            ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_partial BOOLEAN DEFAULT FALSE
        """))
        conn.execute(text("""
            ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash TEXT
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents (content_hash)
        """))
        # Every search_chunks() call filters WHERE document_name = :doc_id before
        # sorting by vector distance. Without this, that filter is a sequential
        # scan over the whole document_chunks table on every single query.
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_document_chunks_document_name
            ON document_chunks (document_name)
        """))
        conn.commit()

    # The ANN index on `embedding` is handled in its own connection/transaction,
    # deliberately isolated from everything above. pgvector's plain `vector`
    # type can only be HNSW-indexed up to 2,000 dimensions — Gemini's
    # embeddings are 3,072-dim, so a direct index on `embedding` fails outright
    # (this took the app down once already, since a failed statement here
    # previously crashed startup). Casting to `halfvec`, which supports HNSW
    # up to 4,000 dimensions, is pgvector's own documented workaround for
    # exactly this case. If index creation fails for any reason (older
    # pgvector version, future limit changes, etc.), we log it and continue —
    # search still works via sequential scan, just slower as the table grows.
    # A missing ANN index should never be a reason the whole API refuses to boot.
    try:
        with get_engine().connect() as conn:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding
                ON document_chunks
                USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
            """))
            conn.commit()
    except Exception as e:
        print(f"WARN: could not create ANN index on document_chunks.embedding: {e}")
        print("Vector search will still work but will use a full scan instead of an index.")


def insert_chunk(content: str, embedding: list, doc_id: str):
    vector_str = "[" + ",".join(map(str, embedding)) + "]"
    with get_engine().connect() as conn:
        conn.execute(
            text("""
                INSERT INTO document_chunks (content, embedding, document_name)
                VALUES (:content, :embedding, :document_name)
            """),
            {"content": content, "embedding": vector_str, "document_name": doc_id}
        )
        conn.commit()


def search_chunks(query_embedding: list, doc_id: str, top_k: int = 3) -> list:
    vector_str = "[" + ",".join(map(str, query_embedding)) + "]"
    with get_engine().connect() as conn:
        result = conn.execute(
            text("""
                SELECT content FROM document_chunks
                WHERE document_name = :document_name
                ORDER BY embedding::halfvec(3072) <=> CAST(:embedding AS halfvec(3072))
                LIMIT :k
            """),
            {"embedding": vector_str, "k": top_k, "document_name": doc_id}
        )
        return [row[0] for row in result.fetchall()]


def save_document(doc_id: str, filename: str, content_hash: str, summary: str, facts: str,
                   chunk_count: int = 0, is_partial: bool = False):
    with get_engine().connect() as conn:
        conn.execute(
            text("""
                INSERT INTO documents (doc_id, filename, content_hash, summary, facts, chunk_count, is_partial)
                VALUES (:doc_id, :filename, :content_hash, :summary, :facts, :chunk_count, :is_partial)
                ON CONFLICT (doc_id) DO UPDATE
                SET summary = EXCLUDED.summary,
                    facts = EXCLUDED.facts,
                    chunk_count = EXCLUDED.chunk_count,
                    is_partial = EXCLUDED.is_partial
            """),
            {"doc_id": doc_id, "filename": filename, "content_hash": content_hash,
             "summary": summary, "facts": facts, "chunk_count": chunk_count, "is_partial": is_partial}
        )
        conn.commit()


def get_document(doc_id: str) -> dict:
    with get_engine().connect() as conn:
        result = conn.execute(
            text("""
                SELECT doc_id, filename, summary, facts, chunk_count, is_partial, content_hash
                FROM documents WHERE doc_id = :doc_id
            """),
            {"doc_id": doc_id}
        ).fetchone()
        if result:
            return {"doc_id": result[0], "filename": result[1], "summary": result[2],
                    "facts": result[3], "chunk_count": result[4], "is_partial": result[5],
                    "content_hash": result[6]}
        return None


def get_document_by_hash(content_hash: str) -> dict:
    """
    Look up the most recent document with this exact content hash.
    Hash-based, not filename-based — editing a PDF and re-uploading it
    under the same name will no longer silently reuse stale chunks.
    """
    with get_engine().connect() as conn:
        result = conn.execute(
            text("""
                SELECT doc_id, filename, summary, facts, chunk_count, is_partial
                FROM documents
                WHERE content_hash = :content_hash
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"content_hash": content_hash}
        ).fetchone()
        if result:
            return {"doc_id": result[0], "filename": result[1], "summary": result[2],
                    "facts": result[3], "chunk_count": result[4], "partial": result[5]}
        return None


def clear_document(doc_id: str):
    with get_engine().connect() as conn:
        conn.execute(
            text("DELETE FROM document_chunks WHERE document_name = :document_name"),
            {"document_name": doc_id}
        )
        conn.execute(
            text("DELETE FROM documents WHERE doc_id = :doc_id"),
            {"doc_id": doc_id}
        )
        conn.commit()

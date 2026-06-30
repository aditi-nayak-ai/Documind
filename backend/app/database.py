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
        conn.commit()


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
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :k
            """),
            {"embedding": vector_str, "k": top_k, "document_name": doc_id}
        )
        return [row[0] for row in result.fetchall()]


def save_document(doc_id: str, filename: str, summary: str, facts: str, chunk_count: int = 0, is_partial: bool = False):
    with get_engine().connect() as conn:
        conn.execute(
            text("""
                INSERT INTO documents (doc_id, filename, summary, facts, chunk_count, is_partial)
                VALUES (:doc_id, :filename, :summary, :facts, :chunk_count, :is_partial)
                ON CONFLICT (doc_id) DO UPDATE
                SET summary = EXCLUDED.summary,
                    facts = EXCLUDED.facts,
                    chunk_count = EXCLUDED.chunk_count,
                    is_partial = EXCLUDED.is_partial
            """),
            {"doc_id": doc_id, "filename": filename, "summary": summary,
             "facts": facts, "chunk_count": chunk_count, "is_partial": is_partial}
        )
        conn.commit()


def get_document(doc_id: str) -> dict:
    with get_engine().connect() as conn:
        result = conn.execute(
            text("SELECT doc_id, filename, summary, facts, chunk_count FROM documents WHERE doc_id = :doc_id"),
            {"doc_id": doc_id}
        ).fetchone()
        if result:
            return {"doc_id": result[0], "filename": result[1], "summary": result[2],
                    "facts": result[3], "chunk_count": result[4]}
        return None


def get_document_by_filename(filename: str) -> dict:
    """
    Look up the most recent document with this exact filename.
    Used to detect duplicate uploads so we can skip re-embedding
    and re-generating summary/facts, which is what actually burns
    Gemini quota — not how often the app is opened.
    """
    with get_engine().connect() as conn:
        result = conn.execute(
            text("""
                SELECT doc_id, filename, summary, facts, chunk_count, is_partial
                FROM documents
                WHERE filename = :filename
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"filename": filename}
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

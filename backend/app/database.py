import os
from sqlalchemy import create_engine, text

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(os.getenv("DATABASE_URL"))
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
                name TEXT UNIQUE NOT NULL,
                summary TEXT,
                facts TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()


def insert_chunk(content: str, embedding: list, document_name: str):
    vector_str = "[" + ",".join(map(str, embedding)) + "]"
    with get_engine().connect() as conn:
        conn.execute(
            text("""
                INSERT INTO document_chunks (content, embedding, document_name)
                VALUES (:content, :embedding, :document_name)
            """),
            {"content": content, "embedding": vector_str, "document_name": document_name}
        )
        conn.commit()


def search_chunks(query_embedding: list, document_name: str, top_k: int = 3) -> list:
    vector_str = "[" + ",".join(map(str, query_embedding)) + "]"
    with get_engine().connect() as conn:
        result = conn.execute(
            text("""
                SELECT content FROM document_chunks
                WHERE document_name = :document_name
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :k
            """),
            {"embedding": vector_str, "k": top_k, "document_name": document_name}
        )
        return [row[0] for row in result.fetchall()]


def save_document(name: str, summary: str, facts: str):
    with get_engine().connect() as conn:
        conn.execute(
            text("""
                INSERT INTO documents (name, summary, facts)
                VALUES (:name, :summary, :facts)
                ON CONFLICT (name) DO UPDATE
                SET summary = EXCLUDED.summary,
                    facts = EXCLUDED.facts
            """),
            {"name": name, "summary": summary, "facts": facts}
        )
        conn.commit()


def get_document(name: str) -> dict:
    with get_engine().connect() as conn:
        result = conn.execute(
            text("SELECT name, summary, facts FROM documents WHERE name = :name"),
            {"name": name}
        ).fetchone()
        if result:
            return {"name": result[0], "summary": result[1], "facts": result[2]}
        return None


def clear_document(document_name: str):
    with get_engine().connect() as conn:
        conn.execute(
            text("DELETE FROM document_chunks WHERE document_name = :document_name"),
            {"document_name": document_name}
        )
        conn.execute(
            text("DELETE FROM documents WHERE name = :name"),
            {"name": document_name}
        )
        conn.commit()

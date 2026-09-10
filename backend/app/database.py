from sqlalchemy import create_engine, text
 
from app.config import settings
from app.logging_config import setup_logging
 
logger = setup_logging("documind")
 
_engine = None
 
 
def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_recycle=300,
        )
    return _engine
 
 
def check_connection() -> bool:
    """Used by GET /health to verify the DB is actually reachable, not
    just that the FastAPI process is alive. A crashed/unreachable DB
    should surface as an unhealthy service, not a silent 200."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 -- deliberate: any failure here means "not healthy", the specific exception type doesn't change the health-check outcome
        return False
 
 
def init_db():
    with get_engine().connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
 
        # --- Auth tables --------------------------------------------------
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # Per-user counters, incremented alongside the global counters in
        # app/metrics.py. Separate from that in-memory, process-local
        # Metrics class: this is per-user, persisted, and survives a
        # restart -- the two serve different purposes and neither
        # replaces the other.
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_usage (
                user_id INTEGER PRIMARY KEY REFERENCES users(id),
                ingests_count INTEGER DEFAULT 0,
                queries_count INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
 
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
        # Nullable and not backfilled automatically -- see MIGRATION.md.
        # Existing rows get user_id = NULL, which matches no authenticated
        # user (NULL = :id is NULL, not true, in SQL), so they become
        # unreachable via the user-scoped queries below until manually
        # backfilled or re-uploaded. Deliberate: the alternative is
        # leaving pre-auth rows readable by any account, which defeats
        # the point of adding auth in the first place.
        conn.execute(text("""
            ALTER TABLE documents ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)
        """))
        # True when summary/facts generation hit a QuotaError and the
        # stored summary/facts are just the "unavailable, quota reached"
        # placeholder text -- NOT when the chunks/embeddings failed (see
        # is_partial for that). Without this flag, the content-hash reuse
        # path in RagService.load_pdf() had no way to tell "a real summary
        # was generated" apart from "a placeholder was saved because the
        # quota was hit at that moment" -- so every re-upload of the same
        # file just served the stale placeholder back forever, even long
        # after the quota had reset. This flag is what lets a re-upload
        # retry ONLY the summary/facts generation (cheap) instead of
        # either silently failing forever or re-embedding everything
        # (expensive, and burns embed quota for no reason).
        conn.execute(text("""
            ALTER TABLE documents ADD COLUMN IF NOT EXISTS needs_summary_retry BOOLEAN DEFAULT FALSE
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents (content_hash)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents (user_id)
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
    except Exception as e:  # noqa: BLE001 -- deliberate: a missing ANN index should degrade to a full scan, never block app startup, regardless of which pgvector/driver error caused it
        logger.warning(
            "Could not create ANN index on document_chunks.embedding -- "
            "vector search will still work but will use a full scan instead of an index",
            extra={"error": str(e)},
        )
 
 
# --- Users ------------------------------------------------------------
 
def create_user(email: str, password_hash: str) -> dict:
    with get_engine().connect() as conn:
        result = conn.execute(
            text("""
                INSERT INTO users (email, password_hash)
                VALUES (:email, :password_hash)
                RETURNING id, email, created_at
            """),
            {"email": email, "password_hash": password_hash},
        ).fetchone()
        conn.execute(
            text("""
                INSERT INTO user_usage (user_id) VALUES (:user_id)
                ON CONFLICT (user_id) DO NOTHING
            """),
            {"user_id": result[0]},
        )
        conn.commit()
        return {"id": result[0], "email": result[1], "created_at": result[2]}
 
 
def get_user_by_email(email: str) -> dict:
    with get_engine().connect() as conn:
        result = conn.execute(
            text("SELECT id, email, password_hash, created_at FROM users WHERE email = :email"),
            {"email": email},
        ).fetchone()
        if result:
            return {"id": result[0], "email": result[1], "password_hash": result[2], "created_at": result[3]}
        return None
 
 
def get_user_by_id(user_id: int) -> dict:
    with get_engine().connect() as conn:
        result = conn.execute(
            text("SELECT id, email, created_at FROM users WHERE id = :id"),
            {"id": user_id},
        ).fetchone()
        if result:
            return {"id": result[0], "email": result[1], "created_at": result[2]}
        return None
 
 
def increment_user_usage(user_id: int, kind: str) -> None:
    """kind is 'ingests' or 'queries'. Upserts so this is safe even if a
    user row predates the user_usage table (shouldn't happen post-init_db,
    but cheap insurance)."""
    column = "ingests_count" if kind == "ingests" else "queries_count"
    with get_engine().connect() as conn:
        conn.execute(
            text(f"""
                INSERT INTO user_usage (user_id, {column}, updated_at)
                VALUES (:user_id, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE
                SET {column} = user_usage.{column} + 1, updated_at = CURRENT_TIMESTAMP
            """),
            {"user_id": user_id},
        )
        conn.commit()
 
 
# --- Chunks -------------------------------------------------------------
 
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
    """No user_id filter here by design: doc_id is an unguessable UUID,
    and every caller (RagService.ask, via the /query route) is required
    to confirm the caller owns doc_id via get_document(doc_id, user_id)
    BEFORE calling this. Ownership is enforced once, at that lookup, not
    duplicated into every downstream chunk query."""
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
 
 
# --- Documents (user_id-scoped) -----------------------------------------
 
def save_document(doc_id: str, filename: str, content_hash: str, summary: str, facts: str,
                   chunk_count: int = 0, is_partial: bool = False, user_id: int | None = None,
                   needs_summary_retry: bool = False):
    with get_engine().connect() as conn:
        conn.execute(
            text("""
                INSERT INTO documents (doc_id, filename, content_hash, summary, facts, chunk_count, is_partial, user_id, needs_summary_retry)
                VALUES (:doc_id, :filename, :content_hash, :summary, :facts, :chunk_count, :is_partial, :user_id, :needs_summary_retry)
                ON CONFLICT (doc_id) DO UPDATE
                SET summary = EXCLUDED.summary,
                    facts = EXCLUDED.facts,
                    chunk_count = EXCLUDED.chunk_count,
                    is_partial = EXCLUDED.is_partial,
                    needs_summary_retry = EXCLUDED.needs_summary_retry
            """),
            {"doc_id": doc_id, "filename": filename, "content_hash": content_hash,
             "summary": summary, "facts": facts, "chunk_count": chunk_count,
             "is_partial": is_partial, "user_id": user_id, "needs_summary_retry": needs_summary_retry}
        )
        conn.commit()
 
 
def get_document(doc_id: str, user_id: int) -> dict:
    """user_id is required, not optional: every caller must know who is
    asking. Passing None here won't magically return unowned/pre-auth
    rows -- SQL's `user_id = NULL` is NULL, not true, so it matches
    nothing, same as for any other mismatched id. See MIGRATION.md."""
    with get_engine().connect() as conn:
        result = conn.execute(
            text("""
                SELECT doc_id, filename, summary, facts, chunk_count, is_partial, content_hash, needs_summary_retry
                FROM documents WHERE doc_id = :doc_id AND user_id = :user_id
            """),
            {"doc_id": doc_id, "user_id": user_id}
        ).fetchone()
        if result:
            return {"doc_id": result[0], "filename": result[1], "summary": result[2],
                    "facts": result[3], "chunk_count": result[4], "is_partial": result[5],
                    "content_hash": result[6], "needs_summary_retry": result[7]}
        return None
 
 
def get_document_by_hash(content_hash: str, user_id: int) -> dict:
    """
    Look up the most recent document with this exact content hash,
    scoped to one user -- reuse/dedup is per-account, not global, so
    uploading the same PDF as two different users creates two rows (each
    user gets their own doc_id to own/delete/query independently) even
    though the underlying chunks and embeddings are identical content.
    """
    with get_engine().connect() as conn:
        result = conn.execute(
            text("""
                SELECT doc_id, filename, summary, facts, chunk_count, is_partial, needs_summary_retry
                FROM documents
                WHERE content_hash = :content_hash AND user_id = :user_id
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"content_hash": content_hash, "user_id": user_id}
        ).fetchone()
        if result:
            return {"doc_id": result[0], "filename": result[1], "summary": result[2],
                    "facts": result[3], "chunk_count": result[4], "partial": result[5],
                    "needs_summary_retry": result[6]}
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
 

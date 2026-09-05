"""
Shared pytest fixtures.

DB strategy: tests run against a REAL pgvector Postgres instance (not mocked),
pointed at by TEST_DATABASE_URL (falls back to DATABASE_URL, then a local
docker-compose default). This catches things a mocked DB layer can't:
pgvector dimension limits, the halfvec cast, index creation, real SQL syntax
errors. See docker-compose.yml `db` service for the local instance, or the
`postgres-pgvector` service in ci.yml for CI.

LLM strategy: Gemini calls ARE mocked (via the `chat_engine` fixture below).
We don't want tests burning API quota, needing real credentials, or being
flaky because of network/quota errors — and we already unit-test the quota
logic itself against synthetic errors in test_quota_classification.py.
"""

import os
import uuid

import pytest

# Must be set before any `app.*` module is imported, since app.database
# reads DATABASE_URL lazily via os.getenv() inside get_engine() -- but
# app.chat_engine.get_client() also reads GEMINI_API_KEY at first use, so
# set both up front to be safe regardless of import order.
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/documind_test"),
)
os.environ.setdefault("GEMINI_API_KEY", "test-key-not-a-real-key")

from app import database  # noqa: E402  (import after env setup, see above)
from app.chat_engine import ChatEngine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_test_database():
    """Create tables/indexes once per test session against the real DB."""
    database.init_db()
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate data between every test so tests don't leak state into
    each other, without paying the cost of recreating tables/indexes."""
    yield
    with database.get_engine().connect() as conn:
        from sqlalchemy import text
        conn.execute(text("TRUNCATE TABLE document_chunks, documents"))
        conn.commit()


@pytest.fixture
def doc_id() -> str:
    """A fresh doc_id per test, since document_name/doc_id is how rows
    are scoped in both tables."""
    return str(uuid.uuid4())


@pytest.fixture
def fake_embedding() -> list:
    """A syntactically valid 3072-dim embedding (matches gemini-embedding-001)
    without calling the real API. Values don't need to be meaningful for
    most tests -- only test_database.py's ordering test cares about the
    actual numbers."""
    return [0.001 * i for i in range(3072)]


@pytest.fixture
def chat_engine() -> ChatEngine:
    """A real ChatEngine instance (constructing genai.Client with the dummy
    key above is safe -- it doesn't make a network call until a method is
    actually invoked). Tests exercise real chunking/orchestration/DB logic;
    override _embed/_embed_batch/_generate per-test with monkeypatch.setattr
    to avoid hitting the network and to simulate specific responses or a
    QuotaError.
    """
    return ChatEngine()

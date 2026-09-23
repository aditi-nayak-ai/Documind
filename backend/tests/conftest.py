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
from urllib.parse import urlparse
 
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
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-not-for-production")
 
 
def _refuse_to_run_against_a_database_that_might_be_real() -> None:
    """`_clean_tables` below runs TRUNCATE ... CASCADE after every single
    test. `os.environ.setdefault` above only sets DATABASE_URL if it isn't
    already set -- so if a developer's shell already has DATABASE_URL
    exported (e.g. from a real Neon/production .env they sourced for some
    other reason), TEST_DATABASE_URL is silently ignored and the ENTIRE
    test suite truncates their real database, test by test, with no
    warning. This is not a hypothetical: it is exactly the kind of mistake
    that is invisible until the data is already gone.
 
    This is a heuristic, not a guarantee -- there is no way to know for
    certain that a URL is "safe" to truncate. It blocks the common
    accident (a URL that is neither localhost nor named like a test
    database) and can be overridden with DOCUMIND_ALLOW_ANY_TEST_DB=1 for
    a deliberately different setup (e.g. a CI database that isn't named
    "test" but is still definitely disposable).
    """
    if os.environ.get("DOCUMIND_ALLOW_ANY_TEST_DB") == "1":
        return
    url = os.environ["DATABASE_URL"]
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    db_name = (parsed.path or "").lstrip("/").lower()
    looks_local = host in ("localhost", "127.0.0.1", "::1") or host.endswith(".docker.internal")
    looks_like_a_test_db = "test" in db_name
    if not (looks_local or looks_like_a_test_db):
        raise RuntimeError(
            "\n\nRefusing to run the test suite: DATABASE_URL does not look like a "
            "test database (host is not localhost, and the database name doesn't "
            "contain 'test').\n"
            f"  DATABASE_URL host: {host or '(none)'}\n"
            f"  DATABASE_URL database name: {db_name or '(none)'}\n\n"
            "Every test run TRUNCATEs all data in this database after each test. "
            "If this really is a disposable test database, either rename it to "
            "include 'test', or set DOCUMIND_ALLOW_ANY_TEST_DB=1 to bypass this "
            "check. If you're not sure, STOP: check what DATABASE_URL is already "
            "set to in your shell -- it may be pointing at a real database, and "
            "TEST_DATABASE_URL is only used as a fallback via os.environ."
            "setdefault(), so it is silently ignored when DATABASE_URL is already "
            "set.\n"
        )
 
 
_refuse_to_run_against_a_database_that_might_be_real()
 
from app import database
from app.chat_engine import ChatEngine
 
 
@pytest.fixture(scope="session", autouse=True)
def _init_test_database():
    """Create tables/indexes once per test session against the real DB."""
    database.init_db()
    yield
 
 
@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate data between every test so tests don't leak state into
    each other, without paying the cost of recreating tables/indexes.
    Order matters: document_chunks/documents/user_usage all reference
    or relate to users, so users must be truncated last (or all together
    in one statement, as below, which Postgres handles regardless of
    declaration order within a single TRUNCATE)."""
    yield
    with database.get_engine().connect() as conn:
        from sqlalchemy import text
        conn.execute(text("TRUNCATE TABLE document_chunks, documents, user_usage, users CASCADE"))
        conn.commit()
 
 
@pytest.fixture
def test_user() -> dict:
    """A user row created directly via the DB layer (not through the
    /auth/register HTTP route) -- useful for tests that only need a valid
    user_id and don't care about exercising the registration endpoint
    itself."""
    from app.auth import hash_password
    return database.create_user("fixture-user@example.com", hash_password("a-fixture-password"))
 
 
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

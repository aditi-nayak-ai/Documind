from pydantic_settings import BaseSettings, SettingsConfigDict
 
 
class Settings(BaseSettings):
    """Centralized, typed configuration.
 
    Replaces scattered os.getenv() calls across api.py, chat_engine.py, and
    database.py with one validated source of truth, read once at import
    time instead of ad hoc at first use. Field names map to env vars
    case-insensitively (database_url -> DATABASE_URL), matching the names
    already used in .env / Render / docker-compose -- no env var renaming
    needed anywhere else in the stack.
    """
 
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
 
    database_url: str = ""
    gemini_api_key: str = ""
    allowed_origins: str = "http://localhost:5173"
 
    # Auth. jwt_secret_key has no default on purpose -- see app/auth.py,
    # which refuses to sign/verify tokens with an empty key rather than
    # silently using a guessable default. jwt_expire_minutes defaults to
    # 7 days: there's no refresh-token flow (see AuthContext.jsx's logout
    # comment), so this is a straight re-login cadence, not a security
    # backstop -- shorten it if that tradeoff doesn't suit your use case.
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7
 
    # Coarse per-user cap on total ingests, independent of any IP-based
    # rate limiting (see app/auth.py's note on why IP alone isn't
    # trustworthy on Render). This is a lifetime total, not a rolling
    # daily window -- user_usage.updated_at is overwritten on every
    # increment, so a true daily reset would need a separate counter
    # reset on a schedule. A lifetime cap still bounds the worst case: no
    # single account can keep draining the shared Gemini quota forever.
    max_ingests_per_user: int = 200
 
 
settings = Settings()
 
 
def validate_settings_or_raise() -> None:
    """Called once at process startup (see api.py's lifespan). Fails
    loudly and immediately if the deployment is misconfigured, instead of
    starting successfully and only failing -- with a confusing 500 -- at
    the first login or token check. A 1-byte JWT_SECRET_KEY used to pass
    silently; jwt.encode would sign with it, and nothing caught how weak
    it was until someone thought to check.
    """
    if not settings.jwt_secret_key:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. Generate one with: "
            'python -c "import secrets; print(secrets.token_hex(32))" '
            "and set it as an environment variable before starting the server."
        )
    if len(settings.jwt_secret_key.encode("utf-8")) < 32:
        raise RuntimeError(
            "JWT_SECRET_KEY is too short (must be at least 32 bytes for HS256). "
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )

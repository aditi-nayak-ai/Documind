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
 
 
settings = Settings()
 

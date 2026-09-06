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


settings = Settings()

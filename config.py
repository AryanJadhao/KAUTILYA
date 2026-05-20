from pydantic_settings import BaseSettings
from functools import lru_cache


# ─────────────────────────────────────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
class Settings(BaseSettings):
    """
    All environment variables loaded from .env automatically.
    Access anywhere via: from config import settings
    """

    # ── API Keys ──────────────────────────────────────────────────────────────
    OPENAI_API_KEY:  str = ""
    TAVILY_API_KEY:  str = ""
    QDRANT_API_KEY:  str = ""

    # ── Qdrant ────────────────────────────────────────────────────────────────
    QDRANT_URL:       str = ""
    COLLECTION_NAME:  str = "web_snapshots"
    VECTOR_SIZE:      int = 1536            # text-embedding-3-small dimension

    # ── LLM ───────────────────────────────────────────────────────────────────
    LLM_MODEL:        str = "gpt-4o-mini"
    LLM_TEMPERATURE:  float = 0.0

    # ── Postgres (LangGraph checkpointer for HITL) ────────────────────────────
    POSTGRES_URL:     str = ""              # e.g. postgresql://user:pass@host:5432/db

    # ── Slack ─────────────────────────────────────────────────────────────────────
    SLACK_WEBHOOK_URL: str = ""
    
    # ── App ───────────────────────────────────────────────────────────────────
    APP_ENV:          str = "development"   # "development" | "production"
    LOG_LEVEL:        str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# ─────────────────────────────────────────────────────────────────────────────
# SINGLETON — import this everywhere
# ─────────────────────────────────────────────────────────────────────────────
@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
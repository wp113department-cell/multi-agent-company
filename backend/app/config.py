from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = Field(..., description="PostgreSQL DSN, e.g. postgresql+asyncpg://user:pass@host/db")

    # Anthropic
    anthropic_api_key: str = Field(..., description="Anthropic API key")

    # Model tiers
    model_planner: str = Field(default="claude-haiku-4-5-20251001", description="Model for PM/Architect/Decomposer")
    model_coder: str = Field(default="claude-sonnet-5", description="Model for Coder/QA/Review agents")
    model_router: str = Field(default="claude-haiku-4-5-20251001", description="Model for triage/summary/heartbeat")

    # Voyage AI (optional — falls back to keyword search if unset)
    voyage_api_key: str = Field(default="", description="Voyage AI key for semantic embeddings")
    voyage_model: str = Field(default="voyage-code-2", description="Voyage embedding model")
    voyage_dimensions: int = Field(default=1536, description="Embedding vector dimensions")

    # Repo
    target_repo_path: str = Field(default=".", description="Path to the codebase the agent operates on")
    worktrees_dir: str = Field(default="/tmp/gridiron-worktrees", description="Where git worktrees are created")

    # Pipeline behaviour
    pipeline_mode: str = Field(default="full", description="simple=skip planning, full=PM→Architect→Decomposer")
    max_retries: int = Field(default=3, description="Max self-correction retries before blocked")
    context_token_budget: int = Field(default=8000, description="Max tokens for context assembly")

    # Server
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    debug: bool = Field(default=False)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings

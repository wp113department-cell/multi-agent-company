from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Any


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = Field(..., description="PostgreSQL DSN, e.g. postgresql+asyncpg://user:pass@host/db")

    # Anthropic (required unless USE_GROQ=true)
    anthropic_api_key: str = Field(default="", description="Anthropic API key (required when USE_GROQ=false)")

    # Model tiers
    model_planner: str = Field(default="claude-haiku-4-5-20251001", description="Model for PM/Architect/Decomposer")
    model_coder: str = Field(default="claude-sonnet-5", description="Model for Coder/QA/Review agents")
    model_router: str = Field(default="claude-haiku-4-5-20251001", description="Model for triage/summary/heartbeat")

    # Voyage AI (optional — falls back to keyword search if unset)
    voyage_api_key: str = Field(default="", description="Voyage AI key for semantic embeddings")
    voyage_model: str = Field(default="voyage-code-2", description="Voyage embedding model")
    voyage_dimensions: int = Field(default=1536, description="Embedding vector dimensions")

    # Repo
    target_repo_path: str = Field(default=".", description="Path to the codebase the agent operates on (fallback when no repo is activated via UI)")
    worktrees_dir: str = Field(default="/tmp/gridiron-worktrees", description="Where git worktrees are created")
    repos_dir: str = Field(default="/tmp/gridiron-repos", description="Where cloned GitHub repos are stored")

    # Pipeline behaviour
    pipeline_mode: str = Field(default="full", description="simple=skip planning, full=PM→Architect→Decomposer")
    max_retries: int = Field(default=3, description="Max self-correction retries before blocked")
    context_token_budget: int = Field(default=8000, description="Max tokens for context assembly")

    # Phase 5 — Cost Controller
    cost_approval_threshold: float = Field(default=1.0, description="Epic cost estimate (USD) above which human approval is required before agents start")
    cost_per_input_token: float = Field(default=0.0000008, description="Cost per input token (USD) — Haiku pricing")
    cost_per_output_token: float = Field(default=0.000004, description="Cost per output token (USD) — Haiku pricing")
    cost_tokens_per_subtask: int = Field(default=4000, description="Baseline input token estimate per subtask for cost pre-estimation")
    cost_output_ratio: float = Field(default=0.3, description="Estimated output/input token ratio for cost pre-estimation")

    # Phase 5 — Manager Agent
    manager_max_subtask_retries: int = Field(default=2, description="Max per-subtask retries before epic is halted")
    manager_max_epic_failures: int = Field(default=2, description="Number of subtask failures that trigger epic.halted")

    # Phase 5 — DevOps Agent bash allowlist (comma-separated command prefixes)
    devops_bash_allowlist: str = Field(
        default="git status,git log,git diff,df -h,du -sh,ls,pwd,cat,echo,free -h,uptime",
        description="Comma-separated read-only bash command prefixes allowed for DevOps Agent",
    )

    # Phase 5 — RBAC
    rbac_enabled: bool = Field(default=True, description="Enforce viewer/approver RBAC on approve/reject endpoints")

    # Phase 6 — Research Agent
    research_enabled: bool = Field(default=True, description="Enable Research Agent as an optional first step before planning")

    # Phase 6 — Engineering Memory (pgvector)
    memory_enabled: bool = Field(default=True, description="Enable pgvector engineering memory (requires pgvector extension)")
    memory_top_k: int = Field(default=3, description="Number of similar past tasks to inject into Architect context")

    # Phase 7 — Concurrency
    max_concurrent_epics: int = Field(default=10, description="Max number of epics running simultaneously")
    max_concurrent_agent_runs: int = Field(default=20, description="Max total agent runs running at once across all epics")
    max_concurrent_subtasks_per_epic: int = Field(default=5, description="Max subtasks running simultaneously within a single epic")

    # Phase 7 — Executive Agent
    executive_max_epics_per_goal: int = Field(default=5, description="Max epics the Executive Agent may create from a single goal")

    # Phase 7 — Queue adapter backend (asyncio | bullmq)
    queue_backend: str = Field(default="asyncio", description="Task queue backend: asyncio (in-process) or bullmq (Redis)")

    # Groq (optional — enables Groq as LLM backend when ANTHROPIC_API_KEY is unavailable)
    groq_api_key: str = Field(default="", description="Groq API key (gsk_...). When set and USE_GROQ=true, all agent calls use Groq instead of Anthropic.")
    use_groq: bool = Field(default=False, description="Route all agent calls to Groq instead of Anthropic. Useful when ANTHROPIC_API_KEY is unavailable.")
    # Groq model tiers — map to Groq model IDs
    groq_model_planner: str = Field(default="qwen/qwen3-32b", description="Groq model for PM/Architect/Decomposer (Haiku equivalent)")
    groq_model_coder: str = Field(default="qwen/qwen3-32b", description="Groq model for Coder/QA/Review agents (Sonnet equivalent)")
    groq_model_router: str = Field(default="llama-3.1-8b-instant", description="Groq model for triage/summary/heartbeat (Haiku equivalent)")

    @model_validator(mode="after")
    def _require_llm_key(self) -> "Settings":
        # anthropic_api_key may be empty at startup if user stores it via UI (settings page).
        # The key is loaded from DB at runtime by base.py:get_effective_api_key().
        # We only raise if BOTH env var and db-path are clearly unavailable.
        if self.use_groq and not self.groq_api_key:
            raise ValueError(
                "GROQ_API_KEY is required when USE_GROQ=true."
            )
        return self

    # Server
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO", description="Logging level: DEBUG, INFO, WARNING, ERROR")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings

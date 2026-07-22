from functools import cached_property

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Database
    database_url: str = Field(
        ..., description="PostgreSQL DSN, e.g. postgresql+asyncpg://user:pass@host/db"
    )

    # Anthropic (required unless USE_GROQ=true)
    anthropic_api_key: str = Field(
        default="", description="Anthropic API key (required when USE_GROQ=false)"
    )

    # OpenAI (optional — used by agents/tools that need GPT models)
    openai_api_key: str = Field(
        default="", description="OpenAI API key. Can also be set via UI Settings page."
    )

    # Model tiers
    model_planner: str = Field(
        default="claude-haiku-4-5-20251001",
        description="Model for PM/Architect/Decomposer",
    )
    model_coder: str = Field(
        default="claude-sonnet-5", description="Model for Coder/QA/Review agents"
    )
    model_router: str = Field(
        default="claude-haiku-4-5-20251001",
        description="Model for triage/summary/heartbeat",
    )

    # Voyage AI (optional — falls back to keyword search if unset)
    voyage_api_key: str = Field(
        default="", description="Voyage AI key for semantic embeddings"
    )
    voyage_model: str = Field(
        default="voyage-code-2", description="Voyage embedding model"
    )
    voyage_dimensions: int = Field(
        default=1536, description="Embedding vector dimensions"
    )

    # Repo
    target_repo_path: str = Field(
        default=".",
        description="Path to the codebase the agent operates on (fallback when no repo is activated via UI)",
    )
    worktrees_dir: str = Field(
        default="/tmp/gridiron-worktrees", description="Where git worktrees are created"
    )
    repos_dir: str = Field(
        default="/tmp/gridiron-repos",
        description="Where cloned GitHub repos are stored",
    )

    # Pipeline behaviour
    pipeline_mode: str = Field(
        default="full", description="simple=skip planning, full=PM→Architect→Decomposer"
    )
    max_retries: int = Field(
        default=3, description="Max self-correction retries before blocked"
    )
    context_token_budget: int = Field(
        default=8000, description="Max tokens for context assembly"
    )

    # Phase 5 — Cost Controller
    cost_approval_threshold: float = Field(
        default=1.0,
        description="Epic cost estimate (USD) above which human approval is required before agents start",
    )
    cost_per_input_token: float = Field(
        default=0.0000008, description="Cost per input token (USD) — Haiku pricing"
    )
    cost_per_output_token: float = Field(
        default=0.000004, description="Cost per output token (USD) — Haiku pricing"
    )
    cost_tokens_per_subtask: int = Field(
        default=4000,
        description="Baseline input token estimate per subtask for cost pre-estimation",
    )
    cost_output_ratio: float = Field(
        default=0.3,
        description="Estimated output/input token ratio for cost pre-estimation",
    )

    # Phase 5 — Manager Agent
    manager_max_subtask_retries: int = Field(
        default=2, description="Max per-subtask retries before epic is halted"
    )
    manager_max_epic_failures: int = Field(
        default=2, description="Number of subtask failures that trigger epic.halted"
    )

    # Phase 5 — DevOps Agent bash allowlist (comma-separated command prefixes)
    devops_bash_allowlist: str = Field(
        default="git status,git log,git diff,df -h,du -sh,ls,pwd,cat,echo,free -h,uptime",
        description="Comma-separated read-only bash command prefixes allowed for DevOps Agent",
    )

    # Phase 5 — RBAC
    rbac_enabled: bool = Field(
        default=True,
        description="Enforce viewer/approver RBAC on approve/reject endpoints",
    )

    # Phase 6 — Research Agent
    research_enabled: bool = Field(
        default=True,
        description="Enable Research Agent as an optional first step before planning",
    )

    # Phase 6 — Engineering Memory (pgvector)
    memory_enabled: bool = Field(
        default=True,
        description="Enable pgvector engineering memory (requires pgvector extension)",
    )
    memory_top_k: int = Field(
        default=3,
        description="Number of similar past tasks to inject into Architect context",
    )

    # Phase 7 — Concurrency
    max_concurrent_epics: int = Field(
        default=10, description="Max number of epics running simultaneously"
    )
    max_concurrent_agent_runs: int = Field(
        default=20, description="Max total agent runs running at once across all epics"
    )
    max_concurrent_subtasks_per_epic: int = Field(
        default=5,
        description="Max subtasks running simultaneously within a single epic",
    )

    # Phase 7 — Executive Agent
    executive_max_epics_per_goal: int = Field(
        default=5,
        description="Max epics the Executive Agent may create from a single goal",
    )

    # Phase 7 — Queue adapter backend (asyncio | rq)
    queue_backend: str = Field(
        default="asyncio",
        description="Task queue backend: asyncio (in-process) or rq (Redis Queue)",
    )

    # Redis — used by RQ queue adapter and Redis Streams event bus
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for RQ queue and Redis Streams event bus.",
    )
    redis_streams_enabled: bool = Field(
        default=False,
        description="Publish events to Redis Streams in addition to the in-process bus.",
    )
    redis_consumer_group: str = Field(
        default="gridiron-consumers", description="Redis Streams consumer group name."
    )

    # S3 artifact storage (optional — falls back to DB when unset)
    artifact_backend: str = Field(
        default="db",
        description="Artifact storage backend: 'db' (PostgreSQL) or 's3' (AWS S3).",
    )
    s3_bucket: str = Field(
        default="",
        description="S3 bucket name for artifact storage. Required when artifact_backend=s3.",
    )
    s3_region: str = Field(
        default="us-east-1", description="AWS region for the S3 bucket."
    )
    s3_key_prefix: str = Field(
        default="gridiron/artifacts/",
        description="Key prefix for all S3 artifact objects.",
    )
    aws_access_key_id: str = Field(
        default="",
        description="AWS access key ID. Leave empty to use IAM role / environment credentials.",
    )
    aws_secret_access_key: str = Field(
        default="",
        description="AWS secret access key. Leave empty to use IAM role / environment credentials.",
    )

    # Observability — Sentry (optional; leave empty to disable)
    sentry_dsn: str = Field(
        default="",
        description="Sentry DSN for error tracking. Leave empty to disable Sentry.",
    )
    sentry_environment: str = Field(
        default="production",
        description="Sentry environment tag (production | staging | development)",
    )
    sentry_traces_sample_rate: float = Field(
        default=0.1, description="Fraction of transactions sent to Sentry (0.0–1.0)"
    )

    # Alerting — webhook fired when a task transitions to 'blocked' or 'failed'
    alert_webhook_url: str = Field(
        default="",
        description="HTTP(S) webhook URL for task blocked/failed alerts. Leave empty to disable.",
    )
    alert_on_blocked: bool = Field(
        default=True,
        description="Send alert webhook when task status becomes 'blocked'",
    )

    # Log retention — automatic cleanup of old task logs
    log_retention_days: int = Field(
        default=90,
        description="Days to keep task_logs rows before automated cleanup. Set to 0 to disable cleanup.",
    )

    # Day 5A — Fleet Platform enhancements
    agent_models_path: str = Field(
        default="",
        description="Override path to agent_models.json. Defaults to backend/app/fleet/agent_models.json when empty.",
    )
    max_tokens_opus: int = Field(
        default=8192, description="Max tokens for Opus-tier agents."
    )
    thinking_budget_opus: int = Field(
        default=2048,
        description="Extended thinking budget for Opus-tier agents (tokens).",
    )
    allowed_workspace_parent: str = Field(
        default="/home",
        description="Workspace paths must start with this prefix (path traversal guard for Repo Console).",
    )
    git_allowed_hosts: str = Field(
        default="github.com,gitlab.com,bitbucket.org",
        description="Comma-separated list of git remote hostnames allowed for clone/push in Repo Console.",
    )

    # Day 14 — Git Push Workflow. No credential vault exists yet (Day 17
    # doesn't either) — this env var is the fallback; the DB-stored value via
    # POST /api/settings/github-token (SystemSetting, same pattern as the
    # Anthropic/OpenAI keys) takes precedence when set.
    github_token: str = Field(
        default="",
        description="GitHub personal access token for creating PRs via the REST API. Prefer setting via the UI (stored in the DB) over this env var.",
    )
    github_api_base_url: str = Field(
        default="https://api.github.com",
        description="GitHub REST API base URL — override for GitHub Enterprise.",
    )

    # Day 10 — Fleet OS Budget Manager (live enforcement, per-run + daily cumulative)
    max_tokens_per_agent_run: int = Field(
        default=100_000,
        description="Max total tokens (in+out) a single agent run may consume before BudgetExceeded is raised.",
    )
    cost_budget_daily_usd: float = Field(
        default=25.0,
        description="Max cumulative agent spend (USD) per calendar day before BudgetExceeded is raised.",
    )
    max_run_time_seconds: int = Field(
        default=600,
        description="Max wall-clock seconds a single agent run may take before BudgetExceeded is raised.",
    )
    max_memory_mb: int = Field(
        default=1024,
        description="Max resident memory (MB) a single agent run may use before BudgetExceeded is raised.",
    )

    # Day 10 — Fleet OS Benchmark Manager (composite score weights + regression threshold)
    benchmark_latency_target_ms: float = Field(
        default=30_000.0,
        description="p50 latency (ms) considered 'perfect' (score 1.0) when normalizing the latency objective; 0 at 2x this value.",
    )
    benchmark_weight_latency: float = Field(
        default=0.15,
        description="Composite benchmark_score weight for the normalized latency objective.",
    )
    benchmark_weight_tool_accuracy: float = Field(
        default=0.20, description="Composite benchmark_score weight for tool_accuracy."
    )
    benchmark_weight_verification_coverage: float = Field(
        default=0.20,
        description="Composite benchmark_score weight for verification_coverage.",
    )
    benchmark_weight_retry_success: float = Field(
        default=0.15, description="Composite benchmark_score weight for retry_success."
    )
    benchmark_weight_compile_success: float = Field(
        default=0.15,
        description="Composite benchmark_score weight for compile_success.",
    )
    benchmark_weight_hallucination: float = Field(
        default=0.15,
        description="Composite benchmark_score weight for (1 - hallucination_rate).",
    )
    benchmark_regression_threshold: float = Field(
        default=0.10,
        description="Fractional drop in benchmark_score vs. baseline that flags a regression (0.10 = 10%).",
    )
    benchmark_baseline_interval_hours: int = Field(
        default=24,
        description="Hours between automatic baseline-population sweeps for agents with real MetricsCollector runs but no stored baseline yet. 0 disables.",
    )

    # Day 11 — Fleet OS Versioned Memory (merge-on-conflict lesson lifecycle)
    memory_merge_similarity_threshold: float = Field(
        default=0.85,
        description="Cosine similarity above which a newly published lesson on the same topic triggers a merge instead of a plain new version.",
    )
    lesson_retention_days: int = Field(
        default=180,
        description="Days to keep SUPERSEDED/MERGED_INTO versioned_lessons rows before archive_expired() marks them ARCHIVED. 0 disables.",
    )

    # Groq (optional — enables Groq as LLM backend when ANTHROPIC_API_KEY is unavailable)
    groq_api_key: str = Field(
        default="",
        description="Groq API key (gsk_...). When set and USE_GROQ=true, all agent calls use Groq instead of Anthropic.",
    )
    use_groq: bool = Field(
        default=False,
        description="Route all agent calls to Groq instead of Anthropic. Useful when ANTHROPIC_API_KEY is unavailable.",
    )
    # Groq model tiers — map to Groq model IDs
    groq_model_planner: str = Field(
        default="qwen/qwen3-32b",
        description="Groq model for PM/Architect/Decomposer (Haiku equivalent)",
    )
    groq_model_coder: str = Field(
        default="qwen/qwen3-32b",
        description="Groq model for Coder/QA/Review agents (Sonnet equivalent)",
    )
    groq_model_router: str = Field(
        default="llama-3.1-8b-instant",
        description="Groq model for triage/summary/heartbeat (Haiku equivalent)",
    )

    @model_validator(mode="after")
    def _require_llm_key(self) -> "Settings":
        if self.use_groq and not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is required when USE_GROQ=true.")
        return self

    @model_validator(mode="after")
    def _require_jwt_secret_when_enabled(self) -> "Settings":
        if self.jwt_auth_enabled:
            if not self.jwt_secret_key:
                raise ValueError(
                    "JWT_SECRET_KEY is required when JWT_AUTH_ENABLED=true. "
                    "Generate one with: openssl rand -hex 32"
                )
            if len(self.jwt_secret_key) < 32:
                raise ValueError(
                    "JWT_SECRET_KEY must be at least 32 characters when JWT_AUTH_ENABLED=true "
                    "(short/guessable secrets allow token forgery). "
                    "Generate one with: openssl rand -hex 32"
                )
        return self

    @model_validator(mode="after")
    def _require_s3_bucket_when_s3_backend(self) -> "Settings":
        if self.artifact_backend == "s3" and not self.s3_bucket:
            raise ValueError("S3_BUCKET is required when ARTIFACT_BACKEND=s3.")
        return self

    @model_validator(mode="after")
    def _validate_enum_fields(self) -> "Settings":
        if self.pipeline_mode not in ("simple", "full"):
            raise ValueError(
                f"PIPELINE_MODE must be 'simple' or 'full', got {self.pipeline_mode!r}"
            )
        if self.artifact_backend not in ("db", "s3"):
            raise ValueError(
                f"ARTIFACT_BACKEND must be 'db' or 's3', got {self.artifact_backend!r}"
            )
        if self.queue_backend not in ("asyncio", "rq"):
            raise ValueError(
                f"QUEUE_BACKEND must be 'asyncio' or 'rq', got {self.queue_backend!r}"
            )
        return self

    @cached_property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @cached_property
    def devops_bash_allowlist_tuple(self) -> tuple[str, ...]:
        return tuple(
            p.strip() for p in self.devops_bash_allowlist.split(",") if p.strip()
        )

    @property
    def is_llm_key_configured(self) -> bool:
        if self.use_groq:
            return bool(self.groq_api_key)
        return bool(self.anthropic_api_key)

    # Server
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    debug: bool = Field(default=False)
    log_level: str = Field(
        default="INFO", description="Logging level: DEBUG, INFO, WARNING, ERROR"
    )
    cors_origins: str = Field(
        default="http://localhost:3000",
        description="Comma-separated list of allowed CORS origins. E.g. https://app.gridiron.example.com,http://localhost:3000",
    )
    event_bus_max_retries: int = Field(
        default=3,
        description="Max handler retry attempts in the in-process event bus before writing to failed_events.",
    )
    groq_max_retries: int = Field(
        default=5, description="Max Groq API call retries on transient errors."
    )

    # Rate limiting (slowapi)
    rate_limit_enabled: bool = Field(
        default=True, description="Enable API rate limiting via slowapi."
    )
    rate_limit_default: str = Field(
        default="200/minute",
        description="Default rate limit for all endpoints (slowapi format: N/second|minute|hour).",
    )
    rate_limit_tasks: str = Field(
        default="60/minute",
        description="Rate limit for task creation and pipeline trigger endpoints.",
    )
    rate_limit_agents: str = Field(
        default="30/minute",
        description="Rate limit for specialized agent dispatch endpoints.",
    )

    # JWT auth
    jwt_secret_key: str = Field(
        default="",
        description="Secret key for signing JWTs. REQUIRED in production. Generate with: openssl rand -hex 32",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT signing algorithm.")
    jwt_access_token_expire_minutes: int = Field(
        default=1440,
        description="JWT access token lifetime in minutes (default: 24 hours).",
    )
    jwt_auth_enabled: bool = Field(
        default=False,
        description="Enable JWT authentication. When false, X-User-Role header is still accepted (backward compat).",
    )
    default_admin_password: str = Field(
        default="gridiron123",
        description="Password auto-seeded for the 'admin' user on first startup. Change in production.",
    )

    # Day 9 — Fleet Enhancement Dashboard (5 self-improvement agents target the
    # Gridiron platform's own codebase, not a user-connected repo)
    fleet_self_repo_path: str = Field(
        default=".",
        description="Root of the Gridiron project itself — where the 5 fleet-enhancement agents read/write (backend/ + apps/web/). Defaults to the process cwd (repo root when run normally).",
    )
    fleet_scan_interval_hours: float = Field(
        default=4.0,
        description="Hours between automatic SCAN-phase runs of the 5 fleet-enhancement agents (background loop). Set to 0 to disable the background loop entirely.",
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings


def reset_settings_cache() -> None:
    """Test-only helper — clears the cached singleton so tests can re-instantiate
    Settings with different env vars without restarting the process."""
    global _settings
    _settings = None

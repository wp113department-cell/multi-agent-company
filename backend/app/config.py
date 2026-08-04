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
    bg_process_registry_path: str = Field(
        default="/tmp/gridiron-bg-processes.json",
        description="Gap-closure Day 23 (Stage 1.3, answers.md) — durable "
        "registry of PIDs started by the run_background tool, so a crashed "
        "or restarted server can find and terminate orphans left running "
        "with nothing else able to stop them (app/fleet/bg_process_registry.py).",
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
    llm_call_timeout_seconds: float = Field(
        default=300.0,
        description="Timeout (seconds) applied to every Anthropic SDK client "
        "construction. Without this, LLM calls rely entirely on the SDK's own "
        "undocumented default, which could hang a worker thread indefinitely.",
    )
    llm_circuit_breaker_failure_threshold: int = Field(
        default=5,
        description="Gap-closure Day 22 (Stage 1.3, answers.md) — consecutive "
        "LLM call failures (per provider: Anthropic, Groq) before the shared "
        "circuit breaker opens and refuses further calls without hitting the "
        "API, so a real outage doesn't get hammered by every one of the "
        "~74-76 agents retrying independently.",
    )
    llm_circuit_breaker_cooldown_seconds: float = Field(
        default=30.0,
        description="Gap-closure Day 22 — how long the circuit breaker stays "
        "open before allowing one trial call through (half-open) to test "
        "whether the provider has recovered.",
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

    # Gap-closure Day 35 (Stage 2, answers.md Q31) — Resource Awareness pre-flight.
    # Mirrors cost_controller.py's own shape: compute a real number, compare to a
    # config threshold, explain + recommend when insufficient instead of a silent
    # hard stop.
    resource_min_ram_gb: float = Field(
        default=1.0,
        description="Minimum available RAM (GB) required before an epic/expensive operation may start",
    )
    resource_min_disk_gb: float = Field(
        default=2.0,
        description="Minimum free disk space (GB) on the working directory's filesystem required before an epic/expensive operation may start",
    )
    resource_min_cpu_count: int = Field(
        default=1,
        description="Minimum logical CPU count required before an epic/expensive operation may start",
    )
    resource_required_python_version: str = Field(
        default="3.11",
        description="Minimum Python version ('major.minor') this backend requires — matches the project's documented Python 3.11+ requirement",
    )
    resource_require_docker: bool = Field(
        default=False,
        description="If true, the resource pre-flight check fails when Docker is unavailable. Only operations that actually need Docker (sandboxed bash execution) should opt into this — most tasks don't need it.",
    )
    resource_require_gpu: bool = Field(
        default=False,
        description="If true, the resource pre-flight check fails when no GPU is detected. Off by default — the fleet's agents are LLM-API-driven, not local-GPU-bound.",
    )
    resource_check_subprocess_timeout_seconds: float = Field(
        default=5.0,
        description="Timeout for each external probe subprocess (docker info, node --version, nvidia-smi, systemd-detect-virt) the resource pre-flight check shells out to",
    )

    # Gap-closure Days 37-38 (Stage 2, answers.md Q32) — Project/Repo Size Awareness.
    # Coefficients below are documented fallback defaults (no measured baseline exists
    # yet for indexing/embedding/test-execution duration) — used only when no real
    # historical `agent_runs` data is available, same fallback shape
    # cost_controller.py already uses for token estimation.
    size_disk_multiplier: float = Field(
        default=3.0,
        description="Projected working-copy disk footprint = raw repo size x this multiplier (clone + worktree + build artifacts)",
    )
    size_memory_mb_per_file: float = Field(
        default=2.0,
        description="Projected in-memory footprint (MB) per file during a full-repo scan/parse pass",
    )
    size_indexing_seconds_per_file: float = Field(
        default=0.05,
        description="Fallback estimated AST-indexing time (seconds) per file — no real indexing-duration history exists yet to calibrate against",
    )
    size_embedding_seconds_per_file: float = Field(
        default=0.15,
        description="Fallback estimated embedding time (seconds) per file (Voyage AI API round-trip) — no real embedding-duration history exists yet to calibrate against",
    )
    size_processing_seconds_fallback_per_subtask: float = Field(
        default=180.0,
        description="Fallback estimated coding time (seconds) per subtask, used only when no real 'coder' agent_runs history exists yet",
    )
    size_test_execution_seconds_fallback: float = Field(
        default=120.0,
        description="Fallback estimated test-execution time (seconds) — no QA-run timing data exists in agent_runs yet (the pipeline's QA node writes no AgentRun row; a separate, already-tracked gap), so this is coefficient-only, not historically calibrated",
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
    # Gap-closure (Audit 05 fix, SEC-05-014): the X-User-Role header self-
    # declaration fallback (used when jwt_auth_enabled=False) let ANY caller
    # become an "approver" by setting one header, with zero verification.
    # Defaulting this to False closes that by default; a deployment that
    # genuinely wants the old no-real-auth convenience must opt in
    # explicitly, the same way rbac_enabled=False is an explicit, visible
    # opt-out rather than a silent one. Does not affect rbac_enabled=False
    # (still a full, deliberate bypass) or a real JWT/X-User-Id+DB-role
    # login — only removes the self-declared-header shortcut.
    allow_legacy_role_header: bool = Field(
        default=False,
        description="Allow the X-User-Role header to grant a role with zero verification when JWT auth is disabled. Insecure — for local/dev convenience only. Defaults off.",
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

    # Gap-closure Day 41 (Stage 2, answers.md Q120 "Memory Prioritization") — composite
    # ranking weights blending similarity with recency/reuse/importance/verified, replacing
    # pure-cosine-distance ORDER BY. Weights need not sum to 1.0 (not enforced) — similarity
    # stays the dominant signal by default (0.6 of the total), the rest mildly re-rank
    # otherwise-close matches rather than overriding relevance outright.
    memory_score_weight_similarity: float = Field(
        default=0.6, description="Composite memory ranking: weight on cosine similarity"
    )
    memory_score_weight_recency: float = Field(
        default=0.15,
        description="Composite memory ranking: weight on exponential recency decay",
    )
    memory_score_weight_reuse: float = Field(
        default=0.1,
        description="Composite memory ranking: weight on reuse_count (capped, normalized)",
    )
    memory_score_weight_importance: float = Field(
        default=0.1,
        description="Composite memory ranking: weight on the importance column",
    )
    memory_score_weight_verified: float = Field(
        default=0.05,
        description="Composite memory ranking: weight on the verified boolean flag",
    )
    memory_recency_half_life_days: float = Field(
        default=30.0,
        description="Days for a memory's recency contribution to decay to half its initial value",
    )
    memory_reuse_cap: int = Field(
        default=20,
        description="reuse_count value at which the reuse contribution to composite ranking saturates at 1.0",
    )

    # Gap-closure Day 42 (Stage 2, answers.md Q120 "Automatic Memory Cleanup" / "Shared
    # Memory Synchronization" — "remove duplicated memories: PARTIAL, only VersionedLesson
    # dedups; raw memory_embeddings rows are never deduplicated"). Deliberately a much
    # stricter threshold than memory_merge_similarity_threshold (0.85) above: this guards
    # against a near-exact duplicate write, not a related-topic merge candidate — a lower
    # threshold here would incorrectly collapse genuinely distinct memories.
    memory_dedup_enabled: bool = Field(
        default=True,
        description="If true, embed_*() write functions check for a near-duplicate before inserting a new memory_embeddings row and strengthen the existing row instead",
    )
    memory_dedup_similarity_threshold: float = Field(
        default=0.97,
        description="Cosine similarity above which a new memory write is treated as a near-duplicate of an existing row (same category/repo scope) rather than a genuinely new memory",
    )

    # Gap-closure Day 43 (Stage 2, answers.md Q120 "Memory Analytics" — "a real, fairly
    # large gap": average retrieval time, memory growth, duplicate count, and unused
    # memories were all NO/PARTIAL with zero instrumentation).
    memory_analytics_growth_days: int = Field(
        default=30,
        description="Number of days of daily row-count history the memory growth-rate analytic reports",
    )
    memory_unused_threshold_days: int = Field(
        default=30,
        description="A memory row with reuse_count=0 older than this many days counts as 'unused' in memory analytics",
    )
    memory_dup_scan_max_rows: int = Field(
        default=5000,
        description="Skip the O(n^2) duplicate-pair analytics scan above this many total memory rows (it is a diagnostic, not a hot path, and must not become an unbounded cost as the table grows)",
    )
    memory_retrieval_time_window: int = Field(
        default=200,
        description="Number of most-recent retrieval-duration samples kept per query_* function for the average-retrieval-time analytic",
    )
    orchestration_timing_window: int = Field(
        default=200,
        description="Number of most-recent orchestration-duration samples kept per phase (e.g. run_manager) for the average-orchestration-time analytic. Gap-closure Day 54, answers.md Q8 'Orchestration speed'.",
    )

    # Gap-closure Day 44 (Stage 2, answers.md Q120 "Memory Aging" — "MemoryEmbedding has
    # only a boolean archived/archived_at — active vs. archived, no 'recent'/'historical'/
    # 'obsolete' gradation"). Buckets are multiples of the same
    # memory_recency_half_life_days Day 41's composite ranking already uses, so "what
    # counts as aged" is defined once, not two conflicting notions of age.
    memory_staleness_aging_half_lives: float = Field(
        default=1.0,
        description="A memory row older than this many recency half-lives is 'aging' (was 'recent')",
    )
    memory_staleness_stale_half_lives: float = Field(
        default=3.0,
        description="A memory row older than this many recency half-lives is 'stale' (was 'aging')",
    )
    memory_staleness_obsolete_half_lives: float = Field(
        default=6.0,
        description="A memory row older than this many recency half-lives is 'obsolete' (was 'stale')",
    )

    # Gap-closure Days 45-47 (Stage 2, "Context compression beyond Stage-1 basics" —
    # answers.md's flagged "understand 9,000+ line files: PARTIAL... no truncation/
    # chunking safeguard"). File folding (repo-first pattern, roo-code's
    # foldedFileContext.ts): a large file's read_file result is replaced with a
    # signature-only structural view instead of either an unbounded full read or a
    # dropped/empty result.
    file_fold_enabled: bool = Field(
        default=True,
        description="If true, read_file returns a folded (signature-only) view for files exceeding file_fold_line_threshold instead of their full content",
    )
    file_fold_line_threshold: int = Field(
        default=1000,
        description="A file with more lines than this is folded (or, if not tree-sitter-parseable, bounded-truncated) by read_file instead of returned in full",
    )
    file_fold_max_chars: int = Field(
        default=20000,
        description="Maximum character budget for a folded (signature-only) file view",
    )
    file_fold_fallback_max_chars: int = Field(
        default=20000,
        description="Maximum characters returned for a large, non-tree-sitter-parseable file (e.g. .md/.json/.txt) — a plain bounded truncation, since folding isn't possible for these",
    )

    # Gap-closure Day 46 (Stage 2, "Context compression beyond Stage-1 basics" —
    # answers.md Q120 "Session Memory": "Compresses repeated information: NO —
    # LessonStore.add() is pure append, no dedup check against existing lessons").
    # LessonStore has no embeddings (in-process, keyword-overlap only, per its own
    # docstring) so its dedup uses the same Jaccard token-overlap metric
    # retrieve() already established for relevance scoring, not a forced cosine-
    # similarity fit where no embedding exists.
    lesson_store_capacity: int = Field(
        default=1000,
        description="Max lessons LessonStore holds before the oldest is evicted (FIFO)",
    )
    lesson_dedup_enabled: bool = Field(
        default=True,
        description="If true, LessonStore.add() checks for a near-duplicate (same category, high token overlap) before appending and replaces it instead of accumulating repeats",
    )
    lesson_dedup_similarity_threshold: float = Field(
        default=0.8,
        description="Jaccard token-overlap ratio (same-category lessons only) above which a new lesson is treated as a near-duplicate of an existing one",
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
    # MASTER_AGENT_v2.md Phase 5.6 — bounded wait on slot acquisition, so a
    # slot that can never be freed (e.g. an epic holding a subtask slot
    # while waiting on another subtask that can't acquire one because the
    # epic's own concurrency cap is exhausted) fails loudly instead of
    # hanging a task in "running" state forever.
    slot_acquisition_timeout_seconds: float = Field(
        default=300.0,
        description="Max seconds to wait for an agent_run_slot()/subtask_slot() before raising SlotAcquisitionTimeout.",
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

    # Observability — OpenTelemetry tracing (MASTER_AGENT_v2.md Phase 6.1;
    # optional, leave endpoint empty to disable and use the in-process
    # no-op span exporter)
    otel_exporter_endpoint: str = Field(
        default="",
        description=(
            "OTLP HTTP endpoint (e.g. http://localhost:4318) to export agent-run "
            "spans to. Leave empty to run with an in-process no-op exporter."
        ),
    )
    otel_service_name: str = Field(
        default="multi-agent-company",
        description="service.name resource attribute reported on every OTEL span.",
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

    # MASTER_AGENT_v2.md Phase 5.6 — orphan agent_run recovery
    agent_run_orphan_threshold_seconds: int = Field(
        default=900,
        description=(
            "How long an agent_runs row can stay status='running' with no "
            "heartbeat update before the periodic sweep reconciles it to "
            "'failed' as orphaned. Set to 0 to disable the sweep."
        ),
    )
    # Stage 4 Cluster N (2026-08-04) — the heartbeat that feeds the sweep above
    # was a documented no-op in run_planner()/run_coder() and entirely absent
    # from run_manager()'s own pipeline, so last_heartbeat_at never left NULL
    # and the sweep above never matched a real row. Fixed by having
    # run_agent_graph() itself (the shared chokepoint ~76 agents already go
    # through) own a real AgentRun row's heartbeat, throttled by this
    # interval — far below agent_run_orphan_threshold_seconds's default so
    # detection stays responsive, but not so frequent it churns a fresh
    # throwaway DB connection on every single tool call.
    agent_run_heartbeat_min_interval_seconds: float = Field(
        default=30.0,
        description=(
            "Minimum real time between heartbeat DB writes for one agent "
            "run, even if many tool calls happen faster than this. Should "
            "stay well below agent_run_orphan_threshold_seconds."
        ),
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

    # Day 14 — Git Push Workflow. The credential vault (Day 17) now exists —
    # this env var remains the fallback; the DB-stored value via
    # POST /api/settings/github-token (SystemSetting, encrypted-at-rest when
    # CREDENTIAL_ENCRYPTION_KEY is set) takes precedence when set.
    github_token: str = Field(
        default="",
        description="GitHub personal access token for creating PRs via the REST API. Prefer setting via the UI (stored in the DB) over this env var.",
    )
    github_api_base_url: str = Field(
        default="https://api.github.com",
        description="GitHub REST API base URL — override for GitHub Enterprise.",
    )

    # Gap-closure Day 7 (answers.md Q21): the deployment profile. Defaults to
    # "development" so every existing local/test/docker-compose setup keeps
    # working with zero new required config — a production deploy must
    # explicitly opt in by setting DEPLOYMENT_ENV=production, at which point
    # _require_credential_encryption_in_production below starts enforcing.
    deployment_env: str = Field(
        default="development",
        description="Deployment profile: development | staging | production. production hard-requires CREDENTIAL_ENCRYPTION_KEY to be set.",
    )

    # Day 17 — Credential Vault. Optional in development (falls back to
    # plaintext with a startup warning when unset) but hard-required when
    # DEPLOYMENT_ENV=production (gap-closure Day 7, answers.md Q21) — never a
    # silently hardcoded fallback key. Generate with: python -c "from
    # cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    credential_encryption_key: str = Field(
        default="",
        description="Fernet key encrypting SystemSetting-backed credentials at rest. Required when DEPLOYMENT_ENV=production; falls back to plaintext (with a startup warning) when unset outside production.",
    )

    # Gap-closure Day 9 (answers.md Q21) — real per-command sandboxing for
    # the fully-generic, denylist-only bash tools (app/policy/sandbox.py),
    # replacing/augmenting the regex denylist the policy engine's own
    # docstring already admitted was incomplete containment. Enabled by
    # default (secure-by-default); the escape hatch exists for environments
    # that genuinely cannot run Docker — an explicit, operator-acknowledged
    # opt-out, never a silent fallback (run_sandboxed() itself fails closed,
    # raising rather than silently running unsandboxed, when Docker is
    # unreachable and this flag is still True).
    bash_sandbox_enabled: bool = Field(
        default=True,
        description="Run the fully-generic bash tools inside an isolated, ephemeral Docker container instead of directly on the host process. Explicit opt-out only — set False if this deployment truly cannot run Docker.",
    )
    bash_sandbox_image: str = Field(
        default="alpine:latest",
        description="Docker image used for sandboxed bash execution. The minimal default has basic coreutils only (no python/node/git) — deployments whose agents routinely need a language toolchain should build and point this at a custom image with it preinstalled.",
    )
    bash_sandbox_network: str = Field(
        default="bridge",
        description="Docker --network mode for sandboxed bash execution: 'bridge' (default, egress allowed — most real commands, e.g. package installs, need it) or 'none' (strictest, blocks all network egress/exfiltration for deployments that can accept losing network-dependent commands).",
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
    doc_agent_auto_trigger_interval_hours: float = Field(
        default=6,
        description="Hours between checks for whether target_repo_path's local `main` HEAD has moved since changelog_agent/release_notes_agent last ran, auto-dispatching each when it has. 0 disables. Gap-closure Day 52, answers.md Q41.",
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
    memory_embeddings_retention_days: int = Field(
        default=180,
        description="Days to keep memory_embeddings rows before the retention loop marks them archived=true. 0 disables. Separate from LOG_RETENTION_DAYS since engineering memory is longer-lived than raw execution logs.",
    )
    scratchpad_ttl_seconds: int = Field(
        default=14400,
        description="Max lifetime (seconds) of an epic_scratchpad entry before it's treated as expired, even if the epic never explicitly completes. Default 4 hours. Entries are also cleared outright the moment their epic completes — this TTL only matters for an epic that stalls or never finishes.",
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
    def _validate_credential_encryption_key(self) -> "Settings":
        # Optional (see credential_encryption_key's own docstring for why this
        # isn't hard-required) — but if SET, it must actually be a valid
        # Fernet key, not a typo silently accepted then failing at first use.
        if self.credential_encryption_key:
            from cryptography.fernet import Fernet

            try:
                Fernet(self.credential_encryption_key.encode())
            except Exception as exc:
                raise ValueError(
                    "CREDENTIAL_ENCRYPTION_KEY is set but is not a valid Fernet key. "
                    'Generate one with: python -c "from cryptography.fernet import '
                    f'Fernet; print(Fernet.generate_key().decode())"  ({exc})'
                ) from exc
        return self

    @model_validator(mode="after")
    def _require_credential_encryption_in_production(self) -> "Settings":
        # Gap-closure Day 7 (answers.md Q21): plaintext-fallback credential
        # storage is acceptable for local dev/test (the pre-Day-17 status
        # quo) but must never be the silent default for a real production
        # deployment — hard-fail at startup instead of only logging a
        # warning that's easy to miss in a deploy pipeline.
        if self.deployment_env == "production" and not self.credential_encryption_key:
            raise ValueError(
                "CREDENTIAL_ENCRYPTION_KEY must be set when DEPLOYMENT_ENV=production "
                "(plaintext credential storage is not permitted in production). "
                'Generate one with: python -c "from cryptography.fernet import '
                'Fernet; print(Fernet.generate_key().decode())"'
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

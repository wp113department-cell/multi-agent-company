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
    task_repo_id_cache_max_size: int = Field(
        default=2048,
        description="Stage 4 Cluster O (2026-08-05): max entries in the process-local "
        "task_id -> repo_id cache (app/db/repository.py::get_task_repo_id/_sync). "
        "DevTask.repo_id is immutable post-creation, so entries never need "
        "invalidation, only a size cap against unbounded growth.",
    )
    bg_process_registry_path: str = Field(
        default="/tmp/gridiron-bg-processes.json",
        description="Gap-closure Day 23 (Stage 1.3, answers.md) — durable "
        "registry of PIDs started by the run_background tool, so a crashed "
        "or restarted server can find and terminate orphans left running "
        "with nothing else able to stop them (app/fleet/bg_process_registry.py).",
    )
    bg_process_hang_threshold_seconds: int = Field(
        default=3600,
        description="AUDIT_Q_BATCH01 §17/§58 'Detect hanging processes' — a "
        "background process (run_background) still alive past this age is "
        "flagged 'possibly_hung' in list_background_processes and the "
        "liveness sweep's health event, distinct from the dead-process "
        "reap sweep. Advisory only — never auto-killed, since many "
        "legitimate background commands (dev servers, watchers) run "
        "indefinitely by design.",
    )
    rename_symbol_max_files: int = Field(
        default=200,
        description="AUDIT_Q_BATCH01 §59 'Edit hundreds of files safely' — "
        "rename_symbol returns a dry-run preview (no writes) instead of "
        "rewriting every matching file when the match count exceeds this, "
        "unless the caller passes confirm_large_batch=true. Safety valve "
        "against an unbounded, blast-radius write triggered by an "
        "over-broad old_name/directory combination.",
    )
    batch_edit_max_files: int = Field(
        default=100,
        description="T2-B8 (2026-09-24, GRIDIRON_PARTIAL #257 'Modify 100+ "
        "files') — batch_edit returns a dry-run preview (no writes) instead "
        "of rewriting every file whose content actually matches when that "
        "count exceeds this, unless the caller passes "
        "confirm_large_batch=true. Same safety-valve shape as "
        "rename_symbol_max_files, deliberately a lower default since "
        "batch_edit's caller-specified file list has no glob/pattern "
        "narrowing the blast radius the way rename_symbol's file_pattern "
        "does.",
    )

    # Pipeline behaviour
    pipeline_mode: str = Field(
        default="auto",
        description="auto=smart router picks the fewest agents (small/medium task → "
        "one or two specialists; large → full pipeline) | simple=planner+coder | "
        "full=always PM→Architect→Decomposer",
    )
    # 2026-09-29 — see app/fleet/cost_mode.py. economy: Haiku tier, no optional
    # aux LLM calls (planner/reflection/critique/replan/lesson), no per-subtask
    # LLM quality gates, 15-turn cap. balanced: Sonnet cap, planner/critique/
    # lesson on. quality: the pre-2026-09-29 behaviour. Safety controls
    # (sandbox, policy, scoped writes, human approvals) are identical in all.
    cost_mode: str = Field(
        default="economy",
        description="LLM cost profile for every agent run: economy | balanced | quality.",
    )
    strict_submit_tools: str = Field(
        default=(
            "submit_patch,submit_fix,submit_migration,submit_plan,"
            "submit_architect_plan,submit_subtasks,submit_brief"
        ),
        description=(
            "Comma-separated submit tools whose output feeds code or plans: a "
            "submission that does not match the tool's input_schema is rejected "
            "before its handler runs and the agent must resubmit. Every other "
            "submit tool keeps the soft behaviour (accepted with a warning). "
            "Owner decision 2026-10-06 (PENDING_TESTS_API_KEYS.md L1)."
        ),
    )
    max_retries: int = Field(
        default=3, description="Max self-correction retries before blocked"
    )
    context_token_budget: int = Field(
        default=8000, description="Max tokens for context assembly"
    )
    chat_history_restore_limit: int = Field(
        default=200,
        description="audit_v1.md 4.4 #3: load_history_from_db() had no LIMIT "
        "at all — loaded every message row for a session, unbounded, whenever "
        "an in-memory chat session needed restoring. Caps the restore query to "
        "the most recent N messages; ChatAgent's own condense step still runs "
        "on top of this bounded set for anything still over the token budget.",
    )
    llm_call_timeout_seconds: float = Field(
        default=300.0,
        description="Timeout (seconds) applied to every Anthropic SDK client "
        "construction. Without this, LLM calls rely entirely on the SDK's own "
        "undocumented default, which could hang a worker thread indefinitely.",
    )
    llm_call_max_retries: int = Field(
        default=3,
        description="AUDIT_Q_BATCH08 §38/§66 'Internet disconnects'/'Exponential "
        "backoff': explicit, config-driven max_retries passed to every "
        "Anthropic SDK client construction. The SDK already retries "
        "connection errors/408/409/429/5xx with exponential backoff and "
        "jitter internally when this is set >0 (its own undocumented-here "
        "default was 2, applied implicitly) — making it explicit and "
        "settings-driven, per this codebase's zero-hardcoding convention, "
        "instead of leaving real retry behavior silently dependent on the "
        "SDK's own default. Distinct from and complementary to the circuit "
        "breaker below: this retries a single call transparently; the "
        "breaker fails fast across calls once a provider is clearly down.",
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
    # Stage 4 Cluster P (2026-08-05, STAGE4_BACKLOG.md) — before this fix, these
    # two fields (labeled "Haiku pricing") were the ONLY cost rate in the
    # codebase, applied to every agent's tokens regardless of real tier. 62 of
    # 73 registered agents route to Sonnet, 9 to Opus (agent_models.json) — the
    # overwhelming majority of real fleet cost was computed at the wrong,
    # cheaper rate. These two fields are now the Sonnet-tier rate (also used as
    # the fallback for any tier without its own dedicated field below, mirroring
    # ModelRouter.route()'s own fallback-to-sonnet convention in
    # app/fleet/model_router.py). See cost_controller.cost_rates_for_tier() for
    # the tier-aware lookup. Sourced from Anthropic's published per-model
    # pricing (claude-sonnet-5, standard rate — not the temporary introductory
    # rate that expires 2026-08-31, so this default does not go stale on that
    # date); verified 2026-08-05, not recalled from training data.
    cost_per_input_token: float = Field(
        default=0.000003,
        description="Cost per input token (USD) — Sonnet tier (claude-sonnet-5); "
        "also the fallback rate for tiers without a dedicated field",
    )
    cost_per_output_token: float = Field(
        default=0.000015,
        description="Cost per output token (USD) — Sonnet tier (claude-sonnet-5); "
        "also the fallback rate for tiers without a dedicated field",
    )
    cost_per_input_token_haiku: float = Field(
        default=0.000001,
        description="Cost per input token (USD) — Haiku tier (claude-haiku-4-5). "
        "Sourced from Anthropic's published pricing, verified 2026-08-05.",
    )
    cost_per_output_token_haiku: float = Field(
        default=0.000005,
        description="Cost per output token (USD) — Haiku tier (claude-haiku-4-5). "
        "Sourced from Anthropic's published pricing, verified 2026-08-05.",
    )
    cost_per_input_token_opus: float = Field(
        default=0.000005,
        description="Cost per input token (USD) — Opus tier (claude-opus-4-8). "
        "Sourced from Anthropic's published pricing, verified 2026-08-05.",
    )
    cost_per_output_token_opus: float = Field(
        default=0.000025,
        description="Cost per output token (USD) — Opus tier (claude-opus-4-8). "
        "Sourced from Anthropic's published pricing, verified 2026-08-05.",
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
    # Gap-closure (Batch 2 audit, §2 "Multiple agents work simultaneously
    # (fan-out)"): run_manager()'s subtask loop was a strict sequential
    # for-loop even for subtasks with no depends_on edge between them.
    # Real, tested wave-based concurrent dispatch now exists (bounded by
    # the existing agent_run_slot/subtask_slot semaphores, same as the
    # sequential path), gated behind this flag and defaulting False for
    # the same reason base_graph.py's own enable_replanning defaults False
    # — landing a new capability without changing behavior for any
    # existing caller/test that never opts in.
    enable_subtask_fanout: bool = Field(
        default=True,
        description="Dispatch independent subtasks (no depends_on edge) concurrently in dependency-respecting waves instead of strictly sequentially. T2-B1 (2026-09-22, GRIDIRON_PARTIAL #43): flipped on by default after the audit's own recommended rollout — the mechanism is real, tested (concurrent overlap, depends_on ordering, and git-commit-lock serialization across a shared worktree all proven in tests/test_subtask_fanout.py). Set to false to force the old strictly-sequential path.",
    )

    # plan14 follow-on #2 (Dynamic Subtask Creation) — the highest-risk item
    # in the backlog per its own audit ("genuine risk of destabilizing an
    # existing, working invariant if rushed"): subtasks were created exactly
    # once, up front, and run_manager()'s wave/order computation assumed a
    # static, complete list. dynamic_subtask_creation_enabled_agents is
    # EMPTY by default (unlike replanning_enabled_agents, which defaulted 4
    # agents True to preserve pre-existing behavior) — this is a brand-new
    # capability with no prior behavior to preserve, so the safe default is
    # every agent off, opted in explicitly per the plan's own recommendation
    # ("Build behind a feature flag, enabled only for specific epics/agents
    # initially"). An agent absent from this dict (the default for all of
    # them) never gets the propose_subtask tool wired at all — see
    # app.agents.manager._dispatch_one_subtask.
    dynamic_subtask_creation_enabled_agents: dict[str, bool] = Field(
        default_factory=dict,
        description="agent_name -> whether that agent gets the propose_subtask tool wired into its own dispatch call. Empty by default (nobody enabled) — this is a new capability, not preserving prior behavior.",
    )
    dynamic_subtask_max_per_epic: int = Field(
        default=5,
        description="Hard cap on the total number of dynamically-proposed subtasks integrated into one epic's run_manager() call, regardless of how many are proposed — bounds worst-case runaway self-replication.",
    )
    dynamic_subtask_max_depth: int = Field(
        default=2,
        description="Max spawn depth for a dynamically-proposed subtask (an original static subtask is depth 0; a subtask it proposes is depth 1; a subtask THAT proposes is depth 2, etc.) — a proposal that would exceed this is rejected regardless of dynamic_subtask_max_per_epic headroom.",
    )
    dynamic_subtask_allowed_matrix: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "backend_dev": ["backend", "test"],
            "frontend_dev": ["frontend", "test"],
        },
        description="proposing_agent_name -> list of subtask `type` values it may propose. Same config-driven, default-deny-outside-the-list shape as delegation_allowed_matrix (Day 4) — a proposal for a type not in its proposer's list is rejected, never silently reinterpreted.",
    )

    # AUDIT_Q_BATCH16 §90 gap-closure (2026-08-11) — "Quality Gates": only
    # linting and tests were mandatory in the Dev→QA→Review pipeline;
    # security_reviewer and architecture_reviewer are real, fully-built,
    # independently-working agents (already used in the autonomous fleet
    # scan loop) that simply had no call site in the pipeline deciding
    # whether a normal task is "done" — a wiring gap, not a missing-
    # capability gap. Wired as non-blocking/advisory (findings are logged
    # and persisted, never flip subtask_status to "blocked") — same
    # precedent as enable_subtask_fanout: a real capability, opt-in,
    # defaulting False so no existing caller/test/cost-budget assumption
    # changes without an operator explicitly choosing the extra 2 LLM
    # calls per subtask this adds.
    enable_security_architecture_gates: bool = Field(
        default=True,
        description="Run security_reviewer, architecture_reviewer and dependency_security_agent as real quality gates after each subtask's QA/review passes — critical/high findings (security_architecture_gates_block_severities) now get one real self-correction retry through the dev agent (T2-B5, GRIDIRON_PARTIAL #453/#455) before blocking, the same safety net reviewer-blocking-findings already had, which is what makes mandatory-by-default safe here.",
    )

    # AUDIT_Q_BATCH18 §24 High-priority #7 gap-closure ("Only 2 of 8 quality-
    # gate types (linting, tests) are mandatory ... despite security/
    # architecture/dependency-check agents already existing") — the prior
    # fix (above) wired security_reviewer/architecture_reviewer into the
    # pipeline but kept them permanently advisory-only, and
    # dependency_security_agent had no call site in the normal-task
    # pipeline at all. Both closed here: dependency_security_agent now runs
    # alongside the other two gates, and any gate producing a critical/high-
    # severity finding on a *verified* run flips subtask_status to
    # "blocked" — the same real, pre-existing blocked-subtask escalation
    # path (task.blocked event, epic-halt-after-N-blocked-subtasks) every
    # other blocking gate in this pipeline already uses, not a new
    # mechanism. Only takes effect when enable_security_architecture_gates
    # is also True (itself still opt-in, defaulting False) — an operator
    # who hasn't opted into running these gates at all sees zero behavior
    # change. An operator who HAS opted in gets this as the honest, intended
    # next step (surfacing findings that are never acted on is a materially
    # weaker gate than what "quality gate" implies) — defaulting non-empty
    # rather than empty, since a silently-inert blocking severity set would
    # just reproduce the exact advisory-only gap this setting exists to
    # close for anyone who opts into enable_security_architecture_gates
    # going forward without also having to discover and set a second flag.
    security_architecture_gates_block_severities: list[str] = Field(
        default=["critical", "high"],
        description="Severities from security_reviewer/architecture_reviewer findings (and any dependency_security_agent finding on a verified/audited run) that flip subtask_status to 'blocked' instead of merely logging advisory findings. Empty list restores pure advisory-only behavior. Only consulted when enable_security_architecture_gates=True.",
    )

    # #457 (2026-09-25, GRIDIRON_PARTIAL "Documentation checks (mandatory
    # pre-completion gate)") — a fifth, free (no LLM call) gate alongside
    # security/architecture/dependency/performance, run whenever
    # enable_security_architecture_gates=True (no separate opt-in flag,
    # same "already-gated umbrella" treatment #454's license check got).
    # Threshold, not a hard 0, since a subtask can legitimately touch a
    # file with pre-existing undocumented symbols it didn't itself add —
    # doc_coverage.py only reports symbols missing docstrings in files the
    # subtask's own diff touched, but can't distinguish "added this run"
    # from "already there"; a small non-zero default absorbs that honest
    # imprecision without making the gate toothless.
    documentation_gate_max_undocumented_public_symbols: int = Field(
        default=2,
        description="Max undocumented top-level public function/class symbols allowed across a subtask's own changed .py files before the documentation gate blocks (see doc_coverage.py). Only consulted when enable_security_architecture_gates=True.",
    )

    # #297 (2026-09-28, GRIDIRON_PARTIAL "Use documentation while coding
    # automatically (no explicit call)") — the audit's own plan explicitly
    # rejected a generic "looks stuck, fetch docs" heuristic as too fragile
    # and named the one narrow, high-confidence trigger it trusts: "only
    # fire when an import fails to resolve". Real, deterministic
    # (code_hygiene.py's own AST-based import-resolution check, no LLM
    # judgment call about when to look something up), and bounded to a
    # handful of real PyPI network calls per subtask attempt — default True
    # since a broken import is, by construction, already a real bug the
    # subtask needs to fix on its next retry attempt regardless; this only
    # makes that fix faster by handing the dev agent real registry data
    # instead of a bare ImportError.
    enable_auto_doc_lookup_on_broken_import: bool = Field(
        default=True,
        description="When a subtask's own changed .py files contain an import that code_hygiene.py's real resolution check confirms cannot resolve, look up that package on PyPI (see doc_lookup.py) and feed the real result back to the dev agent as a retry hint, instead of only reporting a bare unresolved-import error.",
    )
    auto_doc_lookup_max_imports_per_attempt: int = Field(
        default=3,
        description="Max distinct unresolved imports looked up per subtask attempt (bounds real PyPI network calls). Only consulted when enable_auto_doc_lookup_on_broken_import=True.",
    )

    # Phase 5 — DevOps Agent bash allowlist (comma-separated command prefixes)
    devops_bash_allowlist: str = Field(
        default="git status,git log,git diff,df -h,du -sh,ls,pwd,cat,echo,free -h,uptime",
        description="Comma-separated read-only bash command prefixes allowed for DevOps Agent",
    )

    # tool_enhance.md productionization pass, tool #1 (bash) — the ~15
    # separately-scoped bash-tool variants across app/agents/tools.py each
    # hardcoded their own subprocess timeout literal (120/60/30, varying by
    # variant) — a real rule-5 violation ("NO ARBITRARY HARDCODING...
    # Production limits must be configuration-driven"). One dict, keyed by
    # a stable per-variant identifier, rather than 15 separate named
    # fields — matches this codebase's own established keyed-dict
    # convention (replanning_enabled_agents, dynamic_subtask_allowed_
    # matrix) and needs no new field when a 16th variant is added later.
    # Every default below is the EXACT value that variant's call site
    # already hardcoded — this is a zero-behavior-change extraction, not a
    # tuning pass; retuning any one variant is now a config change instead
    # of a code change.
    bash_tool_timeout_seconds: dict[str, int] = Field(
        default_factory=lambda: {
            "test_runner": 120,
            "load_test": 120,
            "dependency_audit": 120,
            "infra_dry_run": 120,
            "coder": 60,
            "qa": 120,
            "devops": 30,
            "cicd": 30,
            "refactor": 60,
            "dependency_agent": 60,
            "migration": 60,
            "ai_engineer": 120,
            "cleanup": 60,
            "chat": 120,
            "scoped": 60,
        },
        description="bash-tool-variant -> subprocess/sandbox timeout in seconds. Keys match app.agents.tools's internal variant identifiers (see each bash handler's own get_settings().bash_tool_timeout_seconds.get(...) call). A variant absent from this dict falls back to that call site's own literal default, preserving today's behavior exactly.",
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
    memory_score_weight_usefulness: float = Field(
        default=0.05,
        description="T2-B4 (2026-09-22, GRIDIRON_PARTIAL #98 'Memory Quality "
        "Control (accuracy validation)') — composite memory ranking: weight on "
        "the real helpful_count/not_helpful_count usage-feedback signal "
        "(POST /api/memory/{id}/feedback), neutral (0.5) until a memory has "
        "actually been rated at least once. Weights need not sum to 1.0 "
        "(not enforced, same as the others above) — this only mildly "
        "re-ranks otherwise-close matches.",
    )
    memory_recency_half_life_days: float = Field(
        default=30.0,
        gt=0,
        description="Days for a memory's recency contribution to decay to half its "
        "initial value. audit_v1.md 4.4 #4: previously had no positivity guard — "
        "a misconfigured 0 was a divisor in the composite score expression, "
        "silently zeroing every memory retrieval fleet-wide (caught by a broad "
        "except Exception, returns []) instead of failing loudly at startup per "
        "CLAUDE.md's own 'never a silent default' rule. Now fails fast.",
    )
    memory_reuse_cap: int = Field(
        default=20,
        description="reuse_count value at which the reuse contribution to composite ranking saturates at 1.0",
    )
    memory_candidate_overfetch_factor: int = Field(
        default=10,
        description="audit_v1.md 4.4 #1: composite ranking's ORDER BY buries the "
        "pgvector distance operator inside a larger arithmetic expression, which "
        "defeats the HNSW index — Postgres can't use it for that sort shape. The "
        "fix is two-stage retrieval: an inner, index-accelerated "
        "'ORDER BY embedding <=> :vec LIMIT top_k * this_factor' overfetch, then "
        "the full composite formula re-ranks only that small candidate set. "
        "Higher = better recall (composite ranking sees more candidates) at the "
        "cost of a slightly larger re-rank step; the ANN fetch itself stays cheap "
        "either way since it's index-accelerated.",
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

    # plan14 Day 1 Task 1 (Dynamic Tool Selection) — narrows each agent's static
    # tool list at runtime to what can actually execute (handler present) and,
    # for high-risk tools, what the agent's own registered AgentCapability.tools
    # contract declares. Never adds a tool. Default True; a caller-side failure
    # in the filter itself is non-fatal and falls back to the untouched list, so
    # this flag exists to allow disabling the narrowing behavior itself if a
    # false-positive drop is ever suspected in production.
    # plan14 Day 2 Task 4 (Memory Quality Gate) — deterministic (no LLM, no
    # regex) pre-store gate for memory_embeddings writes specifically: the
    # "routine memory" tier of the wider quality-tiering design. The
    # separate lessons/versioned_lessons system (LLM/HITL-tiered) is
    # unaffected by these settings. 'reject' skips the DB insert entirely
    # (near-empty/placeholder candidates only). 'draft' still inserts the
    # row (content is never silently discarded except at the reject tier),
    # marked verified=False and with importance dampened by
    # memory_quality_draft_importance_factor — deliberately NOT the
    # archived column: archived/archived_at are app/services/retention.py's
    # own hard exclusion filter (`WHERE archived = false` — every query_*
    # AND the retention job's own re-archival query), and a real
    # regression run proved a quality-gated row pre-set to archived=True at
    # write time makes the retention job's own cutoff query find zero
    # candidates for it forever (tests/test_memory_archived_filter.py::
    # test_real_retention_job_output_is_actually_excluded_end_to_end failed
    # this way before this was caught and fixed) — two independent lifecycle
    # concerns collapsed onto one hard-filter boolean. verified/importance
    # are confirmed soft ranking-only signals (grepped: never used in a hard
    # WHERE filter anywhere), so a draft row stays genuinely findable — just
    # ranked low by the existing composite score formula — with zero
    # collision risk against retention or any other archived-based logic.
    # Deliberately low reject/draft floors — a stated preference like "use
    # tabs not spaces" is legitimately short and must not be rejected
    # outright, only drafted at most.
    memory_quality_gate_enabled: bool = Field(
        default=True,
        description="If true, embed_*() write functions run a deterministic length/specificity check before inserting: reject near-empty candidates outright, mark borderline ones as an unverified/low-importance draft, publish the rest normally",
    )
    memory_quality_reject_min_length_chars: int = Field(
        default=15,
        description="Combined description+summary text shorter than this is rejected outright (never inserted) — catches empty/placeholder writes like '', 'done', 'ok'. Length-only, deliberately not also gated on distinct-token-count (see evaluate_memory_quality's own docstring for why a token floor at the reject tier proved too aggressive against real short-but-legitimate content)",
    )
    memory_quality_draft_min_length_chars: int = Field(
        default=40,
        description="Combined text shorter than this (but at/above the reject floor) is inserted as a draft (verified=False, dampened importance) rather than published at full weight",
    )
    memory_quality_draft_min_distinct_tokens: int = Field(
        default=6,
        description="Fewer distinct tokens than this (but at/above the reject floor) is inserted as a draft rather than published at full weight",
    )
    memory_quality_draft_importance_factor: float = Field(
        default=0.3,
        description="Multiplier applied to the category's normal _default_importance() score for draft-tier rows — pushes them toward the bottom of the composite ranking without hiding them from retrieval entirely",
    )

    dynamic_tool_selection_enabled: bool = Field(
        default=True,
        description="If true, run_agent_graph() narrows each agent's static tool list to tools with a live handler, and further narrows high-risk tools to those declared in the agent's own capability_registry contract",
    )

    # plan14 Day 1 Task 2 (Confidence-Gated Control Flow) — run_agent_graph()
    # already has a working quality_gate_min_confidence mechanism
    # (base_graph.py::_run_quality_gate), proven end to end by
    # tests/test_phase37_quality_gate.py, but every one of the ~76 real
    # callers left it at the implicit 0.0 default, which can never fail the
    # confidence check — inert in production despite being fully built. This
    # dict is the config-driven, per-agent staged-rollout mechanism: a caller
    # looks up its own role_name here (falling back to 0.0 — today's
    # unchanged, inert behavior — when absent) instead of a hardcoded
    # threshold in code. Only "spike_agent" is seeded below — the plan's own
    # "1-2 low-risk agents first" pilot scope (spike_agent: risk_level="low"
    # per its own AGENT_CONTRACT, and already produces a real per-run
    # confidence score via enable_planning=True). Expanding to more agents is
    # a config-only change (add another key here), never a code change.
    quality_gate_min_confidence_by_agent: dict[str, float] = Field(
        default_factory=lambda: {"spike_agent": 0.5, "qa": 0.5},
        description="Per-agent quality_gate_min_confidence override, keyed by "
        "role_name/AGENT_CONTRACT['name']. An agent's own run_agent_graph() call "
        "site looks itself up here; absent keys fall back to 0.0 (today's "
        "unchanged, inert default). 0.5 for spike_agent is a conservative floor "
        "— below-coinflip planner confidence is flagged for review, not merely "
        "below-perfect confidence — chosen for the pilot rollout, adjustable "
        "here without a code change. T2-B3 (2026-09-22, GRIDIRON_PARTIAL #130) "
        "added 'qa' as the second real pilot agent — a low-confidence QA verdict "
        "is exactly the case that should get a human's eyes before the "
        "reviewer/merge stage proceeds on it.",
    )

    # AUDIT_Q_BATCH03 §120 "Context Window Management" — NO/not found:
    # format_full_memory_context truncates individual fields ([:500]/[:300]/
    # [:800]) but nothing capped the combined memory_context block itself
    # before it's injected into the system prompt, so a query returning
    # several large sections (tasks + failures + learnings + procedures, each
    # near its own per-field cap) had no aggregate ceiling. Set to 0 to
    # disable (no cap, prior behaviour).
    memory_injection_token_budget: int = Field(
        default=3000,
        description="Max estimated tokens (~4 chars/token, same rough "
        "heuristic app.agents.chat_agent._estimate_tokens already uses) for "
        "the memory_context block memory_hook_node injects into the system "
        "prompt each run; the block is truncated with a logged warning if "
        "the estimate exceeds this. 0 disables the cap.",
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
    scanner_max_indexable_file_bytes: int = Field(
        default=2_000_000,
        description="audit_v1.md 4.2 #3: repo_tools/scanner.py's index_repository() "
        "used to read full file bytes for every file on every walk (even an "
        "'incremental' reindex only skipped the parse, not the disk read), with "
        "no per-file size cap. Files larger than this (checked via a cheap "
        "os.stat() before ever reading bytes) are skipped from indexing entirely "
        "— generated bundles/lockfiles/binary-like files don't belong in the "
        "symbol index anyway.",
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

    # plan14 Day 2 Task 3 (Session Memory Compression) — LessonStore.add()'s
    # existing capacity-exceeded fallback (self._lessons.pop(0), blind FIFO
    # eviction of the oldest lesson regardless of content) stays the fallback
    # here — these settings only control the LLM-based compression LessonStore
    # now tries FIRST, per the governing 5-day spec's "extend the existing
    # LessonStore, do not build a second session-memory system" instruction.
    lesson_compression_enabled: bool = Field(
        default=True,
        description="If true, LessonStore.add() tries to LLM-compress the largest same-category group of related (Jaccard-overlapping) lessons into one, before falling back to FIFO eviction, when at capacity",
    )
    lesson_compression_min_group_size: int = Field(
        default=3,
        description="Minimum number of related same-category lessons required before compression is attempted; smaller groups fall through to plain FIFO eviction (not worth an LLM call to compact 1-2 lessons)",
    )
    lesson_compression_jaccard_threshold: float = Field(
        default=0.3,
        description="Jaccard token-overlap ratio (same-category lessons) above which two lessons are considered 'related' for compression grouping. Deliberately lower than lesson_dedup_similarity_threshold (0.8) — dedup only collapses near-identical repeats, this groups genuinely distinct-but-topically-related lessons for an LLM to merge without losing information",
    )
    lesson_compression_llm_timeout_seconds: float = Field(
        default=10.0,
        description="Timeout for the lesson-compression LLM call specifically — deliberately much shorter than llm_call_timeout_seconds (300s) and uses 0 retries via its own isolated client, never the shared _call_anthropic/circuit-breaker path. This call is a best-effort background optimization on LessonStore.add()'s hot path (invoked after every agent submission, ~76 agents), not a critical-path submission — it must never block that path for anywhere near 300s, and a failing/unreachable compression call must never count toward (and potentially trip) the shared Anthropic circuit breaker that real, critical agent submissions depend on.",
    )

    # Phase 7 — Concurrency
    max_concurrent_epics: int = Field(
        default=10, description="Max number of epics running simultaneously"
    )
    max_concurrent_agent_runs: int = Field(
        default=20, description="Max total agent runs running at once across all epics"
    )
    db_pool_size: int = Field(
        default=20,
        description="Blocker (audit_v1.md 4.7 #2): create_async_engine() had "
        "no explicit pool sizing — SQLAlchemy's async default is 5 + 10 "
        "overflow = 15, already smaller than max_concurrent_agent_runs's own "
        "designed concurrency ceiling (20) before accounting for request "
        "handling and the isolated throwaway engines this codebase also "
        "creates elsewhere. Matches max_concurrent_agent_runs by default so "
        "the pool isn't the bottleneck under the app's own designed load.",
    )
    db_pool_max_overflow: int = Field(
        default=10,
        description="Extra connections beyond db_pool_size the pool may open "
        "under burst load before QueuePool raises.",
    )
    db_statement_timeout_ms: int = Field(
        default=30000,
        description="AUDIT_Q_BATCH08 §66 'Timeout handling': server-side "
        "statement_timeout (ms) applied to every connection this app's pool "
        "opens, via asyncpg's server_settings — no DB query could previously "
        "hang a connection (and, transitively, an agent run or request "
        "handler awaiting it) indefinitely. 0 disables (Postgres default: no "
        "timeout) for callers that need a longer-running query.",
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
    worktree_retention_days: int = Field(
        default=7,
        description="The daily retention loop removes the git worktree of a task that has been completed/failed/cancelled for this many days (blocked or review-waiting tasks keep theirs). Before production audit 09 only reject/complete/push-approval removed worktrees, so failed and cancelled tasks kept theirs forever. 0 disables.",
    )
    slot_acquisition_timeout_seconds: float = Field(
        default=2100.0,
        description="Max seconds to wait for an agent_run_slot()/subtask_slot() before raising SlotAcquisitionTimeout. Must exceed MAX_RUN_TIME_SECONDS: a slot held by a healthy run frees within that time, so a shorter wait failed queued work under normal load instead of letting it wait its turn (production audit 09; was 300).",
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
    queue_job_retry_max: int = Field(
        default=3,
        description="Blocker 8 (audit_v1.md 4.7 #2): max automatic RQ retries "
        "per enqueued job before it lands in RQ's own FailedJobRegistry. Only "
        "applies when QUEUE_BACKEND=rq.",
    )
    job_wall_clock_timeout_seconds: int = Field(
        default=1800,
        description="AUDIT_Q_BATCH08 §102 'Long-Running Jobs': wall-clock "
        "timeout applied to every job dispatched via "
        "app.pipeline.queue_adapter.dispatch_job(), regardless of backend. "
        "Previously only QUEUE_BACKEND=rq had a bound "
        "(app.queue.rq_adapter._DEFAULT_JOB_TIMEOUT) — the default "
        "QUEUE_BACKEND=asyncio path (FastAPI BackgroundTasks) had no wall-clock "
        "bound at all, only max_turns's turn-count limit. Same 1800s default "
        "as the RQ path so behavior doesn't silently depend on which backend "
        "an operator chose.",
    )
    idempotency_key_ttl_seconds: int = Field(
        default=86400,
        description="AUDIT_Q_BATCH08 §66 'Idempotency': how long a stored "
        "Idempotency-Key response (app.middleware.idempotency, "
        "idempotency_keys table) is honored before the retention loop "
        "purges it. 24h default — long enough to cover a client's realistic "
        "retry window, short enough that the table doesn't grow unbounded.",
    )
    queue_failed_job_sweep_interval_seconds: int = Field(
        default=300,
        description="How often the background loop scans RQ's FailedJobRegistry "
        "for jobs that exhausted queue_job_retry_max and records them as "
        "structured failed_events rows (Blocker 8, audit_v1.md 4.7 #2 — "
        "previously a failed RQ job was a silent drop, no application code "
        "ever read FailedJobRegistry). Only runs when QUEUE_BACKEND=rq.",
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
    redis_streams_drain_interval_seconds: int = Field(
        default=60,
        description="How often the background loop drains/acks the Redis "
        "Streams event stream (see app.event_bus.redis_streams."
        "drain_and_ack_stream). Only runs when REDIS_STREAMS_ENABLED=true.",
    )
    redis_streams_stale_pending_ms: int = Field(
        default=60_000,
        description="audit_v1.md 4.6 #2 (Phase K): a message read via "
        "XREADGROUP but never XACK'd (consumer crashed mid-processing) sits "
        "in the Pending Entries List forever with no recovery path unless "
        "reclaimed. The drain loop (app.event_bus.redis_streams."
        "drain_and_ack_stream) uses XAUTOCLAIM to reclaim entries idle "
        "longer than this many milliseconds.",
    )

    # S3 artifact storage (optional — falls back to DB when unset)
    artifact_backend: str = Field(
        default="db",
        description="Artifact storage backend: 'db' (local disk with the "
        "artifact's path tracked in a Postgres row — NOT the artifact bytes "
        "themselves, despite the name; see audit_v1.md 4.6 finding L-1) or "
        "'s3' (AWS S3, bytes actually stored in S3).",
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
    checkpoint_retention_days: int = Field(
        default=30,
        description="Blocker (audit_v1.md 4.1 #5): days to keep LangGraph "
        "checkpoint/checkpoint_blobs/checkpoint_writes rows before deletion "
        "(hard delete, not archive — these are replay/resume scaffolding, "
        "not audit history). Every run_agent_graph() call mints a fresh "
        "uuid4/uuid6 thread_id never reused, so this table previously grew "
        "unbounded forever with zero cleanup. Set to 0 to disable.",
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
    cross_run_loop_window: int = Field(
        default=3,
        description="T2-B10 (2026-09-24, GRIDIRON_PARTIAL #442 'Detect "
        "looping agents (cross-run)') — reconcile_orphaned_runs() will not "
        "auto-resume an orphan whose (task_id, agent_type) pair has failed "
        "this many times in a row (most recent runs, real AgentRun.status "
        "history) — it's marked failed and escalated instead of resumed "
        "again, breaking a genuine cross-run loop.",
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

    # Stage 4 Tier 3 (2026-08-05, answer2.md Q92) — "abandoned library" is a
    # distinct signal from "outdated": pip index versions/npm outdated only
    # compare installed-vs-latest, never expose *when* latest was published,
    # so a package with a recent latest release looks identical to one whose
    # "latest" is itself years old. dependency_agent's new check_last_release
    # tool queries the real PyPI/npm registry APIs for the latest release's
    # publish date and classifies staleness against these thresholds.
    dependency_abandoned_threshold_days: int = Field(
        default=730,
        description="Days since a package's latest release before it's classified abandoned.",
    )
    dependency_possibly_abandoned_threshold_days: int = Field(
        default=365,
        description="Days since a package's latest release before it's classified possibly abandoned.",
    )

    # Stage 4 Tier 3 (2026-08-05, answer2.md Q43) — RunMetrics.confidence is
    # purely self-reported by the planner's own LLM call, never checked
    # against anything. app.fleet.metrics.check_confidence_calibration()
    # flags a real mismatch between that self-report and this same run's
    # other, independently-computed signals (verification_pct,
    # reflection_unsatisfied) using these 3 thresholds.
    confidence_miscalibration_min_confidence: float = Field(
        default=0.8,
        description="Self-reported confidence at or above this is 'high confidence' for the calibration check.",
    )
    confidence_miscalibration_max_verification_pct: float = Field(
        default=0.5,
        description="Real verification_pct below this, alongside high self-reported confidence, is flagged as a mismatch.",
    )
    confidence_miscalibration_min_reflection_unsatisfied: int = Field(
        default=2,
        description="reflection_unsatisfied at or above this, alongside high self-reported confidence, is flagged as a mismatch.",
    )

    # Stage 4 Tier 3 (2026-08-05, answer2.md Q7) — real, bounded chat-side
    # user-frustration detection (app.agents.user_sentiment). Thresholds for
    # the 2 numeric signals (message repetition, excessive capitalization).
    user_frustration_repeat_similarity_threshold: float = Field(
        default=0.6,
        description="Jaccard word-overlap ratio against a recent prior user message, at or above which the current message is flagged as a near-repeat.",
    )
    user_frustration_repeat_min_words: int = Field(
        default=4,
        description="Minimum distinct words in a message before the near-repeat check applies (a 'yes'/'ok'/'continue' answered twice is an answer, not a sign the user is repeating themselves).",
    )
    user_frustration_excessive_caps_ratio: float = Field(
        default=0.5,
        description="Fraction of alphabetic characters that are uppercase, at or above which a long-enough message is flagged as excessive caps.",
    )
    user_frustration_excessive_caps_min_len: int = Field(
        default=10,
        description="Minimum message length before the excessive-caps check applies (avoids flagging short messages like 'OK' or 'NO').",
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

    # AUDIT_Q_BATCH11 §21 "Secret management" — optional AWS Secrets Manager
    # overlay (app/security/secrets_manager.py). Disabled by default: every
    # field continues to load from env vars/.env exactly as before. When
    # enabled, values fetched from the named secret fill in any field NOT
    # already set via env var/.env (explicit env always wins), and a fetch
    # failure fails startup loudly rather than silently booting with
    # whatever was already in the environment.
    secrets_manager_enabled: bool = Field(
        default=False,
        description="When true, load Settings overrides from AWS Secrets Manager at startup (see SECRETS_MANAGER_SECRET_ID). Disabled by default — no behavior change unless explicitly opted in.",
    )
    secrets_manager_secret_id: str = Field(
        default="",
        description="AWS Secrets Manager secret name or ARN, holding a JSON object of Settings field-name -> value pairs. Required when SECRETS_MANAGER_ENABLED=true.",
    )
    secrets_manager_region: str = Field(
        default="",
        description="AWS region for the Secrets Manager client. Leave empty to use boto3's default region resolution (env var / instance profile / ~/.aws/config).",
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
    job_sandbox_network: str = Field(
        default="none",
        description="Sol A11 (2026-10-06): Docker --network for the code-running "
        "tools' job sandbox (python snippets, node, tests, scripts, make, "
        "profiler, npm scripts). 'none' (default): job code cannot reach the "
        "control plane (DB, Redis, the API), the host, cloud metadata or the "
        "internet. Package installs use job_sandbox_install_network instead.",
    )
    job_sandbox_install_network: str = Field(
        default="bridge",
        description="Sol A11: Docker --network for the approval-gated package "
        "installs (pip_install, npm_install) — they need the package index. "
        "Keep control-plane ports bound to 127.0.0.1 (docker-compose.yml does), "
        "so the bridge gateway cannot reach them; set 'none' to forbid installs.",
    )
    bash_sandbox_streaming_enabled: bool = Field(
        default=True,
        description="T2-B9/#12 (2026-09-24, GRIDIRON_PARTIAL 'Monitor streaming "
        "output (live, mid-command)') — when True, the interactive chat "
        "session's own `bash` tool pushes real terminal_output SSE events as "
        "the sandboxed command's stdout/stderr actually arrive (line-buffered), "
        "instead of only returning the full output once the command exits. "
        "Shipped default False behind a feature flag per the audit's own "
        "explicit plan ('change it behind a feature flag first ... keep the "
        "old buffered path as fallback until it's proven stable') while its "
        "backend was the only thing that existed; flipped to True on "
        "2026-09-25 once the frontend consumer (apps/web/app/chat/page.tsx's "
        "terminal_output handling) was built and verified — without a "
        "consumer, the events were being computed and pushed for nothing. "
        "run_sandboxed()'s own buffered SandboxResult return value is "
        "computed identically either way, so flipping this off at any time "
        "still degrades to exactly the pre-existing buffered behavior, never "
        "a functional loss beyond the live-updates themselves.",
    )
    pty_terminal_enabled: bool = Field(
        default=False,
        description="Q12 (2026-09-24, 'Real interactive PTY terminal') — when "
        "True, exposes the GET/WebSocket /api/terminal/ws/{chat_session_id} "
        "endpoint, which allocates a real pseudo-terminal (Python's `pty` "
        "module) and execs a sandboxed `docker run -it` session inside it "
        "(app.tools.execution.pty_session.PtySession) — a genuine interactive "
        "shell with real stdin, live streaming stdout/stderr, Ctrl+C, and "
        "terminal resize, as opposed to the request/response `bash` tool. "
        "Default False (a brand-new execution surface, not an extension of an "
        "existing proven one) — when False the endpoint refuses every "
        "connection with a clear close code instead of silently degrading, "
        "matching this project's established feature-flag-first rollout "
        "discipline for anything that grants new command execution.",
    )
    pty_terminal_image: str = Field(
        default="gridiron-bash-toolchain:latest",
        description="Docker image for interactive PTY sessions. Defaults to "
        "the same toolchain image bash_sandbox_toolchain_image already "
        "builds (docker/bash-sandbox/Dockerfile) rather than "
        "bash_sandbox_image's minimal alpine:latest default, because "
        "PtySession execs `bash` directly (a real shell prompt needs a real "
        "shell) — alpine's default image has no bash installed at all.",
    )
    pty_terminal_network: str = Field(
        default="bridge",
        description="Docker --network mode for interactive PTY sessions — "
        "same choices and reasoning as bash_sandbox_network ('bridge' "
        "default so a human's interactive session can still e.g. curl/pip "
        "install; 'none' for deployments that can accept losing "
        "network-dependent interactive commands in exchange for stricter "
        "egress isolation).",
    )

    # tool_enhance.md productionization pass, bash tool, follow-up
    # sandboxing-coverage extension (2026-08-15) — this is exactly the
    # "custom image with it preinstalled" bash_sandbox_image's own
    # description above already anticipated. docker/bash-sandbox/Dockerfile
    # builds `gridiron-bash-toolchain:latest`: python:3.12-slim + git +
    # this project's own pinned requirements-dev.txt/requirements.txt
    # (pytest/mypy/ruff/black/pip-audit/alembic, verified via `pip show`
    # against the real host venv before pinning, plus every real runtime
    # dependency so a sandboxed pytest run can actually import app.* code).
    # Used only by the toolchain-needing bash variants (test_runner, qa,
    # refactor, dependency_audit, dependency_agent, devops, cicd,
    # load_test, migration) — the original 5 denylist-only variants
    # (coder/chat/scoped/ai_engineer/cleanup) keep using the minimal
    # bash_sandbox_image default, unchanged.
    bash_sandbox_toolchain_image: str = Field(
        default="gridiron-bash-toolchain:latest",
        description="Docker image (built from docker/bash-sandbox/Dockerfile) used for the bash-tool variants that need this project's own Python/git toolchain — pytest, mypy, ruff, black, pip-audit, alembic, git all preinstalled at the exact versions this project's own requirements pin. Must be built (`docker build -t gridiron-bash-toolchain:latest -f docker/bash-sandbox/Dockerfile .`) before those variants can run inside the sandbox; app.policy.sandbox's own SandboxUnavailableError-style fail-closed behavior surfaces a clear error rather than silently falling back if the image is missing.",
    )
    bash_tool_sandbox_network: dict[str, str] = Field(
        default_factory=lambda: {
            "test_runner": "host",
            "qa": "host",
            "refactor": "host",
            "migration": "host",
        },
        description="bash-tool-variant -> Docker --network override for sandboxed execution, when the variant needs to reach this deployment's own Postgres. Real, verified constraint (not a guess): docker-compose.yml deliberately binds Postgres to 127.0.0.1 only (\"host-only, not reachable from the network\" — see that file's own comment), so a default bridge-network sandboxed container cannot reach it at all, even via host.docker.internal (verified: that resolves to the bridge gateway, but the loopback-only bind still refuses the connection from there). network=host was verified to work cleanly with zero DATABASE_URL rewriting. A variant absent from this dict uses bash_sandbox_network's own default (bridge) — this is a narrow, evidence-driven exception for the specific variants whose real, legitimate functionality (running the project's own pytest suite, or applying a real migration) would otherwise break, not a blanket network-isolation downgrade for every sandboxed variant.",
    )

    # tool_enhance.md productionization pass, tool #2 (create_pr), P0 review
    # item #8 (2026-08-15) — the sync create_pr_handler used by
    # make_chat_handlers() (and, via it, any one-shot agent that legitimately
    # advertises create_pr in its own tools list) runs in an execution
    # context with NO interactive interrupt()/pause mechanism — unlike
    # chat_agent.py's own create_pr dispatch, which gates behind a real
    # self._confirm() pause. Every one-shot handler shares the uniform
    # Callable[[dict], str] signature the whole agent-graph dispatch relies
    # on (app/agents/base_graph.py's `tool_handlers.get(tu_name)(tu_input)`)
    # — there is no channel today for a real human decision to reach a
    # mid-call handler for this agent tier, and an `inp["_approved"]`-style
    # flag would be meaningless (`inp` is LLM-controlled tool-call JSON, so
    # the model could simply always set it). The only honest gate available
    # at this layer is a static, operator-set deployment decision: fail
    # closed by default (matches this codebase's existing
    # bash_sandbox_enabled / SandboxUnavailableError fail-closed pattern),
    # explicit True opt-out only for a deployment that has decided its
    # one-shot agents may autonomously open PRs (or that layers its own
    # separate approval mechanism above this handler).
    create_pr_require_approval: bool = Field(
        default=True,
        description="When True (default), the sync create_pr_handler (used by make_chat_handlers()) always refuses to run `gh pr create` — there is no real per-call human-approval channel available to this handler tier. Set False only for a deployment that has explicitly decided its one-shot agents may autonomously open PRs. Does not affect chat_agent.py's own create_pr dispatch, which already has its own real, independent self._confirm() interactive gate.",
    )

    # tool_enhance.md productionization pass, tool #4 (git_push, 2026-08-16)
    # — real gap found while auditing: chat_agent.py's git_push dispatch
    # already always requires confirmation, but its own tool description
    # promises force-push gets "extra confirmation" — the code gave force
    # and normal pushes the identical single confirmation dialog. Branches
    # here are config-driven (not hardcoded in decision logic) so a
    # deployment can adjust what counts as protected.
    git_push_protected_branches: list[str] = Field(
        default_factory=lambda: ["main", "master"],
        description="Branch names that get a distinct, stronger confirmation warning when force-pushed via the interactive chat agent's git_push tool — force-rewriting one of these is materially more dangerous (shared history other people/CI depend on) than a feature branch only the current session's agent is using.",
    )
    # Same real gap class as create_pr_require_approval above, found while
    # auditing docker_compose: its "up" action creates/starts containers
    # from whatever docker-compose.yml is in the repo, with no restriction
    # on privileged/host-mount config — a real, legitimate one-shot agent
    # (docker_agent) has docker_compose in its allowed_tools today, so
    # this one (unlike most of the other session-gated tools.py handlers
    # audited alongside it, which have no real one-shot caller at all)
    # actually is reachable and was a live, permanently-broken dead end
    # for that agent before this fix.
    docker_compose_up_require_approval: bool = Field(
        default=True,
        description="When True (default), the sync docker_compose handler (used by make_chat_handlers(), reachable by docker_agent) always refuses the 'up' action — there is no real per-call human-approval channel available to this handler tier. Set False only for a deployment that has explicitly decided its one-shot agents may autonomously start containers. Does not affect chat_agent.py's own docker_compose dispatch, which has its own real, independent self._confirm() interactive gate for 'up' as of this same pass.",
    )

    # Day 10 — Fleet OS Budget Manager (live enforcement, per-run + daily cumulative)
    max_tokens_per_agent_run: int = Field(
        default=1_500_000,
        description="Max total BILLED tokens (in+out, summed over every LLM call — each call re-sends the conversation) a single agent run may consume before it is stopped. Set MAX_TOKENS_PER_AGENT_RUN in .env. 1.5M ~ $4.5 of Sonnet input worst case; a 30-turn coder run with a 60k context is ~1.8M before prompt-cache savings.",
    )
    cost_budget_daily_usd: float = Field(
        default=25.0,
        description="Fleet-wide hard cap on LLM spend (USD) per UTC day, across every agent and every LLM call. Checked BEFORE each call (fleet/spend_guard.py) and before new work is dispatched; 0 disables.",
    )
    spend_guard_redis: bool = Field(
        default=True,
        description="Keep the daily LLM spend ledger (fleet/spend_guard.py) in Redis (REDIS_URL) so every worker process shares one total that survives restarts. False = in-process counter only (tests).",
    )
    max_run_time_seconds: int = Field(
        default=1800,
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
    fleet_success_rate_sync_interval_hours: float = Field(
        default=1.0,
        description="AUDIT_Q_BATCH15 §37 gap-closure — hours between syncing "
        "AgentCapability.success_rate (fleet_manager.select()'s routing "
        "input) from real AgentRun outcomes, so routing scores reflect "
        "actual agent performance instead of a static registration-time "
        "constant. 0 disables.",
    )

    # plan14 Day 3 Task 6 (Performance-Aware Runtime Decisions) —
    # FleetManager.select()'s scoring formula already weighs health/
    # success_rate/error_count/tenure/confidence; these add cost and latency
    # as two more real (MetricsCollector-tracked, not fabricated) ranking
    # signals. Both default to 1.0 (neutral, today's exact scoring
    # unchanged) for any agent with no run history yet.
    #
    # Deliberately a CAPPED linear penalty (1 - min(x*weight, max_penalty)),
    # not an unbounded 1/(1+x) curve — matching tenure_factor's own capped-
    # bonus shape (1 + min(x, 0.3)) elsewhere in this file/fleet_manager.py.
    # A real regression test caught the unbounded version letting an
    # extreme cost/latency outlier (e.g. $5 + 60s) flip a 0.95-vs-0.3
    # success_rate gap — the audit's own instruction ("Performance MUST NOT
    # override capability/health/security... is a ranking signal, not an
    # authorization signal") is honored more robustly by a hard cap: even
    # BOTH penalties simultaneously maxed out (0.7 * 0.7 = 0.49x) can never
    # flip a real, multi-times success_rate gap, only break near-ties —
    # the same guarantee tenure/confidence already provide.
    fleet_select_cost_penalty_weight: float = Field(
        default=0.1,
        description="Multiplies an agent's avg_cost_usd (MetricsCollector.avg_cost_usd) before capping at fleet_select_max_cost_penalty in FleetManager.select()'s cost_factor term. 0 disables the cost penalty entirely (cost_factor becomes always 1.0).",
    )
    fleet_select_max_cost_penalty: float = Field(
        default=0.3,
        description="Upper bound on how much avg_cost_usd can reduce cost_factor below 1.0 (0.3 = at most a 30% reduction, regardless of how expensive the agent is).",
    )
    fleet_select_latency_penalty_weight: float = Field(
        default=0.01,
        description="Multiplies an agent's p50 latency in seconds before capping at fleet_select_max_latency_penalty in FleetManager.select()'s latency_factor term. 0 disables the latency penalty entirely.",
    )
    fleet_select_max_latency_penalty: float = Field(
        default=0.3,
        description="Upper bound on how much p50 latency can reduce latency_factor below 1.0 (0.3 = at most a 30% reduction, regardless of how slow the agent is).",
    )

    # plan14 follow-on #3 (Memory-Aware Agent Selection) — a durable,
    # cross-process complement to confidence_factor above: AgentInstance.
    # avg_confidence is in-process only (resets on restart), while this
    # reads AgentHistoricalPerformance, a scheduled rollup over
    # memory_embeddings.agent_name (real per-run outcomes, durable across
    # restarts). Same "neutral (1.0) until real history exists, capped
    # bonus/penalty, never a live join on FleetManager's hot path" shape as
    # tenure_factor/cost_factor/latency_factor above.
    agent_historical_performance_enabled: bool = Field(
        default=True,
        description="Master switch for both the background rollup job (app.fleet.agent_historical_performance) and FleetManager.select()'s memory_performance_factor term. False keeps select()'s exact pre-plan14-follow-on-#3 scoring.",
    )
    agent_historical_performance_rollup_interval_hours: float = Field(
        default=6.0,
        description="Hours between background recomputations of agent_historical_performance from memory_embeddings. Deliberately a scheduled rollup, not a live join, per plan14's own #3 spec — keeps FleetManager.select() a fast in-process/DB-row read, not an aggregation query, on every dispatch.",
    )
    fleet_select_memory_performance_weight: float = Field(
        default=0.3,
        description="How much AgentHistoricalPerformance.success_rate (category='task') can move memory_performance_factor away from 1.0 in FleetManager.select(), scaled to fleet_select_max_memory_performance_penalty. Same capped-linear shape as cost_factor/latency_factor — a real success_rate=0.9 memory history can move the factor at most fleet_select_max_memory_performance_penalty either direction, never enough to flip a live health/success_rate gap on its own.",
    )
    fleet_select_max_memory_performance_penalty: float = Field(
        default=0.2,
        description="Cap on memory_performance_factor's deviation from 1.0 in either direction (0.2 = factor stays in [0.8, 1.2]) — smaller than fleet_select_max_cost_penalty/fleet_select_max_latency_penalty since this is a slower-moving, longer-horizon signal (hours-old rollup) rather than a live per-run metric.",
    )
    fleet_select_memory_performance_min_samples: int = Field(
        default=3,
        description="AgentHistoricalPerformance rows with sample_size below this are treated as insufficient evidence (memory_performance_factor stays neutral at 1.0), same 'don't let sparse data overreact' principle tenure_factor's log1p curve already applies to total_runs.",
    )

    # plan14 Day 4 (#1 Agent-to-Agent Delegation + #13 Delegation Safety +
    # #12 Agent Communication) — confirmed fully absent by repo-wide grep
    # before building this: no delegate_to_agent, no cycle detection, no
    # depth limit, no caller matrix anywhere. Built as one unit, the most
    # security-sensitive day per the governing spec. delegation_allowed_matrix
    # is config-driven (never hardcoded agent names in decision logic) —
    # maps a real, registered source agent_name to the target capabilities
    # (not agent names — FleetManager.select() resolves the concrete agent)
    # it may delegate to.
    delegation_enabled: bool = Field(
        default=True,
        description="If false, delegate_to_agent's handler refuses every delegation request outright (DelegationDisabledError), regardless of policy/depth/budget.",
    )
    delegation_max_depth: int = Field(
        default=3,
        description="Maximum delegation chain length (source -> target -> target's own target -> ...). A request at this depth is refused before dispatch, not after — never a silent infinite/deep recursion.",
    )
    delegation_max_delegations_per_run: int = Field(
        default=5,
        description="Maximum number of delegate_to_agent calls a single top-level agent run may make in total (tracked via the delegation count already present in ancestry/ledger, not a separate global counter) — bounds fan-out cost independent of depth.",
    )
    delegation_default_timeout_seconds: float = Field(
        default=300.0,
        description="Wall-clock timeout for a single delegated agent invocation. Exceeding it raises DelegationTimeoutError and returns a structured failure to the parent — never silently hangs the parent's own turn.",
    )
    delegation_default_budget_usd: float = Field(
        default=1.0,
        description="Budget (USD) allocated to a NEW top-level delegation chain when the initiating agent doesn't already have its own remaining-budget context. Every subsequent delegation in that chain draws down from this same allocation — a child never receives a fresh, unrestricted budget.",
    )
    delegation_allowed_matrix: dict[str, list[str]] = Field(
        default_factory=lambda: {
            # "*new*" = may ask for a capability no static agent has; barot_agent
            # then spawns a short-lived read-only temporary_agent (audit 15).
            "backend_dev": ["security_review", "research_spike", "*new*"],
            "frontend_dev": ["security_review", "research_spike", "*new*"],
            "bug_fix": ["security_review", "*new*"],
        },
        description="source agent_name -> list of target capabilities (not agent names) it may delegate to. An agent absent from this dict, or requesting a capability not listed for it, is refused (DelegationNotAllowedError). Deliberately a small, explicit allow-list, not all-to-all — expanding it is a config-only change.",
    )

    # plan14 Day 5 Task 10 (Adaptive Runtime Replanning) — extends the
    # existing _should_replan() (single "repeated failure" heuristic) with
    # two more real, already-tracked-state-grounded triggers, and moves
    # "which agents get replanning" from a hardcoded `enable_replanning=True`
    # literal in 4 agent files to config, per the governing spec's own
    # "use configurable thresholds/policies" instruction. Every default below
    # preserves today's exact behavior for the 4 already-enabled agents
    # (coder/pm/qa/security_reviewer) while making both "which agents" and
    # "how sensitive" real config, not code.
    replanning_enabled_agents: dict[str, bool] = Field(
        default_factory=dict,
        description="T2-B1 (2026-09-22, GRIDIRON_PARTIAL #47/#65/#106/#117): a fleet-wide "
        "default rollout of the already-proven, already-tested replanning mechanism — "
        "run_agent_graph() now treats 'caller passed nothing' as True for every real agent "
        "(see its own docstring on enable_replanning), matching the audit's own recommended "
        "rollout after the pilot period. This dict is now an EXCEPTION list — set an agent "
        "name to False here to opt a specific agent OUT (e.g. a purely read-only reporting "
        "agent with no real 'redo the plan' failure mode), never to opt one in; the old "
        "'absent means off' meaning is gone. Chat/pipeline-only entry points that don't call "
        "run_agent_graph (chat_agent, pm/architect/decomposer's own pipeline graph) are "
        "unaffected either way.",
    )
    critique_enabled_agents: dict[str, bool] = Field(
        default_factory=dict,
        description="T2-B1 (2026-09-22, GRIDIRON_PARTIAL #123): same fleet-wide-default "
        "rollout as replanning_enabled_agents, for the self-critique mechanism — every real "
        "role file already has a genuine Quality Gates/Success Criteria section for the "
        "critique node to score against (confirmed by the audit before this rollout). An "
        "exception list for agents to opt OUT of critique, not a hand-maintained opt-in list.",
    )
    replanning_reflection_failure_threshold: int = Field(
        default=2,
        description="_should_replan()'s existing 'failure' trigger: consecutive reflection_unsatisfied_count judgments before replanning fires. Unchanged default from the pre-plan14 hardcoded value.",
    )
    replanning_critique_failure_threshold: int = Field(
        default=2,
        description="_should_replan()'s existing 'failure' trigger: consecutive critique_retries on the same unmet criteria before replanning fires. Unchanged default from the pre-plan14 hardcoded value.",
    )
    replanning_confidence_threshold: float = Field(
        default=0.5,
        description="NEW 'new-information' trigger: if the planner's own state['confidence'] is below this floor, replan — the plan was built on genuinely uncertain footing, distinct from a failure that's already happened during execution. 0.5 matches the same 'below-coinflip' reasoning already used for quality_gate_min_confidence_by_agent's pilot threshold (Day 1 Task 2).",
    )
    replanning_blocked_turn_threshold: int = Field(
        default=4,
        description="NEW 'blocked/dependency' trigger: if at least this many turns have passed and a required verification key (VerificationConfig.enforce_in_result) the agent's own contract cares about still isn't satisfied, replan — real evidence the plan's assumptions about the environment/dependencies aren't holding, not a fabricated heuristic. Only checked for agents that actually declare enforce_in_result requirements.",
    )

    prompt_auto_rollback_interval_hours: float = Field(
        default=4.0,
        description="AUDIT_Q_BATCH15 §118 gap-closure — hours between checking "
        "every deployed role prompt for a real regression against its stored "
        "benchmark baseline (regression_detector.check_fleet()) and "
        "auto-rolling back any that has one (prompt_registry.rollback()). "
        "0 disables.",
    )
    prompt_auto_rollback_cooldown_hours: float = Field(
        default=24.0,
        description="AUDIT_Q_BATCH15 §118 gap-closure — minimum hours between "
        "two automatic rollbacks of the same role's prompt, so a still-warming "
        "metrics ring buffer right after a rollback can't immediately trigger "
        "another one (oscillation guard).",
    )
    agents_score_compute_interval_hours: float = Field(
        default=24.0,
        description="AUDIT_Q_BATCH15 §117 gap-closure — hours between computing "
        "and persisting each active repo's agents_score (mean baseline "
        "benchmark_score of agents that actually ran against that repo). "
        "0 disables.",
    )
    tools_score_compute_interval_hours: float = Field(
        default=24.0,
        description="T2-B7 (2026-09-24, GRIDIRON_PARTIAL #414) — hours between "
        "computing and persisting each active repo's tools_score (mean real "
        "AgentRun.tool_accuracy over recent runs scoped to that repo). "
        "0 disables.",
    )
    prompts_score_compute_interval_hours: float = Field(
        default=24.0,
        description="T2-B7 (2026-09-24, GRIDIRON_PARTIAL #414) — hours between "
        "computing and persisting each active repo's prompts_score (fraction "
        "of relevant roles currently passing regression_detector's real "
        "deploy-gate check). 0 disables.",
    )
    documentation_score_compute_interval_hours: float = Field(
        default=24.0,
        description="GRIDIRON_PARTIAL #414 re-verification (2026-09-28) — hours "
        "between computing and persisting each active repo's "
        "documentation_score (fraction of recent doc_coverage.py subtask "
        "gate events that passed rather than blocked). 0 disables.",
    )
    dependency_auto_dispatch_interval_seconds: float = Field(
        default=60.0,
        description="T2-B7 (2026-09-24, GRIDIRON_PARTIAL #429 'Detect "
        "dependencies / optimize order org-wide (auto-dispatch)') — seconds "
        "between scans for DevTask rows blocked_reason='dependency' whose "
        "depends_on have all reached 'completed', auto-dispatching them "
        "instead of requiring a human/caller to manually retry POST /run. "
        "0 disables.",
    )
    # AUDIT_Q_BATCH18 §69 gap-closure (2026-08-12) — "Autonomous Quality
    # Improvement" / "rollback if quality declines": real and automatic for
    # PROMPT versions (prompt_auto_rollback_* above) but not for
    # EnhancementRequest-driven CODE commits until this. Same fully-
    # automatic (no human-approval gate) risk posture as its prompt
    # sibling — see app.fleet.enhancement_rollback's module docstring for
    # why that's the honest, consistent choice rather than a more
    # conservative one invented just for this dimension.
    enhancement_quality_monitor_interval_hours: float = Field(
        default=6.0,
        description="How often the scheduled loop checks completed, "
        "commit_sha-bearing EnhancementRequests for a post-apply success-rate "
        "decline. 0 disables.",
    )
    enhancement_quality_monitor_pre_window_hours: float = Field(
        default=168.0,
        description="Hours of AgentRun history BEFORE an enhancement's "
        "completed_at used as its 'before' baseline success rate (default: 7 days).",
    )
    enhancement_quality_monitor_min_post_window_hours: float = Field(
        default=48.0,
        description="Minimum hours that must have elapsed since an enhancement's "
        "completed_at before its post-apply success rate is judged — avoids "
        "reacting to a handful of runs in the first few minutes/hours.",
    )
    enhancement_quality_monitor_min_runs: int = Field(
        default=5,
        description="Minimum real AgentRun count required in BOTH the pre- and "
        "post-apply windows before a decline verdict is reached — insufficient "
        "data in either window means 'not yet evaluable', never a fabricated verdict.",
    )
    enhancement_quality_decline_threshold: float = Field(
        default=0.15,
        description="Minimum success-rate drop (pre - post, as a fraction, e.g. "
        "0.15 = 15 percentage points) that counts as a real decline triggering "
        "an automatic `git revert` of the enhancement's commit_sha.",
    )
    # AUDIT_Q_BATCH18 Bonus-table row 2 gap-closure (2026-08-12) — "In-
    # process singletons block horizontal scaling": LessonStore was purely
    # in-process, so lessons learned by one backend process's agents were
    # invisible to another's. Unlike the WRITE-side scheduled loops above
    # (which need leader election so only one instance runs the job), this
    # is a per-process READ-refresh — every backend process runs its own
    # copy independently, no coordination needed, so it is deliberately
    # NOT added to main.py's leader-election loop list.
    lesson_store_refresh_interval_seconds: float = Field(
        default=60.0,
        description="How often each backend process refreshes its own in-process "
        "LessonStore cache from the shared `lessons` DB table (merging lessons "
        "written by other processes since this process's last refresh). 0 disables.",
    )
    leader_election_enabled: bool = Field(
        default=True,
        description="Blocker (audit_v1.md 4.8 #5): 'No leader election / "
        "distributed lock — every backend instance runs every singleton "
        "background loop.' When true (default), each of main.py's background "
        "loops is gated by a Postgres pg_try_advisory_lock so only one "
        "backend instance actually runs it at a time; other instances retry "
        "acquisition periodically so a new leader takes over if the current "
        "one dies (the lock is session-scoped — released automatically when "
        "its holding connection closes, no heartbeat needed). Set false only "
        "for a deliberately single-instance deployment that wants to skip "
        "the lock round-trip.",
    )
    leader_election_retry_seconds: int = Field(
        default=30,
        description="How often a non-leader instance retries acquiring a "
        "background loop's advisory lock.",
    )

    # Stage 4 Cluster Q — Architecture slice (2026-08-05, app/fleet/architecture_score.py)
    # Per-severity weights for architecture_reviewer's structured risks[]
    # (a real JSON-schema enum, never narrative text). Policy defaults, same
    # category of config as benchmark_weight_* above — critical risks
    # dominate the score; a clean review (risks=[]) scores 1.0 vacuously,
    # mirroring benchmark_manager.py's own "no negative signal -> 1.0"
    # convention.
    architecture_score_weight_critical: float = Field(
        default=1.0, description="Per-risk weight for severity=critical."
    )
    architecture_score_weight_high: float = Field(
        default=0.5, description="Per-risk weight for severity=high."
    )
    architecture_score_weight_medium: float = Field(
        default=0.2, description="Per-risk weight for severity=medium."
    )
    architecture_score_weight_low: float = Field(
        default=0.05, description="Per-risk weight for severity=low."
    )
    architecture_score_risk_cap: float = Field(
        default=3.0,
        description="Weighted risk-point sum at which architecture_score bottoms out at "
        "0.0 (e.g. 3 uncleared critical risks, or an equivalent weighted mix). "
        "Policy threshold, adjustable — not a measured constant.",
    )

    # Stage 4 Cluster Q — Security slice (2026-08-05, app/fleet/security_score.py)
    # pip-audit's real JSON schema (verified by reading the installed
    # package) has no severity field, so this is a vulnerability-count
    # threshold, not a severity weight — a real, honest difference from
    # architecture_score_risk_cap above, not an oversight.
    security_score_vuln_cap: float = Field(
        default=5.0,
        description="Total unresolved-vulnerability count at which security_score "
        "bottoms out at 0.0. Policy threshold, adjustable — not a measured constant.",
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

    # plan14 Day 3 Task 5 (Memory Consolidation) — extends the existing Day 11
    # merge-on-conflict lifecycle to N-way: promote()'s reactive sweep (any
    # OTHER currently-published lesson similar enough gets merged at the
    # moment a new one goes live) and the proactive consolidate_published_
    # lessons() background pass (clusters existing published lessons and
    # proposes merged drafts for human review). Both reuse
    # memory_merge_similarity_threshold above rather than a second threshold.
    memory_consolidation_enabled: bool = Field(
        default=True,
        description="If true, promote() also sweeps for and merges (state='merged_into') other currently-published lessons within memory_merge_similarity_threshold of the just-promoted lesson's embedding",
    )
    memory_consolidation_max_merge_per_promote: int = Field(
        default=20,
        description="Bounds how many other published lessons a single promote() call can flip to merged_into in one sweep",
    )
    memory_consolidation_max_candidates: int = Field(
        default=200,
        description="Bounds consolidate_published_lessons()'s proactive scan to the N most-recently-published lessons, keeping its O(n^2) pairwise clustering pass cost-bounded",
    )
    memory_consolidation_min_cluster_size: int = Field(
        default=2,
        description="Minimum related-lesson cluster size for consolidate_published_lessons() to propose a merged draft — a 'cluster' of 1 is nothing to consolidate",
    )
    memory_consolidation_interval_hours: float = Field(
        default=24.0,
        description="Hours between app/main.py's _versioned_lesson_consolidation_loop runs — matches the existing daily cadence _versioned_lesson_archive_loop already uses for the same table",
    )
    memory_embeddings_retention_days: int = Field(
        default=180,
        description="Days to keep memory_embeddings rows before the retention loop marks them archived=true. 0 disables. Separate from LOG_RETENTION_DAYS since engineering memory is longer-lived than raw execution logs.",
    )

    # T2-B4 (2026-09-22, GRIDIRON_PARTIAL #100 "Memory Evolution (active
    # shrink/consolidate over time)") — app/memory/consolidation.py. Named
    # memory_EMBEDDINGS_consolidation_* (not memory_consolidation_*, already
    # taken above by the versioned_lessons consolidation loop) for the same
    # reason memory_embeddings_retention_days above is distinctly named from
    # log_retention_days — a different table, a different real feature.
    # versioned_lessons' consolidation proposes a DRAFT for human review
    # (promote() gates every real change); memory_embeddings has no such
    # human gate anywhere in its own lifecycle (writes are fully automatic,
    # scored only by the deterministic MemoryQualityDecision content check)
    # — auto-merging here is consistent with that existing design, not a new
    # risk class introduced by this feature.
    memory_embeddings_consolidation_enabled: bool = Field(
        default=False,
        description="If true, a leader-gated background loop periodically finds clusters of old, mutually-similar, still-active memory_embeddings rows and merges each cluster via a real LLM call, archiving the rest. OFF by default — unlike a per-task agent run, this is unbounded automatic background LLM spend running forever regardless of real platform usage; opt in deliberately once you've reviewed the cost knobs below.",
    )
    memory_embeddings_consolidation_interval_hours: float = Field(
        default=24.0,
        description="Hours between memory_embeddings consolidation cycles",
    )
    memory_embeddings_consolidation_min_age_days: int = Field(
        default=30,
        description="Only memory_embeddings rows older than this are consolidation candidates — recent memory is still actively being reinforced by reuse and shouldn't be merged away yet",
    )
    memory_embeddings_consolidation_min_group_size: int = Field(
        default=3,
        description="Minimum number of mutually-similar same-category rows required before a cluster is merged — smaller groups aren't worth an LLM call",
    )
    memory_embeddings_consolidation_similarity_threshold: float = Field(
        default=0.85,
        description="Cosine similarity above which two memory_embeddings rows are considered part of the same consolidation cluster — deliberately close to memory_dedup_similarity_threshold's 0.97 but a bit looser, since these are genuinely distinct-but-related old entries being merged for space, not near-duplicates",
    )
    memory_embeddings_consolidation_scan_limit: int = Field(
        default=200,
        description="Bounds each category's per-cycle candidate scan to the N oldest qualifying rows, keeping the O(n^2) pairwise clustering pass cost-bounded — same reasoning as memory_consolidation_max_candidates above",
    )
    memory_embeddings_consolidation_max_groups_per_cycle: int = Field(
        default=3,
        description="Hard cap on real LLM merge calls per consolidation cycle, across every category combined — the actual cost-control knob",
    )
    scratchpad_ttl_seconds: int = Field(
        default=14400,
        description="Max lifetime (seconds) of an epic_scratchpad entry before it's treated as expired, even if the epic never explicitly completes. Default 4 hours. Entries are also cleared outright the moment their epic completes — this TTL only matters for an epic that stalls or never finishes.",
    )
    # Gap-closure (Batch 2 audit, §2 "Duplicate work prevented"): same TTL
    # safety-net pattern as scratchpad_ttl_seconds above, for
    # app/pipeline/file_locks.py's real held file locks — an epic that
    # crashes mid-coding (never reaching _finalize_node's release call)
    # must not permanently deadlock a file for every future epic.
    epic_file_lock_ttl_seconds: int = Field(
        default=14400,
        description="Max lifetime (seconds) of an epic_file_locks row before it's treated as expired/stale, even if the epic never explicitly completes. Default 4 hours. Locks are also released outright the moment their epic completes — this TTL only matters for an epic that stalls or crashes mid-coding.",
    )

    # bhaskar_tool — universal "no existing tool fits" fallback. A small
    # LangGraph sub-agent (app/agents/bhaskar_agent.py) that writes and runs
    # a one-off script for a task no other tool covers, exposed to every
    # agent via app/tools/agents/bhaskar_tool.py. Every limit below is real,
    # enforced runtime behavior (bounded turns, wall-clock timeout, retry
    # cap, sandbox resource limits) per tool_enhance.md's own "declared
    # timeout metadata is NOT enough — verify actual enforcement" bar, not
    # decorative configuration.
    bhaskar_tool_enabled: bool = Field(
        default=True,
        description="Kill switch. If false, bhaskar_tool's handler refuses every call outright with a structured error, regardless of cache state.",
    )
    bhaskar_tool_cache_max_entries: int = Field(
        default=4,
        description="Max number of generated scripts kept in the bhaskar_tool cache (app/fleet/scratchpad.py's EpicScratchpad, sentinel epic_id) at once. Writing a 5th evicts the oldest — enforced atomically via write_entry_with_eviction's Postgres advisory lock so concurrent callers can never overshoot this bound.",
    )
    bhaskar_tool_cache_ttl_seconds: int = Field(
        default=1200,
        description="Lifetime (seconds) of one cached generated script — 20 minutes. Enforced the same way every other scratchpad entry's TTL is: read_entries only returns rows where expires_at > now, so an expired entry is simply invisible to a cache lookup even before any sweep deletes it.",
    )
    bhaskar_tool_max_turns: int = Field(
        default=6,
        description="max_turns passed to run_agent_graph() for the internal bhaskar_agent run. Deliberately small — this is a narrow-scope 'research + write + test one script' helper, not a general coding agent, so an LLM stuck in a loop is bounded early.",
    )
    bhaskar_tool_max_retries: int = Field(
        default=1,
        description="Max additional attempts if the internal bhaskar_agent run raises or finishes with status='failed'. Bounded, not infinite — after this many retries bhaskar_tool_handler returns a structured failure instead of trying again.",
    )
    bhaskar_tool_timeout_seconds: float = Field(
        default=180.0,
        description="Hard wall-clock bound (via asyncio.wait_for) on one bhaskar_agent attempt, independent of max_turns — a single slow turn (e.g. a hung LLM call) cannot hang the calling agent's turn past this.",
    )
    bhaskar_tool_sandbox_script_timeout_seconds: int = Field(
        default=45,
        description="Per-execution timeout for a script run inside bhaskar_tool's own sandbox (app/agents/bhaskar_sandbox.py) — both during generation (the internal agent testing its own draft) and on a cache-hit replay. Deliberately smaller than run_python_snippet's MAX_PYTHON_SNIPPET_TIMEOUT_SECONDS (300s): bhaskar-generated scripts are short, single-purpose, and run un-reviewed, so the ceiling is tighter.",
    )
    bhaskar_tool_sandbox_max_memory_mb: int = Field(
        default=512,
        description="RLIMIT_AS (address space) cap, in MB, applied to a sandboxed script's subprocess via preexec_fn on POSIX. A generated script that tries to allocate past this is killed by the kernel, not by application-level bookkeeping.",
    )
    bhaskar_tool_sandbox_max_output_file_mb: int = Field(
        default=10,
        description="RLIMIT_FSIZE cap, in MB, applied to a sandboxed script's subprocess — the kernel refuses any single file write past this size, regardless of what the generated code tries to do.",
    )
    bhaskar_tool_sandbox_max_output_chars: int = Field(
        default=4000,
        description="Max characters of captured stdout/stderr returned from a sandboxed script run — matches this codebase's existing run_python_snippet truncation convention (5000 chars) at a slightly tighter bound appropriate to a short single-purpose script.",
    )
    bhaskar_tool_sandbox_backend: str = Field(
        default="docker",
        description="Where synthesized scripts run. 'docker' (default): a throwaway container with no host files mounted, non-root, read-only root, all capabilities dropped, kernel memory/pid/CPU limits and a size-capped tmpfs; refuses to run if Docker is unavailable. 'process': the older in-process sandbox (Python-level file/network guards plus rlimits) — audit 15 (2026-10-06) showed its file guard can be bypassed via _io.FileIO/ctypes to read backend/.env, so use it only where Docker cannot run.",
    )
    bhaskar_tool_sandbox_allow_network: bool = Field(
        default=True,
        description="Whether sandboxed scripts may make outbound HTTP(S) connections at all. When true, every connection attempt is still individually validated by the injected network guard (app/agents/bhaskar_sandbox.py) — resolved once, every address checked (IPv4/IPv6, including IPv4-mapped IPv6) against the same private/loopback/link-local/reserved-range denylist app/agents/tool_security.py's _ssrf_denial_reason already enforces for fetch_url/check_url_status, then connected via a pinned validated IP rather than a second DNS lookup — set false to disable network entirely for an extra-cautious deployment. Left true by default because bhaskar_tool's own stated purpose (e.g. scraping a public site) requires it; the guard itself, not this flag, is what carries the security weight.",
    )
    bhaskar_tool_sandbox_max_total_disk_mb: int = Field(
        default=50,
        description="Total sandbox-directory size cap (MB), polled live by run_sandboxed_python's watchdog and enforced by killing the process group — distinct from bhaskar_tool_sandbox_max_output_file_mb's RLIMIT_FSIZE, which only bounds any ONE file's size, not the sum of many small ones.",
    )
    bhaskar_tool_sandbox_max_processes: int = Field(
        default=32,
        description="RLIMIT_NPROC cap applied to a sandboxed script's subprocess on POSIX — stops a fork-bomb-shaped script. Kept generous: RLIMIT_NPROC counts against the real UID system-wide (this sandbox process runs as the same OS user as the rest of the app, not a separate/dropped-privilege user), so a too-low value risks unpredictable failures unrelated to the sandboxed script itself.",
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

    # Gemini (optional — TEMPORARY, easily removable, see app/agents/
    # gemini_adapter.py's own docstring for the full removal list. A
    # second free-tier testing backend alongside Groq above, added
    # 2026-09-28 purely because Groq's own free-tier rate limit was too
    # tight to get through a full pending-tests pass alone.)
    gemini_api_key: str = Field(
        default="",
        description="Gemini API key (from ai.google.dev). When set and USE_GEMINI=true, all agent calls use Gemini instead of Anthropic. TEMPORARY testing-only backend — see gemini_adapter.py.",
    )
    use_gemini: bool = Field(
        default=False,
        description="Route all agent calls to Gemini instead of Anthropic. TEMPORARY testing-only backend, mirrors USE_GROQ — see gemini_adapter.py.",
    )
    gemini_model_planner: str = Field(
        default="gemini-flash-lite-latest",
        description="Gemini model for PM/Architect/Decomposer (Haiku equivalent). "
        "2026-09-28: gemini-2.5-flash's free tier is only 20 requests/DAY "
        "(GenerateRequestsPerDayPerProjectPerModel-FreeTier) — exhausted after "
        "one real pm_agent test file. gemini-flash-lite-latest has its own, "
        "separate quota pool and is confirmed working (real tool-calling "
        "round trip verified) — use this until real per-day numbers are known.",
    )
    gemini_model_coder: str = Field(
        default="gemini-flash-lite-latest",
        description="Gemini model for Coder/QA/Review agents (Sonnet equivalent). See gemini_model_planner's own note on why not gemini-2.5-flash.",
    )
    gemini_model_router: str = Field(
        default="gemini-flash-lite-latest",
        description="Gemini model for triage/summary/heartbeat (Haiku equivalent). See gemini_model_planner's own note on why not gemini-2.5-flash.",
    )
    gemini_max_retries: int = Field(
        default=5, description="Max Gemini API call retries on transient (429) errors."
    )

    @model_validator(mode="before")
    @classmethod
    def _load_secrets_manager_overrides(cls, values: object) -> object:
        """Overlays AWS Secrets Manager values (app/security/secrets_manager.py)
        onto whatever pydantic-settings already resolved from env vars/.env,
        BEFORE field validation/type-coercion runs. A no-op unless
        SECRETS_MANAGER_ENABLED=true (read directly from os.environ, since
        `values` here reflects env/.env/init — Settings itself doesn't exist
        yet). Only fills fields that aren't already set, so an explicit env
        var always takes precedence over the fetched value — predictable,
        and never silently overrides a value an operator deliberately set."""
        if not isinstance(values, dict):
            return values

        from app.security.secrets_manager import fetch_secrets_manager_overrides

        overrides = fetch_secrets_manager_overrides()
        for field_name, value in overrides.items():
            if not values.get(field_name):
                values[field_name] = value
        return values

    @model_validator(mode="after")
    def _require_llm_key(self) -> "Settings":
        if self.use_groq and not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is required when USE_GROQ=true.")
        if self.use_gemini and not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when USE_GEMINI=true.")
        if self.use_groq and self.use_gemini:
            raise ValueError(
                "USE_GROQ and USE_GEMINI cannot both be true — pick one temporary "
                "testing backend at a time."
            )
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
    def _require_secure_production_auth(self) -> "Settings":
        """Reject production configurations that leave control-plane access open."""
        if self.deployment_env != "production":
            return self

        if not self.jwt_auth_enabled:
            raise ValueError(
                "JWT_AUTH_ENABLED=true is required when DEPLOYMENT_ENV=production."
            )
        if not self.rbac_enabled:
            raise ValueError(
                "RBAC_ENABLED=true is required when DEPLOYMENT_ENV=production."
            )
        if self.allow_legacy_role_header:
            raise ValueError(
                "ALLOW_LEGACY_ROLE_HEADER=false is required when DEPLOYMENT_ENV=production."
            )
        if (
            self.default_admin_password == "gridiron123"
            or len(self.default_admin_password) < 12
        ):
            raise ValueError(
                "DEFAULT_ADMIN_PASSWORD must be a non-default value of at least 12 "
                "characters when DEPLOYMENT_ENV=production."
            )
        return self

    @model_validator(mode="after")
    def _require_durable_workspace_in_production(self) -> "Settings":
        # Blocker 7 (audit_v1.md 4.8 #10): worktrees_dir/repos_dir/
        # bg_process_registry_path all default to /tmp/... — a host
        # crash, container restart, or routine /tmp cleanup job silently
        # loses every in-flight git worktree and cloned repo, leaving DB
        # rows referencing paths that no longer exist. All three are
        # already fully operator-configurable via env vars (WORKTREES_DIR/
        # REPOS_DIR/BG_PROCESS_REGISTRY_PATH) — this only hard-fails
        # startup if a production deployment left them on the ephemeral
        # /tmp default, matching this file's existing pattern of refusing
        # to silently boot production with an unsafe default.
        if self.deployment_env != "production":
            return self
        _ephemeral = ("/tmp/", "/tmp")
        for field_name, value in (
            ("WORKTREES_DIR", self.worktrees_dir),
            ("REPOS_DIR", self.repos_dir),
            ("BG_PROCESS_REGISTRY_PATH", self.bg_process_registry_path),
        ):
            if value == "/tmp" or value.startswith("/tmp/"):
                raise ValueError(
                    f"{field_name} is set to {value!r}, under the ephemeral /tmp "
                    "filesystem, which is not permitted when DEPLOYMENT_ENV="
                    "production (a host restart or /tmp cleanup silently loses "
                    "in-flight worktrees/repos/state). Point it at a durable, "
                    "persistent-volume-backed path instead."
                )
        return self

    @model_validator(mode="after")
    def _require_s3_bucket_when_s3_backend(self) -> "Settings":
        if self.artifact_backend == "s3" and not self.s3_bucket:
            raise ValueError("S3_BUCKET is required when ARTIFACT_BACKEND=s3.")
        return self

    @model_validator(mode="after")
    def _validate_enum_fields(self) -> "Settings":
        if self.deployment_env not in ("development", "staging", "production"):
            raise ValueError(
                "DEPLOYMENT_ENV must be 'development', 'staging', or 'production', "
                f"got {self.deployment_env!r}"
            )
        if self.pipeline_mode not in ("auto", "simple", "full"):
            raise ValueError(
                "PIPELINE_MODE must be 'auto', 'simple' or 'full', "
                f"got {self.pipeline_mode!r}"
            )
        if self.cost_mode not in ("economy", "balanced", "quality"):
            raise ValueError(
                "COST_MODE must be 'economy', 'balanced' or 'quality', "
                f"got {self.cost_mode!r}"
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
        if self.use_gemini:
            return bool(self.gemini_api_key)
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
    rate_limit_trusted_proxies: str = Field(
        default="127.0.0.1,::1",
        description="Comma-separated IPs of reverse proxies (the Next.js frontend server) whose X-Forwarded-For is trusted for rate limiting. Requests from any other peer are keyed by their own IP. Logged-in requests are keyed per user regardless.",
    )
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
    rate_limit_login: str = Field(
        default="10/minute",
        description="Rate limit for the unauthenticated login/setup endpoints — deliberately "
        "tighter than rate_limit_default to slow credential stuffing/brute force.",
    )

    # JWT auth
    jwt_secret_key: str = Field(
        default="",
        description="Secret key for signing JWTs. REQUIRED in production. Generate with: openssl rand -hex 32",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT signing algorithm.")
    jwt_revalidate_against_db: bool = Field(
        default=True,
        description="Check every verified JWT against the users table (account still exists; role taken from the row, not the token) so deleting or demoting a user takes effect immediately instead of when their token expires. Cached ~15 s per user.",
    )
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
    agent_unhealthy_cooldown_seconds: float = Field(
        default=300.0,
        description="After this many seconds without a further failure an 'unhealthy' agent is offered one trial dispatch again (half-open); a success recovers it, a failure restarts the cooldown. 0 = an unhealthy agent stays excluded until something else recovers it.",
    )
    fleet_scan_interval_hours: float = Field(
        default=24.0,
        description="Hours between automatic SCAN-phase runs of the fleet self-improvement agents (background loop; 8 LLM scans per cycle). Daily by default (audit 15: every 4 h was ~48 LLM runs/day with nobody using the app). Set to 0 to disable the background loop entirely.",
    )
    fleet_scan_budget_fraction: float = Field(
        default=0.5,
        description="Background fleet scans only run while today's LLM spend is below this fraction of COST_BUDGET_DAILY_USD, so self-improvement can never use up the budget the owner's own tasks need. 1.0 = scans may use the whole cap.",
    )

    # barot_agent — just-in-time meta-agent. When fleet_manager.select() finds
    # no static agent for a required capability, barot_agent may synthesize a
    # short-lived temporary_agent to fill the gap. See app/agents/barot_agent.py
    # and app/agents/temporary_agent.py.
    barot_agent_enabled: bool = Field(
        default=True,
        description="Kill switch for the barot_agent just-in-time meta-agent. When False, fleet_manager.select() falls straight back to returning None on a capability gap, exactly as before this feature existed — zero code change needed to disable.",
    )
    barot_agent_model: str = Field(
        default="claude-sonnet-5",
        description="Model barot_agent uses both for its own planning calls (deciding a temporary_agent's tool profile) and, via ModelRouter.set_override, for the temporary_agent instances it spawns.",
    )
    barot_agent_fallback_models: list[str] = Field(
        default_factory=list,
        description="Ordered fallback models tried if barot_agent_model's planning call fails (empty response or an API error not already retried by the SDK/circuit breaker).",
    )
    barot_agent_max_concurrent_temp_agents: int = Field(
        default=3,
        description="Max live temporary_agent instances barot_agent may have at once. A gap task arriving at capacity is declined (falls through to fleet_manager.select()'s existing None-return) — never queued.",
    )
    barot_agent_temp_agent_ttl_minutes: float = Field(
        default=20.0,
        description="Wall-clock TTL per temporary_agent instance, enforced by the TTL sweep loop. An instance is torn down at task completion or this TTL, whichever is first — see TemporaryAgentPool.",
    )
    barot_agent_ttl_sweep_interval_seconds: float = Field(
        default=60.0,
        description="How often the background loop checks for expired temporary_agent instances. Set to 0 to disable the sweep loop entirely (TTL is then only enforced lazily, on the next pool interaction) — same '0 disables' idiom as fleet_scan_interval_hours.",
    )
    barot_agent_temp_agent_naming_pattern: str = Field(
        default="temporary_agent-{task_id}-{short_uuid}",
        description="str.format()-style pattern for spawned temporary_agent names/role_names. Must produce a value safe as a dict key, a role-file stem, and an AgentRun.agent_type string (no '/'). Available fields: task_id, short_uuid, capability.",
    )
    barot_agent_default_tool_scope: str = Field(
        default="planned",
        description="'planned' (only value implemented in this version): temporary_agent instances only ever get the read-only tool subset barot_agent's planning call selected. 'full' (write/bash tools backed by a real ephemeral git worktree) is accepted here but raises NotImplementedError at spawn time until a follow-up build adds worktree lifecycle wiring.",
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

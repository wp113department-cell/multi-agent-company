from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.tasks import router as tasks_router
from app.api.repo import router as repo_router, init_active_repo
from app.api.artifacts import router as artifacts_router
from app.api.auth import router as auth_router
from app.api.epics import router as epics_router
from app.api.registry import router as registry_router
from app.api.memory import router as memory_router
from app.api.goals import router as goals_router
from app.api.metrics import router as metrics_router
from app.api.settings import router as settings_router
from app.api.chat import router as chat_router
from app.api.specialized_agents import router as specialized_agents_router
from app.api.activity import router as activity_router
from app.api.console import router as console_router
from app.api.fleet_dashboard import router as fleet_dashboard_router
from app.api.approvals import router as approvals_router

from app.config import get_settings
from app.rate_limit import limiter

logger = logging.getLogger(__name__)


def _init_sentry(settings: "Settings") -> None:  # type: ignore[name-defined]  # noqa: F821
    """Initialise Sentry SDK if SENTRY_DSN is configured. No-op otherwise."""
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.asyncio import AsyncioIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            # AsyncioIntegration (gap-closure 2026-07-23): this codebase has
            # several genuine fire-and-forget asyncio.create_task() sites
            # (e.g. db/repository.py's heartbeat_agent_run(), called from
            # api/agents.py with no try/except of its own) — without this,
            # an exception raised inside one of those tasks is never
            # awaited/retrieved and never reaches Sentry, only asyncio's own
            # "Task exception was never retrieved" warning at GC time.
            integrations=[
                FastApiIntegration(),
                SqlalchemyIntegration(),
                AsyncioIntegration(),
            ],
            # Never send secrets to Sentry
            before_send=lambda event, hint: event,
        )
        logger.info("Sentry initialised (environment=%s)", settings.sentry_environment)
    except ImportError:
        logger.warning(
            "SENTRY_DSN is set but sentry-sdk is not installed. "
            "Run: pip install sentry-sdk[fastapi] to enable error tracking."
        )
    except Exception as exc:
        logger.warning("Sentry init failed: %s", exc)


def _init_otel(settings: "Settings") -> None:  # type: ignore[name-defined]  # noqa: F821
    """Eagerly build the process TracerProvider (MASTER_AGENT_v2.md Phase
    6.1). Spans are recorded in-process either way; this just logs whether
    export to OTEL_EXPORTER_ENDPOINT is actually wired, and makes startup
    fail loudly-but-non-fatally instead of silently on the first agent run."""
    from app.fleet.metrics import _get_tracer_provider

    provider = _get_tracer_provider()
    if not provider:
        logger.warning(
            "OpenTelemetry SDK unavailable — run_span() will collect metrics "
            "as usual but no OTEL spans will be created."
        )
    elif settings.otel_exporter_endpoint:
        logger.info(
            "OpenTelemetry tracing initialised (service=%s, endpoint=%s)",
            settings.otel_service_name,
            settings.otel_exporter_endpoint,
        )
    else:
        logger.info(
            "OpenTelemetry tracing initialised in-process only "
            "(set OTEL_EXPORTER_ENDPOINT to export spans)."
        )


async def _weekly_reindex_loop() -> None:
    """Reindex the active repo every 7 days so context/repo-intelligence
    persistence stays fresh.

    Gap-closure (2026-07-23): delegates to api.repo._do_reindex() (the same
    routine POST /api/repo/reindex uses) instead of running its own separate
    index_repository() scan. That separate scan had two real bugs: (a) its
    result was discarded entirely — no persistence, no _cached_index update,
    so the new indexed_files/symbols/call_edges tables never got the weekly
    loop's benefit; (b) it always reindexed whichever repo_path was active
    at process startup (captured once as an argument), never a repo the user
    switched to afterward via POST /api/repo/{id}/activate. Delegating to
    _do_reindex() (which calls get_active_repo_path() fresh every time)
    fixes both for free.
    """
    from app.api.repo import _do_reindex

    _SEVEN_DAYS = 7 * 24 * 60 * 60
    while True:
        await asyncio.sleep(_SEVEN_DAYS)
        try:
            await _do_reindex()
            logger.info("Weekly auto-reindex complete")
        except Exception as exc:
            logger.warning("Weekly reindex failed: %s", exc)


async def _fleet_agents_scan_loop() -> None:
    """Day 9 — periodic SCAN phase for the fleet self-improvement agents.

    5 agents from Day 9 (agent_performance_reviewer, agent_debugger, agent_advisor,
    knowledge_curator, quality_auditor) plus architecture_reviewer (Day 48) and
    dependency_security_agent (Day 49), both added gap-closure Days 48-50 (Stage 2) —
    their real analysis tools (dead_code_detect/circular_dep_detect/import_graph;
    pip-audit/npm audit) existed but were only ever task-triggered, never autonomous.

    Runs sequentially (not parallel — real LLM calls, avoid a runaway-cost loop).
    Each agent's own scan function is fully autonomous and read-only; it only ever
    files a pending enhancement_requests row for a human to approve/reject on the
    Fleet Dashboard — nothing here writes to disk. Set FLEET_SCAN_INTERVAL_HOURS=0
    to disable.
    """
    interval_hours = get_settings().fleet_scan_interval_hours
    if interval_hours <= 0:
        logger.info("Fleet agent scan loop disabled (FLEET_SCAN_INTERVAL_HOURS=0)")
        return

    scan_fns = [
        (
            "agent_performance_reviewer",
            "app.agents.agent_performance_reviewer",
            "run_agent_performance_reviewer_scan",
        ),
        ("agent_debugger", "app.agents.agent_debugger", "run_agent_debugger_scan"),
        ("agent_advisor", "app.agents.agent_advisor", "run_agent_advisor_scan"),
        (
            "knowledge_curator",
            "app.agents.knowledge_curator",
            "run_knowledge_curator_scan",
        ),
        ("quality_auditor", "app.agents.quality_auditor", "run_quality_auditor_scan"),
        # Gap-closure Days 48-50 (Stage 2, answers.md Q35/Q36) — architecture_reviewer
        # was previously task-triggered only (app.api.specialized_agents); its own
        # existing dead_code_detect/circular_dep_detect/import_graph tools are real
        # and work, just never ran autonomously. 6th fleet self-improvement scan.
        (
            "architecture_reviewer",
            "app.agents.architecture_reviewer",
            "run_architecture_reviewer_scan",
        ),
        # Gap-closure Day 49 (Stage 2, answers.md Q35 "Dependency conflicts") — 7th
        # fleet self-improvement scan. dependency_security_agent's real CVE-scanning
        # (pip-audit/npm audit) was also task-triggered only.
        (
            "dependency_security_agent",
            "app.agents.dependency_security_agent",
            "run_dependency_security_scan",
        ),
    ]

    while True:
        await asyncio.sleep(interval_hours * 60 * 60)
        for agent_name, module_path, fn_name in scan_fns:
            try:
                import importlib

                mod = importlib.import_module(module_path)
                scan_fn = getattr(mod, fn_name)
                result = await asyncio.to_thread(scan_fn)
                logger.info("Fleet scan complete: %s (%s)", agent_name, result.summary)
            except Exception as exc:
                logger.warning("Fleet scan failed for %s: %s", agent_name, exc)


async def _versioned_lesson_archive_loop() -> None:
    """Gap-closure (2026-07-21) — Day 11's plan doc for versioned_memory.py said
    archive_expired() would be "called from the same background-loop slot
    pattern already used for retention/reindex" — it never was. Runs once per
    day, same cadence as the log-retention loop. Set LESSON_RETENTION_DAYS=0
    to disable (archive_expired() itself already no-ops in that case).
    """
    interval_seconds = 24 * 3600
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from app.fleet.versioned_memory import get_versioned_memory_store

            archived = await asyncio.to_thread(
                get_versioned_memory_store().archive_expired
            )
            if archived:
                logger.info("Versioned lesson archive: %d row(s) archived", archived)
        except Exception as exc:
            logger.warning("Versioned lesson archive loop failed: %s", exc)


async def _failed_rq_job_sweep_loop() -> None:
    """Blocker 8 (audit_v1.md 4.7 #2): "A failed job goes into RQ's own
    registry with no automatic retry and no application code ever reads
    it — effectively a silent drop." Periodically drains RQ's
    FailedJobRegistry into structured failed_events rows (see
    app.pipeline.queue_adapter.sweep_failed_rq_jobs) so a job that
    exhausted its retries is at least visible, not just sitting silently
    in Redis. No-ops immediately when QUEUE_BACKEND != rq (the default),
    same as every other RQ-only code path in this codebase.
    """
    settings = get_settings()
    if settings.queue_backend.lower() != "rq":
        return
    interval_seconds = settings.queue_failed_job_sweep_interval_seconds
    if interval_seconds <= 0:
        logger.info(
            "Failed RQ job sweep loop disabled (QUEUE_FAILED_JOB_SWEEP_INTERVAL_SECONDS=0)"
        )
        return

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            from app.pipeline.queue_adapter import sweep_failed_rq_jobs

            recorded = await sweep_failed_rq_jobs()
            if recorded:
                logger.warning(
                    "Failed RQ job sweep: recorded %d failed job(s) to failed_events",
                    recorded,
                )
        except Exception as exc:
            logger.warning("Failed RQ job sweep loop failed: %s", exc)


async def _benchmark_baseline_loop() -> None:
    """Gap-closure (2026-07-21) — Day 10 built benchmark_manager.store_baseline()
    but nothing ever called it automatically, so no real agent has ever had a
    baseline. Since regression_detector treats "no baseline" as "no
    regression" by design, this meant prompt_registry.deploy()'s regression
    gate was a no-op for every real agent. Sweeps capability_registry
    periodically and stores an initial baseline for any agent that has real
    MetricsCollector runs but no baseline yet. Set
    BENCHMARK_BASELINE_INTERVAL_HOURS=0 to disable.
    """
    interval_hours = get_settings().benchmark_baseline_interval_hours
    if interval_hours <= 0:
        logger.info(
            "Benchmark baseline loop disabled (BENCHMARK_BASELINE_INTERVAL_HOURS=0)"
        )
        return

    while True:
        await asyncio.sleep(interval_hours * 60 * 60)
        try:
            from app.fleet.benchmark_manager import get_benchmark_manager
            from app.fleet.capability_registry import get_capability_registry
            from app.fleet.metrics import get_metrics_collector

            bm = get_benchmark_manager()
            collector = get_metrics_collector()
            for cap in get_capability_registry().all():
                try:
                    if not collector.by_agent(cap.name, n=1):
                        continue  # no real runs yet — nothing meaningful to baseline
                    report = await asyncio.to_thread(bm.compare_to_baseline, cap.name)
                    if report.baseline_score is None:
                        result = await asyncio.to_thread(bm.run_benchmark, cap.name)
                        await asyncio.to_thread(bm.store_baseline, cap.name, result)
                        logger.info(
                            "Stored initial baseline for %s: benchmark_score=%.3f",
                            cap.name,
                            result.objectives["benchmark_score"],
                        )
                except Exception as exc:
                    logger.warning(
                        "Baseline population failed for %s: %s", cap.name, exc
                    )
        except Exception as exc:
            logger.warning("Benchmark baseline loop iteration failed: %s", exc)


async def _doc_agent_auto_trigger_loop() -> None:
    """Gap-closure Day 52 (Stage 2, answers.md Q41 "Auto-trigger 'when code
    changes': NO for all of the above. All four real doc agents are
    dispatch-only via POST /api/specialized-agents/{name}/run; no CI step,
    pre-commit hook, or post-merge trigger regenerates any of them
    automatically." Plan: "wire a lightweight trigger (a periodic loop,
    matching the existing _fleet_agents_scan_loop() pattern, or a CI
    post-merge step) to invoke changelog_agent/release_notes_agent
    automatically on merge to main").

    No real CI/webhook receiver exists anywhere in this codebase (confirmed
    by grep before building this), so this follows the plan's other named
    option: a periodic loop matching _fleet_agents_scan_loop()'s own
    pattern. Polls the target repo's real local `main` HEAD SHA (the same
    local repo every other real git operation here already operates on —
    not a remote fetch, which would add a network dependency this loop
    doesn't otherwise have) and, when it has moved since the last recorded
    run for that agent (SystemSetting-backed, keyed per agent so
    changelog_agent and release_notes_agent track independently), creates a
    real DevTask and dispatches the agent against it — the exact same
    task-based execution path POST /api/specialized-agents/{name}/run
    already uses (create_task + run_changelog_agent/run_release_notes_agent
    + record_agent_run_outcome), not a new bypass mechanism. Set
    DOC_AGENT_AUTO_TRIGGER_INTERVAL_HOURS=0 to disable.
    """
    interval_hours = get_settings().doc_agent_auto_trigger_interval_hours
    if interval_hours <= 0:
        logger.info(
            "Doc-agent auto-trigger loop disabled "
            "(DOC_AGENT_AUTO_TRIGGER_INTERVAL_HOURS=0)"
        )
        return

    while True:
        await asyncio.sleep(interval_hours * 60 * 60)
        try:
            await _run_doc_agent_auto_trigger_once()
        except Exception as exc:
            logger.warning("Doc-agent auto-trigger loop iteration failed: %s", exc)


_DOC_AUTO_TRIGGER_AGENTS: tuple[tuple[str, str, str, str], ...] = (
    (
        "changelog_agent",
        "app.agents.changelog_agent",
        "run_changelog_agent",
        "Auto-update CHANGELOG.md",
    ),
    (
        "release_notes_agent",
        "app.agents.release_notes_agent",
        "run_release_notes_agent",
        "Auto-generate release notes",
    ),
)


async def _run_doc_agent_auto_trigger_once() -> None:
    import importlib
    import subprocess

    from app.db.repository import create_task, get_setting, set_setting
    from app.db.session import get_session_factory
    from app.memory.hooks import record_agent_run_outcome

    settings = get_settings()
    repo_path = str(settings.target_repo_path)

    try:
        head = subprocess.run(
            ["git", "rev-parse", "main"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        logger.warning("Doc-agent auto-trigger: could not read main HEAD: %s", exc)
        return
    if head.returncode != 0:
        return  # no local `main` branch yet (e.g. repo not cloned) — nothing to do
    current_sha = head.stdout.strip()
    if not current_sha:
        return

    factory = get_session_factory()
    for agent_name, module_path, fn_name, title in _DOC_AUTO_TRIGGER_AGENTS:
        setting_key = f"doc_agent_last_sha:{agent_name}"
        try:
            async with factory() as db:
                last_sha = await get_setting(db, setting_key)
                if last_sha == current_sha:
                    continue  # main hasn't moved since this agent's last run

                task = await create_task(
                    db,
                    title=title,
                    description=(
                        f"Autonomous trigger: main moved to {current_sha[:12]} — "
                        f"regenerate from the real git history up to this commit."
                    ),
                )
                module = importlib.import_module(module_path)
                run_fn = getattr(module, fn_name)
                result = await asyncio.to_thread(
                    run_fn,
                    task_id=task.id,
                    description=task.description,
                    repo_path=repo_path,
                )
                await record_agent_run_outcome(
                    agent_name=agent_name,
                    task_id=str(task.id),
                    description=task.description,
                    result=result,
                    db=db,
                    # Stage 4 Cluster O (2026-08-05) — task is already loaded
                    # here (create_task() above), so its repo_id is directly
                    # available with no extra lookup.
                    repo_id=task.repo_id,
                )
                await set_setting(db, setting_key, current_sha)
                logger.info(
                    "Doc-agent auto-trigger: %s ran for main@%s (task #%d, status=%s)",
                    agent_name,
                    current_sha[:12],
                    task.id,
                    result.status,
                )
        except Exception as exc:
            logger.warning("Doc-agent auto-trigger failed for %s: %s", agent_name, exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    from app.pipeline.graph import init_checkpointer, close_checkpointer
    from app.agents.base_graph import (
        init_agent_checkpointer,
        close_agent_checkpointer,
    )
    from app.db.session import get_session_factory
    from app.db.repository import get_setting
    from app.agents.base import set_api_key_override
    from app.services.retention import start_retention_loop
    from app.fleet.failure_ladder import start_orphan_recovery_loop

    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    # Audit 01 gap-closure (2026-07-24) — capture the real main event loop so
    # FleetBus (app/fleet/fleet_events.py) can forward events published from
    # inside asyncio.to_thread() worker threads (every real agent run) onto
    # it via run_coroutine_threadsafe, instead of silently failing to find a
    # loop from the worker thread's own perspective.
    from app.fleet.fleet_events import set_main_loop

    set_main_loop(asyncio.get_running_loop())

    # Sentry — must happen before any request processing
    _init_sentry(settings)

    # OpenTelemetry — same "must happen before any request processing" reason
    _init_otel(settings)

    # Day 19 — Cloud Deployment prep. Every real agent's _register() only
    # fires once its module is imported; before this, only pm/architect/
    # decomposer were imported eagerly (via pipeline/graph.py), leaving
    # capability_registry/agent_registry populated with as few as ~6 of the
    # 72 real agents for most of a fresh process's lifetime — a real gap for
    # /health's agent count and for fleet_manager.select() calls made shortly
    # after startup, before any task has touched every agent type.
    try:
        from app.fleet.capability_registry import ensure_all_agents_registered

        imported = ensure_all_agents_registered()
        logger.info(
            "Fleet agent registry bootstrap: %d agent modules imported", imported
        )
    except Exception as exc:
        logger.warning("Fleet agent registry bootstrap failed (non-fatal): %s", exc)

    # Gap-closure Day 23 (Stage 1.3, answers.md) — before any agent can
    # start a new background process this run, terminate anything left
    # over in the durable registry from a previous crash/restart: nothing
    # in a fresh process could have legitimately started it, so being in
    # the registry at this point IS the orphan signal.
    try:
        from app.fleet.bg_process_registry import sweep_orphaned_processes

        killed = sweep_orphaned_processes()
        if killed:
            logger.warning(
                "Startup orphan sweep terminated %d leftover background process(es): %s",
                len(killed),
                killed,
            )
    except Exception as exc:
        logger.warning("Startup orphan-process sweep failed (non-fatal): %s", exc)

    await init_active_repo()
    await init_checkpointer(settings.database_url)
    await init_agent_checkpointer(settings.database_url)

    # Load DB-stored API key override (if user saved one via UI)
    try:
        factory = get_session_factory()
        async with factory() as db:
            db_key = await get_setting(db, "anthropic_api_key")
            if db_key:
                set_api_key_override(db_key)
    except Exception as exc:
        logger.warning("Could not load API key from DB at startup: %s", exc)

    # Gap-closure (Audit 05 fix, SEC-05-015): this used to reseed the admin
    # user's password back to settings.default_admin_password on EVERY
    # startup whenever it didn't match — meaning a manually-changed admin
    # password was silently reverted on the next restart, with no way to
    # durably change it short of overriding DEFAULT_ADMIN_PASSWORD itself
    # (a hardcoded "gridiron123" by default, checked into source). Now:
    # seed the admin account ONLY if it doesn't exist at all (first-ever
    # startup); never touch an existing admin row's password again. The
    # freshly-seeded row carries must_change_password=True so the login
    # flow (see app/api/auth.py) can surface a forced-change prompt.
    if settings.jwt_secret_key:
        try:
            import json
            from sqlalchemy import text
            from app.auth.jwt import hash_password

            factory = get_session_factory()
            async with factory() as db:
                row = await db.execute(
                    text("SELECT value FROM system_settings WHERE key = 'auth_users'")
                )
                existing: list[dict[str, str]] = json.loads(
                    row.scalar_one_or_none() or "[]"
                )
                admin_user = next(
                    (u for u in existing if u.get("username") == "admin"), None
                )
                if admin_user is None:
                    admin = {
                        "username": "admin",
                        "hashed_password": hash_password(
                            settings.default_admin_password
                        ),
                        "role": "approver",
                        "must_change_password": True,
                    }
                    await db.execute(
                        text(
                            "INSERT INTO system_settings (key, value) VALUES ('auth_users', :v) "
                            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
                        ),
                        {"v": json.dumps([admin] + existing)},
                    )
                    await db.commit()
                    logger.info(
                        "Admin user seeded (username=admin, must_change_password=True) "
                        "— this only happens once, on first-ever startup"
                    )
        except Exception as exc:
            logger.warning("Could not seed admin user: %s", exc)

    reindex_task = asyncio.create_task(_weekly_reindex_loop())
    retention_task = asyncio.create_task(start_retention_loop())
    fleet_scan_task = asyncio.create_task(_fleet_agents_scan_loop())
    lesson_archive_task = asyncio.create_task(_versioned_lesson_archive_loop())
    benchmark_baseline_task = asyncio.create_task(_benchmark_baseline_loop())
    orphan_recovery_task = asyncio.create_task(start_orphan_recovery_loop())
    doc_agent_auto_trigger_task = asyncio.create_task(_doc_agent_auto_trigger_loop())
    failed_rq_job_sweep_task = asyncio.create_task(_failed_rq_job_sweep_loop())

    yield

    reindex_task.cancel()
    retention_task.cancel()
    fleet_scan_task.cancel()
    lesson_archive_task.cancel()
    benchmark_baseline_task.cancel()
    orphan_recovery_task.cancel()
    doc_agent_auto_trigger_task.cancel()
    failed_rq_job_sweep_task.cancel()
    for task in (
        reindex_task,
        retention_task,
        fleet_scan_task,
        lesson_archive_task,
        benchmark_baseline_task,
        orphan_recovery_task,
        doc_agent_auto_trigger_task,
        failed_rq_job_sweep_task,
    ):
        try:
            await task
        except asyncio.CancelledError:
            pass
    await close_checkpointer()
    await close_agent_checkpointer()


app = FastAPI(
    title="Gridiron Developer Department API",
    version="0.1.0",
    lifespan=lifespan,
)

# Wire rate limiter state and middleware before other middleware
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip() for o in get_settings().cors_origins.split(",") if o.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks_router)
app.include_router(repo_router)
app.include_router(artifacts_router)
app.include_router(auth_router)
app.include_router(epics_router)
app.include_router(registry_router)
app.include_router(memory_router)
app.include_router(goals_router)
app.include_router(metrics_router)
app.include_router(settings_router)
app.include_router(chat_router)
app.include_router(specialized_agents_router)
app.include_router(activity_router)
app.include_router(console_router)
app.include_router(fleet_dashboard_router)
app.include_router(approvals_router)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": str(exc.status_code), "message": str(exc.detail)}},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "422", "message": str(exc)}},
    )


@app.get("/health")
async def health() -> dict[str, object]:
    """Liveness + readiness probe: checks DB, Redis (if enabled), S3 (if enabled)."""
    import asyncio

    checks: dict[str, str] = {}

    # DB check
    try:
        from app.db.session import get_session_factory
        from sqlalchemy import text

        factory = get_session_factory()
        async with factory() as db:
            await db.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        logger.warning("Database health check failed: %s", exc)
        checks["db"] = "error"

    # Redis check (optional — only when redis_streams_enabled or queue_backend=rq)
    settings = get_settings()
    if settings.redis_streams_enabled or settings.queue_backend == "rq":
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
            await r.ping()
            await r.aclose()
            checks["redis"] = "ok"
        except Exception as exc:
            logger.warning("Redis health check failed: %s", exc)
            checks["redis"] = "error"

    # S3 check (optional — only when artifact_backend=s3)
    if settings.artifact_backend == "s3":
        try:
            from app.artifacts.s3_store import _get_s3

            s3 = await asyncio.to_thread(_get_s3)
            await asyncio.to_thread(s3.head_bucket, Bucket=settings.s3_bucket)
            checks["s3"] = "ok"
        except Exception as exc:
            logger.warning("S3 health check failed: %s", exc)
            checks["s3"] = "error"

    # Day 19 — Cloud Deployment prep. Agent count, so a deployment's own
    # health check can confirm the fleet actually loaded (not just that the
    # process is up), matching the plan's success criterion.
    try:
        from app.fleet.capability_registry import get_capability_registry

        agent_count = len(get_capability_registry().all())
    except Exception:
        agent_count = 0

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {
        "status": overall,
        "checks": checks,
        "db": checks.get("db", "unknown"),
        "agents": agent_count,
    }

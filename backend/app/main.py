from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.tasks import router as tasks_router
from app.api.repo import router as repo_router, init_active_repo, get_active_repo_path
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

logger = logging.getLogger(__name__)

# Rate limiter — keyed by remote IP; enabled only when RATE_LIMIT_ENABLED=true
limiter = Limiter(key_func=get_remote_address, enabled=get_settings().rate_limit_enabled)


def _init_sentry(settings: "Settings") -> None:  # type: ignore[name-defined]  # noqa: F821
    """Initialise Sentry SDK if SENTRY_DSN is configured. No-op otherwise."""
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            integrations=[FastApiIntegration(), SqlalchemyIntegration()],
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


async def _weekly_reindex_loop(repo_path: str) -> None:
    """Reindex the target repo every 7 days so context stays fresh."""
    from app.repo_tools.scanner import index_repository
    from app.repo_tools.context_builder import invalidate_context_cache

    _SEVEN_DAYS = 7 * 24 * 60 * 60
    while True:
        await asyncio.sleep(_SEVEN_DAYS)
        try:
            index_repository(repo_path)
            invalidate_context_cache(repo_path)
            logger.info("Weekly auto-reindex complete for %s", repo_path)
        except Exception as exc:
            logger.warning("Weekly reindex failed: %s", exc)


async def _fleet_agents_scan_loop() -> None:
    """Day 9 — periodic SCAN phase for the 5 fleet self-improvement agents.

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
        ("agent_performance_reviewer", "app.agents.agent_performance_reviewer", "run_agent_performance_reviewer_scan"),
        ("agent_debugger", "app.agents.agent_debugger", "run_agent_debugger_scan"),
        ("agent_advisor", "app.agents.agent_advisor", "run_agent_advisor_scan"),
        ("knowledge_curator", "app.agents.knowledge_curator", "run_knowledge_curator_scan"),
        ("quality_auditor", "app.agents.quality_auditor", "run_quality_auditor_scan"),
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
            archived = await asyncio.to_thread(get_versioned_memory_store().archive_expired)
            if archived:
                logger.info("Versioned lesson archive: %d row(s) archived", archived)
        except Exception as exc:
            logger.warning("Versioned lesson archive loop failed: %s", exc)


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
        logger.info("Benchmark baseline loop disabled (BENCHMARK_BASELINE_INTERVAL_HOURS=0)")
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
                            cap.name, result.objectives["benchmark_score"],
                        )
                except Exception as exc:
                    logger.warning("Baseline population failed for %s: %s", cap.name, exc)
        except Exception as exc:
            logger.warning("Benchmark baseline loop iteration failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    from app.pipeline.graph import init_checkpointer, close_checkpointer
    from app.db.session import get_session_factory
    from app.db.repository import get_setting
    from app.agents.base import set_api_key_override
    from app.services.retention import start_retention_loop

    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    # Sentry — must happen before any request processing
    _init_sentry(settings)

    await init_active_repo()
    await init_checkpointer(settings.database_url)

    # Load DB-stored API key override (if user saved one via UI)
    try:
        factory = get_session_factory()
        async with factory() as db:
            db_key = await get_setting(db, "anthropic_api_key")
            if db_key:
                set_api_key_override(db_key)
    except Exception as exc:
        logger.warning("Could not load API key from DB at startup: %s", exc)

    # Ensure admin user always exists with the correct password on every startup
    if settings.jwt_secret_key:
        try:
            import json
            from sqlalchemy import text
            from app.auth.jwt import hash_password, verify_password
            factory = get_session_factory()
            async with factory() as db:
                row = await db.execute(
                    text("SELECT value FROM system_settings WHERE key = 'auth_users'")
                )
                existing: list[dict[str, str]] = json.loads(row.scalar_one_or_none() or "[]")
                admin_user = next((u for u in existing if u.get("username") == "admin"), None)
                # Re-seed if admin is missing OR if their password no longer matches
                if admin_user is None or not verify_password(
                    settings.default_admin_password, admin_user.get("hashed_password", "")
                ):
                    non_admin = [u for u in existing if u.get("username") != "admin"]
                    admin = {
                        "username": "admin",
                        "hashed_password": hash_password(settings.default_admin_password),
                        "role": "approver",
                    }
                    await db.execute(
                        text(
                            "INSERT INTO system_settings (key, value) VALUES ('auth_users', :v) "
                            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
                        ),
                        {"v": json.dumps([admin] + non_admin)},
                    )
                    await db.commit()
                    logger.info("Admin user synced (username=admin)")
        except Exception as exc:
            logger.warning("Could not sync admin user: %s", exc)

    reindex_task = asyncio.create_task(_weekly_reindex_loop(get_active_repo_path()))
    retention_task = asyncio.create_task(start_retention_loop())
    fleet_scan_task = asyncio.create_task(_fleet_agents_scan_loop())
    lesson_archive_task = asyncio.create_task(_versioned_lesson_archive_loop())
    benchmark_baseline_task = asyncio.create_task(_benchmark_baseline_loop())

    yield

    reindex_task.cancel()
    retention_task.cancel()
    fleet_scan_task.cancel()
    lesson_archive_task.cancel()
    benchmark_baseline_task.cancel()
    for task in (reindex_task, retention_task, fleet_scan_task, lesson_archive_task, benchmark_baseline_task):
        try:
            await task
        except asyncio.CancelledError:
            pass
    await close_checkpointer()


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
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
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
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": str(exc.status_code), "message": str(exc.detail)}},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
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
        checks["db"] = f"error: {exc}"

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
            checks["redis"] = f"error: {exc}"

    # S3 check (optional — only when artifact_backend=s3)
    if settings.artifact_backend == "s3":
        try:
            from app.artifacts.s3_store import _get_s3
            s3 = await asyncio.to_thread(_get_s3)
            await asyncio.to_thread(
                s3.head_bucket, Bucket=settings.s3_bucket
            )
            checks["s3"] = "ok"
        except Exception as exc:
            checks["s3"] = f"error: {exc}"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}

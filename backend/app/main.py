from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.tasks import router as tasks_router
from app.api.repo import router as repo_router, init_active_repo, get_active_repo_path
from app.api.artifacts import router as artifacts_router
from app.api.epics import router as epics_router
from app.api.registry import router as registry_router
from app.api.memory import router as memory_router
from app.api.goals import router as goals_router
from app.api.metrics import router as metrics_router
from app.api.settings import router as settings_router
from app.api.chat import router as chat_router
from app.api.specialized_agents import router as specialized_agents_router

from app.config import get_settings

logger = logging.getLogger(__name__)


def _init_sentry(settings: "Settings") -> None:  # type: ignore[name-defined]
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

    reindex_task = asyncio.create_task(_weekly_reindex_loop(get_active_repo_path()))
    retention_task = asyncio.create_task(start_retention_loop())

    yield

    reindex_task.cancel()
    retention_task.cancel()
    for task in (reindex_task, retention_task):
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks_router)
app.include_router(repo_router)
app.include_router(artifacts_router)
app.include_router(epics_router)
app.include_router(registry_router)
app.include_router(memory_router)
app.include_router(goals_router)
app.include_router(metrics_router)
app.include_router(settings_router)
app.include_router(chat_router)
app.include_router(specialized_agents_router)


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
async def health() -> dict[str, str]:
    return {"status": "ok"}

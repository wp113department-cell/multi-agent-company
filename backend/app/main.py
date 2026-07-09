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
from app.api.repo import router as repo_router
from app.api.artifacts import router as artifacts_router
from app.api.epics import router as epics_router
from app.api.registry import router as registry_router
from app.api.memory import router as memory_router
from app.api.goals import router as goals_router
from app.api.metrics import router as metrics_router

from app.config import get_settings

logger = logging.getLogger(__name__)


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
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    reindex_task = asyncio.create_task(_weekly_reindex_loop(settings.target_repo_path))
    yield
    reindex_task.cancel()
    try:
        await reindex_task
    except asyncio.CancelledError:
        pass


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

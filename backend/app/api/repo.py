from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(prefix="/api/repo", tags=["repo"])

_last_reindex: dict[str, object] = {"indexed_at": None, "file_count": 0}


async def _do_reindex() -> None:
    from app.repo_tools.scanner import index_repository
    from datetime import datetime, timezone

    settings = get_settings()
    idx = index_repository(settings.target_repo_path)
    _last_reindex["indexed_at"] = datetime.now(timezone.utc).isoformat()
    _last_reindex["file_count"] = len(idx.files)


@router.post("/reindex")
async def trigger_reindex(background_tasks: BackgroundTasks) -> dict[str, object]:
    """Trigger a full repository reindex (fire-and-forget)."""
    background_tasks.add_task(_do_reindex)
    return {"triggered": True}


@router.get("/reindex")
async def reindex_status() -> dict[str, object]:
    return {
        "last_indexed_at": _last_reindex["indexed_at"],
        "file_count": _last_reindex["file_count"],
    }


@router.get("/context")
async def get_context(task_description: str) -> dict[str, object]:
    """Build and return context for a task description."""
    from app.repo_tools.scanner import index_repository
    from app.repo_tools.context_builder import build_context

    settings = get_settings()
    idx = index_repository(settings.target_repo_path)
    ctx = build_context(task_description, idx)
    return {
        "relevant_files": ctx.relevant_files,
        "dependency_chain": ctx.dependency_chain,
        "related_symbols": ctx.related_symbols,
        "summary": ctx.summary,
    }

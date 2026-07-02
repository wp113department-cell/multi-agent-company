from fastapi import APIRouter, BackgroundTasks
from app.config import get_settings

router = APIRouter(prefix="/api/repo", tags=["repo"])

# In-process state for incremental re-index
_indexed_at: str | None = None
_file_count: int = 0
_known_hashes: dict[str, str] = {}  # {rel_path: content_hash}


async def _do_reindex() -> None:
    global _indexed_at, _file_count, _known_hashes

    from app.repo_tools.scanner import index_repository
    from datetime import datetime, timezone
    from app.repo_tools.context_builder import invalidate_context_cache

    settings = get_settings()

    # Full walk — hash comparison in scanner skips re-parsing unchanged files
    full_index = index_repository(
        settings.target_repo_path,
        known_hashes=_known_hashes if _known_hashes else None,
    )

    _known_hashes = {rel: fi.content_hash for rel, fi in full_index.files.items()}
    _indexed_at = datetime.now(timezone.utc).isoformat()
    _file_count = len(full_index.files)

    # Context cache is stale after a re-index
    invalidate_context_cache(settings.target_repo_path)


@router.post("/reindex")
async def trigger_reindex(background_tasks: BackgroundTasks) -> dict[str, object]:
    """Trigger a full repository reindex (fire-and-forget, incremental after first run)."""
    background_tasks.add_task(_do_reindex)
    return {"triggered": True}


@router.get("/reindex")
async def reindex_status() -> dict[str, object]:
    return {
        "lastIndexedAt": _indexed_at,
        "fileCount": _file_count,
    }


@router.get("/context")
async def get_context(task_description: str) -> dict[str, object]:
    """Build and return context for a task description."""
    from app.repo_tools.scanner import index_repository
    from app.repo_tools.context_builder import build_context

    settings = get_settings()
    idx = index_repository(
        settings.target_repo_path,
        known_hashes=_known_hashes if _known_hashes else None,
    )
    ctx = build_context(task_description, idx)
    return {
        "relevantFiles": ctx.relevant_files,
        "dependencyChain": ctx.dependency_chain,
        "relatedSymbols": ctx.related_symbols,
        "summary": ctx.summary,
    }

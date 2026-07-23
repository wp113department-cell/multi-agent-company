"""Repository management API.

GET    /api/repo            — list all cloned repos + active repo
POST   /api/repo/clone      — clone a GitHub repo and auto-activate it
POST   /api/repo/{id}/activate — switch active repo
DELETE /api/repo/{id}       — remove a repo record from the database
GET    /api/repo/reindex    — reindex status
POST   /api/repo/reindex    — trigger reindex
GET    /api/repo/context    — build context for a task description
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Repo
from app.db.session import get_async_session, get_db

if TYPE_CHECKING:
    # Deferred at runtime like every other scanner import in this file —
    # app.repo_tools.scanner loads tree-sitter grammars at module import
    # time, so real imports of it stay lazy/in-function; this is type-only.
    from app.repo_tools.scanner import RepoIndex

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/repo", tags=["repo"])

# ---------------------------------------------------------------------------
# Active-repo state (module-level, updated by clone/activate + startup init)
# ---------------------------------------------------------------------------

_active_repo_path: str | None = None

# In-process state for incremental re-index
_indexed_at: str | None = None
_file_count: int = 0
_known_hashes: dict[str, str] = {}
# Gap-closure (2026-07-23): the full, merged RepoIndex from the last reindex.
# Previously _do_reindex()/get_context() only cached _known_hashes and fed
# it straight back into index_repository() as the next call's skip-filter —
# but index_repository() with known_hashes set returns ONLY the files that
# changed (unchanged ones are skipped and never added to the result), and
# scanner.merge_indexes() (which exists specifically to reunite them) had
# zero real callers anywhere. After the very first reindex, _known_hashes/
# _file_count and every /api/repo/context call silently degraded to only
# ever seeing recently-changed files — found while wiring the new repo-
# intelligence persistence layer, which would otherwise have persisted the
# same broken partial data.
_cached_index: RepoIndex | None = None


def get_active_repo_path() -> str:
    """Return the currently active repo path, falling back to TARGET_REPO_PATH env var."""
    return _active_repo_path or get_settings().target_repo_path


async def init_active_repo() -> None:
    """Called at startup — loads the active repo from the DB into module state."""
    global _active_repo_path
    try:
        async with get_async_session() as db:
            result = await db.execute(
                select(Repo).where(
                    Repo.is_active == True, Repo.status == "ready"  # noqa: E712
                )
            )
            repo = result.scalar_one_or_none()
            if repo:
                _active_repo_path = repo.local_path
                logger.info("Active repo loaded from DB: %s", repo.local_path)
    except Exception as exc:
        logger.warning("Could not load active repo from DB at startup: %s", exc)


# ---------------------------------------------------------------------------
# Background clone task
# ---------------------------------------------------------------------------


async def _clone_and_activate(
    repo_id: int,
    github_url: str,
    local_path: str,
    branch: str | None = None,
    token: str | None = None,
) -> None:
    global _active_repo_path
    async with get_async_session() as db:
        try:
            target = Path(local_path)
            # Build the clone URL — inject token for private repos
            clone_url = github_url
            if token:
                # https://TOKEN@github.com/...
                clone_url = github_url.replace("https://", f"https://{token}@", 1)

            is_git_repo = (target / ".git").exists()

            if target.exists() and is_git_repo:
                # Already a cloned repo — pull latest
                proc = await asyncio.create_subprocess_exec(
                    "git",
                    "pull",
                    cwd=local_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            else:
                # Directory doesn't exist or exists but isn't a git repo — clone fresh
                target.mkdir(parents=True, exist_ok=True)
                cmd = ["git", "clone"]
                if branch:
                    cmd += ["-b", branch]
                cmd += [clone_url, local_path]
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            _, stderr_bytes = await proc.communicate()

            if proc.returncode != 0:
                error_msg = stderr_bytes.decode(errors="replace")[:2000]
                await db.execute(
                    update(Repo)
                    .where(Repo.id == repo_id)
                    .values(status="error", error_msg=error_msg)
                )
                await db.commit()
                logger.error("Clone failed for %s: %s", github_url, error_msg)
                return

            # Deactivate any previously active repo
            await db.execute(
                update(Repo)
                .where(Repo.is_active == True)  # noqa: E712
                .values(is_active=False)
            )
            # Mark this repo as ready and active
            await db.execute(
                update(Repo)
                .where(Repo.id == repo_id)
                .values(
                    status="ready",
                    is_active=True,
                    cloned_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
            await db.commit()

            _active_repo_path = local_path
            logger.info("Repo cloned and activated: %s → %s", github_url, local_path)

            # Invalidate context cache for old repo, reindex will happen on demand
            try:
                from app.repo_tools.context_builder import invalidate_context_cache

                invalidate_context_cache(local_path)
            except Exception:
                pass

        except Exception as exc:
            logger.exception("Unexpected error cloning %s", github_url)
            try:
                await db.execute(
                    update(Repo)
                    .where(Repo.id == repo_id)
                    .values(status="error", error_msg=str(exc)[:2000])
                )
                await db.commit()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class CloneRequest(BaseModel):
    github_url: str
    dest_path: str | None = None  # optional; auto-computed if omitted
    branch: str | None = None  # optional branch to check out
    token: str | None = None  # optional GitHub PAT for private repos


class RepoResponse(BaseModel):
    id: int
    githubUrl: str
    name: str
    localPath: str
    status: str
    errorMsg: str | None
    isActive: bool
    clonedAt: str | None
    createdAt: str


def _repo_to_dict(r: Repo) -> dict[str, Any]:
    return {
        "id": r.id,
        "githubUrl": r.github_url,
        "name": r.name,
        "localPath": r.local_path,
        "status": r.status,
        "errorMsg": r.error_msg,
        "isActive": r.is_active,
        "clonedAt": r.cloned_at.isoformat() if r.cloned_at else None,
        "createdAt": r.created_at.isoformat(),
    }


def _extract_name(url: str) -> str:
    name = url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or "repo"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def list_repos(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """List all cloned repos and identify the active one."""
    result = await db.execute(select(Repo).order_by(Repo.created_at.desc()))
    repos = result.scalars().all()
    return {
        "repos": [_repo_to_dict(r) for r in repos],
        "activeRepoPath": get_active_repo_path(),
    }


@router.post("/clone")
async def clone_repo(
    body: CloneRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Clone a GitHub repo and auto-activate it as the target for all agents."""
    url = body.github_url.strip()
    if not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Only https:// URLs are supported.")

    settings = get_settings()
    name = _extract_name(url)
    local_path = (
        body.dest_path.strip()
        if body.dest_path and body.dest_path.strip()
        else str(Path(settings.repos_dir) / name)
    )
    branch = body.branch.strip() if body.branch and body.branch.strip() else None
    token = body.token.strip() if body.token and body.token.strip() else None

    # If already in DB, return existing record and re-trigger clone (pull)
    existing = await db.execute(select(Repo).where(Repo.github_url == url))
    existing_repo = existing.scalar_one_or_none()

    if existing_repo:
        await db.execute(
            update(Repo)
            .where(Repo.id == existing_repo.id)
            .values(status="cloning", error_msg=None)
        )
        await db.commit()
        repo_id = existing_repo.id
    else:
        new_repo = Repo(
            github_url=url,
            name=name,
            local_path=local_path,
            status="cloning",
        )
        db.add(new_repo)
        await db.commit()
        await db.refresh(new_repo)
        repo_id = new_repo.id

    background_tasks.add_task(
        _clone_and_activate, repo_id, url, local_path, branch, token
    )

    result = await db.execute(select(Repo).where(Repo.id == repo_id))
    repo = result.scalar_one()
    return _repo_to_dict(repo)


@router.delete("/{repo_id}")
async def delete_repo(
    repo_id: int, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Remove a repo record from the database. Local files are left untouched."""
    global _active_repo_path
    result = await db.execute(select(Repo).where(Repo.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repo not found.")
    if repo.is_active:
        _active_repo_path = None
    await db.delete(repo)
    await db.commit()
    return {"deleted": True, "id": repo_id}


@router.post("/{repo_id}/activate")
async def activate_repo(
    repo_id: int, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Switch the active repo without re-cloning."""
    global _active_repo_path
    result = await db.execute(select(Repo).where(Repo.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repo not found.")
    if repo.status != "ready":
        raise HTTPException(
            status_code=400, detail="Repo is not ready — wait for clone to finish."
        )

    await db.execute(
        update(Repo).where(Repo.is_active == True).values(is_active=False)  # noqa: E712
    )
    await db.execute(update(Repo).where(Repo.id == repo_id).values(is_active=True))
    await db.commit()

    _active_repo_path = repo.local_path
    return _repo_to_dict(repo)


# ---------------------------------------------------------------------------
# Existing reindex + context endpoints (unchanged behaviour, uses active repo)
# ---------------------------------------------------------------------------


async def _do_reindex() -> None:
    global _indexed_at, _file_count, _known_hashes, _cached_index

    from app.repo_tools.scanner import index_repository, merge_indexes
    from app.repo_tools.context_builder import invalidate_context_cache

    repo_path = get_active_repo_path()
    partial_index = index_repository(
        repo_path, known_hashes=_known_hashes if _known_hashes else None
    )
    # Gap-closure (2026-07-23): index_repository() with known_hashes set
    # returns ONLY the files that changed — scanner.merge_indexes() exists
    # specifically to reunite that partial result with the previous full
    # index, but had zero real callers until now. See _cached_index's
    # declaration comment above for the bug this was silently causing.
    full_index = (
        merge_indexes(_cached_index, partial_index)
        if _cached_index is not None
        else partial_index
    )
    _cached_index = full_index
    _known_hashes = {rel: fi.content_hash for rel, fi in full_index.files.items()}
    _indexed_at = datetime.now(timezone.utc).isoformat()
    _file_count = len(full_index.files)
    invalidate_context_cache(repo_path)

    # Gap-closure: persist indexed_files/symbols/call_edges — previously
    # migrated (migration 001) but never actually written anywhere.
    try:
        from app.repo_tools.cross_file_graph import build_cross_file_graph
        from app.repo_tools.persistence import persist_repo_index

        graph_result = build_cross_file_graph(full_index)
        async with get_async_session() as db:
            await persist_repo_index(repo_path, full_index, graph_result, db)
    except Exception:
        logger.exception("Failed to persist repo index for %s", repo_path)


@router.post("/reindex")
async def trigger_reindex(background_tasks: BackgroundTasks) -> dict[str, object]:
    background_tasks.add_task(_do_reindex)
    return {"triggered": True}


@router.get("/reindex")
async def reindex_status() -> dict[str, object]:
    return {"lastIndexedAt": _indexed_at, "fileCount": _file_count}


@router.get("/context")
async def get_context(task_description: str) -> dict[str, object]:
    from app.repo_tools.context_builder import build_context

    repo_path = get_active_repo_path()
    # Gap-closure (2026-07-23): previously re-derived a partial index here
    # via index_repository(repo_path, known_hashes=_known_hashes) — after the
    # first reindex ever ran, that returns ONLY changed files (see
    # _cached_index's declaration comment), silently starving context
    # building of most of the repo on every call. Reuse the maintained full
    # index instead; only fall back to a full scan if nothing has indexed
    # this repo yet.
    if _cached_index is not None:
        idx = _cached_index
    else:
        from app.repo_tools.scanner import index_repository

        idx = index_repository(repo_path)
    ctx = build_context(task_description, idx)
    return {
        "relevantFiles": ctx.relevant_files,
        "dependencyChain": ctx.dependency_chain,
        "relatedSymbols": ctx.related_symbols,
        "summary": ctx.summary,
    }

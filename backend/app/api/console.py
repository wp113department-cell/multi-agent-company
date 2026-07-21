"""Repo Console API — P3 (local workspace + git operations).

POST /api/console/workspace/browse  — list directory
POST /api/console/repos/clone       — git clone into local folder
GET  /api/console/repos/{rpath}/status — git status
...

Each "repo" is identified by a URL-encoded path (rpath path parameter accepts slashes).
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import git_service, workspace_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/console", tags=["console"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class BrowseRequest(BaseModel):
    path: str


class CloneRequest(BaseModel):
    url: str
    dest_path: str
    branch: str = ""


class AddRequest(BaseModel):
    paths: list[str]


class CommitRequest(BaseModel):
    message: str
    author_name: str = ""
    author_email: str = ""


class PushRequest(BaseModel):
    remote: str = "origin"
    branch: str = ""


class CheckoutRequest(BaseModel):
    branch: str
    create: bool = False


class MkdirRequest(BaseModel):
    path: str  # absolute path inside workspace


class ClonePrivateRequest(BaseModel):
    url: str
    dest_path: str
    token: str  # GitHub PAT or other HTTPS token
    branch: str = ""


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _decode_path(encoded: str) -> str:
    """URL-decode the repo path and validate it's inside the workspace.

    When the path starts with a letter (no leading slash), it was captured by
    {rpath:path} which strips the leading '/'. We restore it so absolute paths work.
    """
    path = unquote(encoded)
    # Restore leading slash stripped by {rpath:path} routing
    if path and not path.startswith("/"):
        path = "/" + path
    try:
        workspace_service.assert_in_workspace(path)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return path


# ---------------------------------------------------------------------------
# Workspace endpoints
# ---------------------------------------------------------------------------


@router.post("/workspace/browse")
async def browse_workspace(req: BrowseRequest) -> dict[str, Any]:
    """List directory contents inside the allowed workspace."""
    try:
        entries = workspace_service.list_directory(req.path)
        is_git = workspace_service.is_git_repo(req.path)
        return {"ok": True, "path": req.path, "entries": entries, "is_git_repo": is_git}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/workspace/mkdir")
async def make_directory(req: MkdirRequest) -> dict[str, Any]:
    """Create a new directory inside the allowed workspace."""
    import os

    try:
        workspace_service.assert_in_workspace(req.path)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    try:
        os.makedirs(req.path, exist_ok=True)
        return {"ok": True, "path": req.path}
    except OSError as exc:
        raise HTTPException(
            status_code=400, detail=f"Could not create directory: {exc}"
        )


@router.post("/repos/clone-private")
async def clone_private_repo(req: ClonePrivateRequest) -> dict[str, Any]:
    """Clone a private repo using a GitHub Personal Access Token (HTTPS token auth)."""
    try:
        result = await git_service.git_clone_with_token(
            req.url, req.dest_path, req.token, req.branch or None
        )
        if not result["ok"]:
            raise HTTPException(
                status_code=422, detail=result.get("stderr", "git clone failed")
            )
        return {"ok": True, "path": req.dest_path, "stderr": result.get("stderr", "")}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Git repo endpoints
# rpath uses {rpath:path} so it accepts slashes in the URL-encoded path
# ---------------------------------------------------------------------------


@router.post("/repos/clone")
async def clone_repo(req: CloneRequest) -> dict[str, Any]:
    """Clone a remote repo to a local folder in the workspace."""
    try:
        result = await git_service.git_clone(req.url, req.dest_path, req.branch or None)
        if not result["ok"]:
            raise HTTPException(
                status_code=422, detail=result.get("stderr", "git clone failed")
            )
        return {"ok": True, "path": req.dest_path, "stderr": result.get("stderr", "")}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/repos/{rpath:path}/status")
async def repo_status(rpath: str) -> dict[str, Any]:
    path = _decode_path(rpath)
    try:
        return await git_service.git_status(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/repos/{rpath:path}/log")
async def repo_log(rpath: str, limit: int = 20) -> dict[str, Any]:
    path = _decode_path(rpath)
    try:
        return await git_service.git_log(path, limit=min(limit, 100))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/repos/{rpath:path}/diff")
async def repo_diff(rpath: str, staged: bool = False) -> dict[str, Any]:
    path = _decode_path(rpath)
    try:
        return await git_service.git_diff(path, staged=staged)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/repos/{rpath:path}/add")
async def repo_add(rpath: str, req: AddRequest) -> dict[str, Any]:
    path = _decode_path(rpath)
    try:
        return await git_service.git_add(path, req.paths)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/repos/{rpath:path}/commit")
async def repo_commit(rpath: str, req: CommitRequest) -> dict[str, Any]:
    path = _decode_path(rpath)
    try:
        return await git_service.git_commit(
            path, req.message, req.author_name, req.author_email
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/repos/{rpath:path}/push")
async def repo_push(rpath: str, req: PushRequest) -> dict[str, Any]:
    path = _decode_path(rpath)
    try:
        return await git_service.git_push(path, req.remote, req.branch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/repos/{rpath:path}/branches")
async def repo_branches(rpath: str) -> dict[str, Any]:
    path = _decode_path(rpath)
    try:
        return await git_service.git_branch_list(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/repos/{rpath:path}/checkout")
async def repo_checkout(rpath: str, req: CheckoutRequest) -> dict[str, Any]:
    path = _decode_path(rpath)
    try:
        return await git_service.git_checkout(path, req.branch, req.create)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/repos/{rpath:path}/pull")
async def repo_pull(rpath: str, remote: str = "origin") -> dict[str, Any]:
    path = _decode_path(rpath)
    try:
        return await git_service.git_pull(path, remote)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

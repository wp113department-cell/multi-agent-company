"""Isolated workspace for EnhancementRequest APPLY phases (audit 15, 2026-10-06).

Before this, an approved enhancement's agent edited, tested and committed
directly in the live working copy (settings.fleet_self_repo_path) — on the
owner's current branch, next to any uncommitted work of their own. Now each
APPLY phase runs in its own git worktree on a fresh `fleet/enh-<id>` branch
created from the current HEAD:

1. the agent edits, runs the tests and commits inside that worktree;
2. a verified commit is merged back into the live branch with a normal
   `git merge` — git itself refuses if it would touch files with the owner's
   uncommitted changes, and then nothing is forced: the change stays on its
   branch and the request says so;
3. the worktree is removed; the branch is deleted once merged.

The apply functions read their repo through `apply_repo_path()`: inside an
isolated workspace it is the worktree, otherwise the configured repo (so
direct callers and tests keep their previous behaviour).
"""

from __future__ import annotations

import contextvars
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

_current_repo: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fleet_apply_repo", default=None
)


def apply_repo_path() -> str:
    """Where an APPLY phase should read, edit, test and commit."""
    return _current_repo.get() or str(get_settings().fleet_self_repo_path)


@dataclass
class ApplyWorkspace:
    request_id: int
    branch: str
    toplevel: str  # the live repository's root
    worktree: str  # the isolated worktree's root
    repo_path: str  # worktree path matching fleet_self_repo_path's place in the repo
    token: contextvars.Token[str | None] | None = None


@dataclass
class MergeResult:
    merged: bool
    detail: str


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=120
    )


def open_workspace(request_id: int) -> ApplyWorkspace:
    """Create the worktree and its branch (activate() routes the agent to it)."""
    settings = get_settings()
    live_repo = os.path.realpath(str(settings.fleet_self_repo_path))
    top = _git(live_repo, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        raise RuntimeError(
            f"fleet_self_repo_path is not a git repository: {top.stderr.strip()}"
        )
    toplevel = top.stdout.strip()
    rel = os.path.relpath(live_repo, toplevel)
    branch = f"fleet/enh-{request_id}"
    worktree = str(Path(settings.worktrees_dir) / f"fleet-enh-{request_id}")
    if os.path.exists(worktree):
        _git(toplevel, "worktree", "remove", "--force", worktree)
    _git(
        toplevel, "branch", "-D", branch
    )  # stale branch from an earlier failed attempt
    added = _git(toplevel, "worktree", "add", "-b", branch, worktree, "HEAD")
    if added.returncode != 0:
        raise RuntimeError(f"could not create apply worktree: {added.stderr.strip()}")
    repo_path = os.path.normpath(os.path.join(worktree, rel))
    # Tests run with the repo's own virtualenv / node_modules (untracked, so
    # absent from a fresh worktree): link the live ones in.
    for name in (".venv", "node_modules"):
        src = os.path.join(live_repo, name)
        dst = os.path.join(repo_path, name)
        if os.path.isdir(src) and not os.path.exists(dst):
            os.symlink(src, dst)
    return ApplyWorkspace(request_id, branch, toplevel, worktree, repo_path)


def activate(ws: ApplyWorkspace) -> None:
    """Route apply_repo_path() to the worktree. Call it in the caller's own
    context (not inside a worker thread): asyncio.to_thread copies the
    context at call time, so a later to_thread(apply_fn) then sees it."""
    ws.token = _current_repo.set(ws.repo_path)


def deactivate(ws: ApplyWorkspace) -> None:
    if ws.token is not None:
        _current_repo.reset(ws.token)
        ws.token = None


def merge_back(ws: ApplyWorkspace) -> MergeResult:
    """Merge the verified enhancement branch into the live branch."""
    merged = _git(
        ws.toplevel,
        "-c",
        "user.name=Gridiron Fleet",
        "-c",
        "user.email=fleet@gridiron.local",
        "merge",
        "--no-edit",
        "--no-ff",
        "-m",
        f"Merge enhancement #{ws.request_id} ({ws.branch})",
        ws.branch,
    )
    if merged.returncode == 0:
        return MergeResult(True, "merged")
    _git(ws.toplevel, "merge", "--abort")
    detail = (merged.stderr or merged.stdout).strip().splitlines()
    return MergeResult(False, " ".join(detail[-3:])[:500] or "git merge failed")


def close_workspace(ws: ApplyWorkspace, *, keep_branch: bool) -> None:
    """Remove the worktree; delete the branch unless it holds unmerged work."""
    _git(ws.toplevel, "worktree", "remove", "--force", ws.worktree)
    if not keep_branch:
        _git(ws.toplevel, "branch", "-D", ws.branch)

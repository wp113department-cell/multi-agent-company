"""Git worktree isolation — creates per-task isolated worktrees for agent code changes."""

import os
import shutil
import subprocess
from pathlib import Path

from app.config import get_settings


def _run(args: list[str], cwd: str) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git error: {result.stderr.strip()}")
    return result.stdout.strip()


def worktree_path(task_id: int | str, epic_id: str | None = None) -> Path:
    settings = get_settings()
    base = Path(settings.worktrees_dir)
    if epic_id:
        # Per-epic namespace avoids cross-epic path collisions under concurrency
        return base / f"epic-{epic_id}" / f"task-{task_id}"
    return base / f"task-{task_id}"


def _is_registered_worktree(wt_path: Path, base_repo: str) -> bool:
    """Gap-closure (Audit 04 fix, ORCH-04-012): check whether wt_path is
    actually a registered git worktree of base_repo (not just an existing
    directory — could be a stale/partial leftover from a crashed prior run,
    or a directory git itself doesn't know about). `git worktree list
    --porcelain` lists one `worktree <path>` line per real, registered
    worktree; a normalized path comparison confirms membership."""
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=base_repo,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False
        target = str(wt_path.resolve())
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                registered = line[len("worktree ") :].strip()
                try:
                    if str(Path(registered).resolve()) == target:
                        return True
                except OSError:
                    continue
        return False
    except Exception:
        return False


def create_worktree(
    task_id: int | str,
    repo_path: str | None = None,
    epic_id: str | None = None,
) -> Path:
    settings = get_settings()
    base_repo = repo_path or settings.target_repo_path
    wt_path = worktree_path(task_id, epic_id=epic_id)
    branch = f"agent/task-{task_id}"

    os.makedirs(wt_path.parent, exist_ok=True)
    if wt_path.exists():
        # Gap-closure (Audit 04 fix, ORCH-04-012): previously this returned
        # the existing directory unconditionally, trusting it as-is — a
        # restarted task (same task_id, same worktree path) would silently
        # build on top of whatever was left over from a prior failed/crashed
        # attempt instead of a clean checkout, with no signal this happened.
        # Only trust it if git itself still considers it a real, registered
        # worktree; otherwise treat it as stale and rebuild fresh.
        if _is_registered_worktree(wt_path, base_repo):
            return wt_path
        try:
            _run(
                ["git", "worktree", "remove", "--force", str(wt_path)],
                cwd=base_repo,
            )
        except RuntimeError:
            shutil.rmtree(wt_path, ignore_errors=True)
        # A `git worktree add -b <branch>` would fail if <branch> already
        # exists from the stale attempt (branch survives worktree removal) —
        # delete it too, best-effort, before recreating.
        try:
            _run(["git", "branch", "-D", branch], cwd=base_repo)
        except RuntimeError:
            pass

    _run(["git", "worktree", "add", "-b", branch, str(wt_path)], cwd=base_repo)
    return wt_path


def get_diff(task_id: int | str, repo_path: str | None = None) -> str:
    settings = get_settings()
    base_repo = repo_path or settings.target_repo_path
    branch = f"agent/task-{task_id}"
    try:
        return _run(["git", "diff", f"HEAD...{branch}"], cwd=base_repo)
    except RuntimeError:
        return ""


def preserve_worktree(task_id: int | str) -> None:
    """
    Mark the worktree as intentionally preserved — do nothing to the directory.
    Called when a task enters blocked or ready_for_review so the worktree is
    kept for human inspection until the task is completed or torn down explicitly.
    """
    wt_path = worktree_path(task_id)
    if wt_path.exists():
        # Touch a sentinel file so external tooling can detect preserved worktrees
        (wt_path / ".gridiron-preserved").touch()


def remove_worktree(
    task_id: int | str,
    repo_path: str | None = None,
    epic_id: str | None = None,
) -> None:
    settings = get_settings()
    base_repo = repo_path or settings.target_repo_path
    wt_path = worktree_path(task_id, epic_id=epic_id)

    if wt_path.exists():
        # Remove sentinel if present
        sentinel = wt_path / ".gridiron-preserved"
        if sentinel.exists():
            sentinel.unlink()
        try:
            _run(["git", "worktree", "remove", "--force", str(wt_path)], cwd=base_repo)
        except RuntimeError:
            shutil.rmtree(wt_path, ignore_errors=True)

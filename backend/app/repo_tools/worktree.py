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


def worktree_path(task_id: int | str) -> Path:
    settings = get_settings()
    return Path(settings.worktrees_dir) / f"task-{task_id}"


def create_worktree(task_id: int | str, repo_path: str | None = None) -> Path:
    settings = get_settings()
    base_repo = repo_path or settings.target_repo_path
    wt_path = worktree_path(task_id)
    branch = f"agent/task-{task_id}"

    os.makedirs(settings.worktrees_dir, exist_ok=True)
    if wt_path.exists():
        return wt_path

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


def remove_worktree(task_id: int | str, repo_path: str | None = None) -> None:
    settings = get_settings()
    base_repo = repo_path or settings.target_repo_path
    wt_path = worktree_path(task_id)

    if wt_path.exists():
        # Remove sentinel if present
        sentinel = wt_path / ".gridiron-preserved"
        if sentinel.exists():
            sentinel.unlink()
        try:
            _run(["git", "worktree", "remove", "--force", str(wt_path)], cwd=base_repo)
        except RuntimeError:
            shutil.rmtree(wt_path, ignore_errors=True)

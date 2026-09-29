"""Production audit 2026-09-29 — recreating a task worktree after a reject or a
reboot. Reproduced before the fix: `git worktree add -b agent/task-N` failed
with "a branch named 'agent/task-N' already exists" whenever the branch
survived without its directory, so the task ended "blocked". Real git, no mocks.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import reset_settings_cache
from app.repo_tools.worktree import create_worktree, remove_worktree


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=a@b", "-c", "user.name=a", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("WORKTREES_DIR", str(tmp_path / "worktrees"))
    reset_settings_cache()
    base = tmp_path / "repo"
    base.mkdir()
    (base / "a.py").write_text("x = 1\n")
    _git(base, "init", "-q")
    _git(base, "add", ".")
    _git(base, "commit", "-qm", "init")
    yield base
    reset_settings_cache()


def _commit_in(wt: Path, name: str) -> str:
    (wt / name).write_text("y = 2\n")
    _git(wt, "add", name)
    _git(wt, "commit", "-qm", f"agent work {name}")
    return _git(wt, "rev-parse", "HEAD").strip()


def test_rerun_after_reject_recreates_worktree(repo: Path) -> None:
    wt = create_worktree(9101, str(repo))
    old_sha = _commit_in(wt, "rejected.py")
    remove_worktree(9101, str(repo))  # what the reject endpoint does

    wt2 = create_worktree(9101, str(repo))  # re-run after feedback
    assert wt2.exists()
    assert not (wt2 / "rejected.py").exists()  # fresh start
    # the old work is preserved on a backup branch, not destroyed
    branches = _git(repo, "branch", "--format=%(refname:short)").split()
    backups = [b for b in branches if b.startswith("agent/task-9101-stale-")]
    assert len(backups) == 1
    assert _git(repo, "rev-parse", backups[0]).strip() == old_sha


def test_restart_after_reboot_wiped_worktree_dir(repo: Path) -> None:
    wt = create_worktree(9102, str(repo))
    _commit_in(wt, "partial.py")
    shutil.rmtree(wt)  # /tmp wiped by a reboot; git still has the registration

    wt2 = create_worktree(9102, str(repo))
    assert wt2.exists() and (wt2 / "a.py").exists()


def test_first_creation_is_unchanged(repo: Path) -> None:
    wt = create_worktree(9103, str(repo))
    assert _git(wt, "rev-parse", "--abbrev-ref", "HEAD").strip() == "agent/task-9103"
    branches = _git(repo, "branch", "--format=%(refname:short)").split()
    assert not any("stale" in b for b in branches)

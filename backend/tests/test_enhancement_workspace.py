"""APPLY phases run in an isolated worktree and merge back (audit 15).

Before, an approved enhancement edited and committed directly in the live
working copy, next to the owner's uncommitted work. Real git, no LLM.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.config import get_settings
from app.fleet import enhancement_workspace as ew


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture()
def live_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "live"
    (repo / "backend").mkdir(parents=True)
    (repo / "backend" / "a.py").write_text("x = 1\n")
    (repo / "backend" / "b.py").write_text("y = 1\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    monkeypatch.setattr(get_settings(), "fleet_self_repo_path", str(repo / "backend"))
    monkeypatch.setattr(get_settings(), "worktrees_dir", str(tmp_path / "wt"))
    return repo


def _apply_edit(ws: ew.ApplyWorkspace, name: str, text: str) -> str:
    root = Path(ew.apply_repo_path())
    (root / name).write_text(text)
    _git(root, "add", name)
    _git(root, "commit", "-qm", f"enhancement edits {name}")
    return _git(root, "rev-parse", "HEAD")


def test_the_agent_edits_the_worktree_never_the_live_copy(live_repo: Path) -> None:
    ws = ew.open_workspace(7)
    ew.activate(ws)
    try:
        assert ew.apply_repo_path() == ws.repo_path != str(live_repo / "backend")
        sha = _apply_edit(ws, "a.py", "x = 2\n")
        assert (live_repo / "backend" / "a.py").read_text() == "x = 1\n"  # untouched
        assert ew.merge_back(ws).merged
    finally:
        ew.deactivate(ws)
        ew.close_workspace(ws, keep_branch=False)
    assert ew.apply_repo_path() == str(live_repo / "backend")
    assert (live_repo / "backend" / "a.py").read_text() == "x = 2\n"
    assert _git(live_repo, "merge-base", "--is-ancestor", sha, "HEAD") == ""
    assert "fleet/enh-7" not in _git(live_repo, "branch")
    assert not Path(ws.worktree).exists()


def test_a_merge_that_would_clobber_uncommitted_work_is_refused(
    live_repo: Path,
) -> None:
    ws = ew.open_workspace(8)
    ew.activate(ws)
    try:
        _apply_edit(ws, "a.py", "x = 3\n")
        (live_repo / "backend" / "a.py").write_text("x = 'my unsaved work'\n")
        outcome = ew.merge_back(ws)
    finally:
        ew.deactivate(ws)
        ew.close_workspace(ws, keep_branch=True)
    assert not outcome.merged and outcome.detail
    assert (live_repo / "backend" / "a.py").read_text() == "x = 'my unsaved work'\n"
    assert "fleet/enh-8" in _git(live_repo, "branch")  # kept for the owner to merge


def test_the_repos_virtualenv_is_available_in_the_worktree(live_repo: Path) -> None:
    (live_repo / "backend" / ".venv").mkdir()
    ws = ew.open_workspace(9)
    try:
        assert (Path(ws.repo_path) / ".venv").resolve() == (
            live_repo / "backend" / ".venv"
        )
    finally:
        ew.close_workspace(ws, keep_branch=False)

"""W5 — build a new project from zero (2026-10-09).

Both new-project setups make a first commit (a new folder gets a README,
a new GitHub repository GitHub's own README), so the old "blank repository"
bootstrap — which writes and commits straight into the folder with no
approval — never ran for them, and nothing told the team the project was
new. Now the free scan recognises a starter-only project and every agent's
context says plainly: this is a new project, build it from zero. The work
then goes through the normal pipeline (plan approval, its own worktree,
tests, delivery approval).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.pipeline.bootstrap import is_blank_repo
from app.repo_tools import project_scan
from app.repo_tools.project_scan import overview_text, scan_project


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    project_scan.reset_cache()


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _new_folder_project(tmp_path: Path) -> Path:
    """What "New project on this computer" leaves: a README, one commit."""
    root = tmp_path / "shop"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_text("# Shop\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "Start tracking project")
    return root


def _new_github_project(tmp_path: Path) -> Path:
    """What a new GitHub repository (auto_init) looks like once cloned."""
    root = tmp_path / "gh"
    root.mkdir()
    for name in ("README.md", "LICENSE", ".gitignore"):
        (root / name).write_text("x\n")
    return root


def test_a_new_folder_project_is_recognised(tmp_path: Path) -> None:
    root = _new_folder_project(tmp_path)
    assert not is_blank_repo(str(root))  # why the old bootstrap never ran
    o = scan_project(str(root))
    assert o["isNewProject"] is True
    text = overview_text(str(root))
    assert "This is a NEW project" in text and "only README.md" in text


def test_a_new_github_project_is_recognised(tmp_path: Path) -> None:
    assert scan_project(str(_new_github_project(tmp_path)))["isNewProject"] is True


def test_an_existing_project_is_not_new(tmp_path: Path) -> None:
    root = _new_folder_project(tmp_path)
    (root / "main.py").write_text("print('hi')\n")
    o = scan_project(str(root))
    assert o["isNewProject"] is False
    assert "NEW project" not in overview_text(str(root))


def test_an_empty_folder_is_new(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    assert "This is a NEW project" in overview_text(str(root))


def test_every_agent_is_told_even_when_indexing_fails(tmp_path: Path) -> None:
    from app.agents.base_graph import _make_memory_hook_node

    root = _new_folder_project(tmp_path)
    node = _make_memory_hook_node("build an online shop", str(root))
    empty = {"tasks": [], "failures": [], "learnings": [], "procedures": []}
    with (
        patch("app.memory.store.query_memory_context_sync", return_value=empty),
        patch(
            "app.repo_tools.scanner.index_repository_cached",
            side_effect=RuntimeError("nothing to index"),
        ),
    ):
        updates = node({"messages": [], "trace_id": "w5"})  # type: ignore[arg-type]
    assert "This is a NEW project" in updates["repo_context"]

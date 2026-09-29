"""Production audit 2026-09-29 — index_repository honours .gitignore.

Before: the scanner walked every directory except a short hardcoded list, so
the target workspace (which holds cloned repos under repos/, gitignored) was
indexed as 14,631 files in ~75 s — and base_graph's memory_hook_node runs that
index on EVERY agent run. After: 1,228 files in ~2.8 s on the same repo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.repo_tools.scanner import index_repository


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_repo(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("def main():\n    return 1\n")
    (tmp_path / "vendor_clone").mkdir()
    (tmp_path / "vendor_clone" / "big.py").write_text("def huge():\n    pass\n")
    (tmp_path / ".gitignore").write_text("vendor_clone/\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "i")
    return tmp_path


def test_gitignored_directory_is_not_indexed(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    idx = index_repository(str(repo))
    assert "app/main.py" in idx.files
    assert not any(p.startswith("vendor_clone/") for p in idx.files)


def test_new_untracked_but_not_ignored_file_is_still_indexed(tmp_path: Path) -> None:
    """An agent's freshly written, not-yet-committed file must stay visible."""
    repo = _make_repo(tmp_path)
    (repo / "app" / "new_module.py").write_text("class Fresh:\n    pass\n")
    idx = index_repository(str(repo))
    assert "app/new_module.py" in idx.files


def test_hardcoded_ignore_dirs_still_apply_inside_git_repos(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "lib.js").write_text("function x() {}\n")
    _git(repo, "add", "-f", "node_modules/lib.js")  # even if force-tracked
    idx = index_repository(str(repo))
    assert not any(p.startswith("node_modules/") for p in idx.files)


def test_non_git_directory_falls_back_to_directory_walk(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("def f():\n    pass\n")
    idx = index_repository(str(tmp_path))
    assert "pkg/mod.py" in idx.files


def test_cached_index_reused_until_the_repo_changes(tmp_path: Path) -> None:
    from app.repo_tools import scanner

    repo = _make_repo(tmp_path)
    first = scanner.index_repository_cached(str(repo))
    assert scanner.index_repository_cached(str(repo)) is first  # unchanged → reused
    (repo / "app" / "added.py").write_text("def added():\n    pass\n")  # untracked edit
    second = scanner.index_repository_cached(str(repo))
    assert second is not first and "app/added.py" in second.files
    _git(repo, "add", ".")
    _git(repo, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "c")
    assert scanner.index_repository_cached(str(repo)) is not second  # new commit

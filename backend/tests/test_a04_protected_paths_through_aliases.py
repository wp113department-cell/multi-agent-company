"""Sol A04 (2026-10-09): protected files through aliases.

check_path_in_worktree resolved symlinks to check the path stays inside
the worktree, but checked the protected-file rules (.env, .git, keys) only
against the path as spelled — so a link `notes.txt -> .env` or a folder
link `cfg -> .git` reached protected files. The rules now apply to the
file the path really reaches too. Attack matrix: read, write, edit, delete
and move, through file aliases and parent-folder aliases, with the real
tool handlers.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from app.policy.engine import check_path_in_worktree

SECRET = "SECRET=do-not-leak\n"


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".env").write_text(SECRET)
    (wt / ".git").mkdir()
    (wt / ".git" / "config").write_text("[core]\n")
    (wt / ".git" / "hooks").mkdir()
    (wt / "server.key").write_text("-----BEGIN PRIVATE KEY-----\n")
    (wt / "app.py").write_text("x = 1\n")
    # aliases an agent could create from its sandbox
    os.symlink(".env", wt / "notes.txt")
    os.symlink("server.key", wt / "readme.md")
    os.symlink(".git", wt / "cfg")
    (wt / "docs").mkdir()
    os.symlink("../.env", wt / "docs" / "settings.txt")
    return wt


ALIASES = [
    "notes.txt",
    "readme.md",
    "cfg/config",
    "cfg/hooks/pre-commit",
    "docs/settings.txt",
]


@pytest.mark.parametrize("alias", ALIASES)
def test_the_guard_follows_aliases(worktree: Path, alias: str) -> None:
    r = check_path_in_worktree(alias, str(worktree))
    assert not r.allowed and "leads to" in r.reason


def test_ordinary_files_are_still_allowed(worktree: Path) -> None:
    assert check_path_in_worktree("app.py", str(worktree)).allowed
    assert check_path_in_worktree("new/file.py", str(worktree)).allowed
    os.symlink("app.py", worktree / "alias.py")
    assert check_path_in_worktree("alias.py", str(worktree)).allowed


def test_direct_spellings_are_still_denied(worktree: Path) -> None:
    for p in (".env", ".git/config", "server.key"):
        assert not check_path_in_worktree(p, str(worktree)).allowed


def _handlers(wt: Path) -> dict[str, Any]:
    from app.agents.tools import make_chat_handlers, make_coder_handlers

    return {**make_chat_handlers(str(wt)), **make_coder_handlers(str(wt), str(wt))}


def _denied(out: Any) -> bool:
    text = str(out)
    return "DENIED" in text.upper() or "denied" in text or "[ERROR]" in text


@pytest.mark.parametrize("alias", ["notes.txt", "docs/settings.txt", "readme.md"])
def test_reading_a_secret_through_an_alias_is_refused(
    worktree: Path, alias: str
) -> None:
    h = _handlers(worktree)
    for tool, inp in (
        ("read_file", {"path": alias}),
        ("read_files", {"paths": [alias]}),
    ):
        out = h[tool](inp)
        assert "do-not-leak" not in str(out) and "PRIVATE KEY" not in str(out), tool


@pytest.mark.parametrize("alias", ["notes.txt", "docs/settings.txt"])
def test_writing_or_editing_a_secret_through_an_alias_is_refused(
    worktree: Path, alias: str
) -> None:
    h = _handlers(worktree)
    assert _denied(h["write_file"]({"path": alias, "content": "SECRET=owned\n"}))
    assert _denied(
        h["edit_file"]({"path": alias, "old_string": "do-not-leak", "new_string": "x"})
    )
    assert (worktree / ".env").read_text() == SECRET


def test_writing_into_git_through_a_folder_alias_is_refused(worktree: Path) -> None:
    h = _handlers(worktree)
    out = h["write_file"](
        {"path": "cfg/hooks/pre-commit", "content": "#!/bin/sh\nevil\n"}
    )
    assert _denied(out)
    assert not (worktree / ".git" / "hooks" / "pre-commit").exists()


@pytest.mark.parametrize("alias", ["notes.txt", "cfg/config"])
def test_deleting_or_moving_a_protected_file_through_an_alias_is_refused(
    worktree: Path, alias: str
) -> None:
    h = _handlers(worktree)
    _denied(h["delete_file"]({"path": alias}))
    _denied(h["move_file"]({"source": alias, "dest": "moved.txt"}))
    assert (worktree / ".env").read_text() == SECRET
    assert (worktree / ".git" / "config").exists()
    assert not (worktree / "moved.txt").exists()

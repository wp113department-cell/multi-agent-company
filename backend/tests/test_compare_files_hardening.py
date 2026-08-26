"""compare_files tool #127 — tool_enhance.md productionization pass
(2026-08-26).

Two real findings, on BOTH real implementations (`compare_files`
inside `make_chat_handlers`, byte-identical to `chat_agent.py`'s own
dispatch):

1. Severe — a worktree-boundary escape that is a genuine TWO-FILE
   ARBITRARY READ. Neither implementation validated `path_a`/`path_b`
   before `root / path_a`. Proved live: a real unified diff of two
   files entirely outside the intended worktree was genuinely
   produced, disclosing both files' full content.
2. A real robustness gap — an uncaught crash on a non-numeric
   `context`. Proved live: `context="not_a_number"` raised an
   unhandled `ValueError`.

Both are now closed via a shared `compare_files_handler()` using
`check_path_in_worktree()` on both fields and a `try/except` +
`[0, 50]` clamp on `context`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.compare_files import (
    COMPARE_FILES_TOOL,
    compare_files_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_compare_files_hardening", repo_path=repo)
    return ChatAgent(session)


def test_compare_files_tool_schema() -> None:
    assert COMPARE_FILES_TOOL["name"] == "compare_files"
    assert COMPARE_FILES_TOOL["input_schema"]["required"] == ["path_a", "path_b"]  # type: ignore[index]


def test_compare_files_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("compare_files") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape two-file arbitrary read
# ---------------------------------------------------------------------------


def test_make_chat_handlers_closes_path_a_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("hello\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("SECRET_OUTSIDE_WORKTREE")

    handlers = make_chat_handlers(str(repo))
    result = handlers["compare_files"]({"path_a": str(outside), "path_b": "a.txt"})
    assert "[POLICY DENIED]" in result
    assert "SECRET_OUTSIDE_WORKTREE" not in result


def test_make_chat_handlers_closes_path_b_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("hello\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("SECRET_OUTSIDE_WORKTREE")

    handlers = make_chat_handlers(str(repo))
    result = handlers["compare_files"]({"path_a": "a.txt", "path_b": str(outside)})
    assert "[POLICY DENIED]" in result
    assert "SECRET_OUTSIDE_WORKTREE" not in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_the_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside1 = tmp_path / "outside1.txt"
    outside1.write_text("SECRET_1")
    outside2 = tmp_path / "outside2.txt"
    outside2.write_text("SECRET_2")

    agent = _agent(str(repo))
    result = await agent._execute_tool(
        "compare_files", {"path_a": str(outside1), "path_b": str(outside2)}
    )
    assert "[POLICY DENIED]" in result
    assert "SECRET_1" not in result
    assert "SECRET_2" not in result


def test_handler_closes_the_escape_directly(tmp_path: Path) -> None:
    outside1 = tmp_path / "outside1.txt"
    outside1.write_text("SECRET_1")
    outside2 = tmp_path / "outside2.txt"
    outside2.write_text("SECRET_2")
    repo = tmp_path / "repo"
    repo.mkdir()

    result = compare_files_handler(
        repo, str(repo), {"path_a": str(outside1), "path_b": str(outside2)}
    )
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — uncaught crash on non-numeric context
# ---------------------------------------------------------------------------


def test_handler_no_longer_crashes_on_non_numeric_context(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello\n")
    (tmp_path / "b.txt").write_text("world\n")
    result = compare_files_handler(
        tmp_path,
        str(tmp_path),
        {"path_a": "a.txt", "path_b": "b.txt", "context": "not_a_number"},
    )
    assert result == "[ERROR] context must be an integer, got 'not_a_number'"


def test_handler_clamps_out_of_range_context(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello\n")
    (tmp_path / "b.txt").write_text("world\n")
    result = compare_files_handler(
        tmp_path, str(tmp_path), {"path_a": "a.txt", "path_b": "b.txt", "context": -5}
    )
    assert "[ERROR]" not in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths
# ---------------------------------------------------------------------------


def test_handler_shows_a_real_diff(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello\n")
    (tmp_path / "b.txt").write_text("world\n")
    result = compare_files_handler(
        tmp_path, str(tmp_path), {"path_a": "a.txt", "path_b": "b.txt"}
    )
    assert "-hello" in result
    assert "+world" in result


def test_handler_reports_identical_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello\n")
    (tmp_path / "b.txt").write_text("hello\n")
    result = compare_files_handler(
        tmp_path, str(tmp_path), {"path_a": "a.txt", "path_b": "b.txt"}
    )
    assert result == "Files are identical"


def test_handler_errors_cleanly_on_missing_file(tmp_path: Path) -> None:
    result = compare_files_handler(
        tmp_path, str(tmp_path), {"path_a": "ghost.txt", "path_b": "also_ghost.txt"}
    )
    assert "[ERROR]" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_shows_a_real_diff(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello\n")
    (tmp_path / "b.txt").write_text("world\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "compare_files", {"path_a": "a.txt", "path_b": "b.txt"}
    )
    assert "-hello" in result
    assert "+world" in result

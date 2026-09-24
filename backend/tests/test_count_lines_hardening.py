"""count_lines tool #129 — tool_enhance.md productionization pass
(2026-08-26).

Two real, empirically-verified findings, on the one real
implementation (`count_lines_h` inside `make_chat_handlers`, plus
`app/agents/chat_agent.py`'s dispatch, which never existed until this
turn):

1. A worktree-boundary escape that is a genuine ARBITRARY FILE/
   DIRECTORY READ — `root / path` was never validated. Proved live: a
   `path` value outside the intended worktree was genuinely read and
   its real line count returned.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools #100/#103/#110/#112/#118/#120/#122/#126) —
   every real interactive-chat call fell through to "[ERROR] Unknown
   tool".

Both are now closed via a shared `count_lines_handler()` using
`check_path_in_worktree()` on `path`, used by both real access paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.count_lines import COUNT_LINES_TOOL, count_lines_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_count_lines_hardening", repo_path=repo)
    return ChatAgent(session)


def test_count_lines_tool_schema() -> None:
    assert COUNT_LINES_TOOL["name"] == "count_lines"
    assert COUNT_LINES_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_count_lines_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("count_lines") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape arbitrary file/directory read
# ---------------------------------------------------------------------------


def test_make_chat_handlers_closes_file_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("line1\nline2\nline3\n")

    handlers = make_chat_handlers(str(repo))
    result = handlers["count_lines"]({"path": str(outside)})
    assert "[POLICY DENIED]" in result


def test_make_chat_handlers_closes_directory_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (outside_dir / "secret.py").write_text("x = 1\n")

    handlers = make_chat_handlers(str(repo))
    result = handlers["count_lines"]({"path": str(outside_dir), "pattern": "**/*.py"})
    assert "[POLICY DENIED]" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_the_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("line1\nline2\n")

    agent = _agent(str(repo))
    result = await agent._execute_tool("count_lines", {"path": str(outside)})
    assert "[POLICY DENIED]" in result


def test_handler_closes_the_escape_directly(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("line1\nline2\n")
    repo = tmp_path / "repo"
    repo.mkdir()

    result = count_lines_handler(repo, str(repo), {"path": str(outside)})
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("line1\nline2\nline3\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("count_lines", {"path": "a.py"})
    assert "Unknown tool" not in result
    assert "3 lines" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths, in both file and directory mode
# ---------------------------------------------------------------------------


def test_handler_counts_a_real_file(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("line1\nline2\nline3\n")
    result = count_lines_handler(tmp_path, str(tmp_path), {"path": "a.py"})
    assert result == "a.py: 3 lines"


def test_handler_counts_a_real_directory(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("line1\nline2\n")
    (tmp_path / "b.py").write_text("line1\n")
    result = count_lines_handler(
        tmp_path, str(tmp_path), {"path": ".", "pattern": "**/*.py"}
    )
    assert ".py: 3" in result
    assert "Total: 3" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_counts_a_real_file(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("line1\nline2\nline3\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("count_lines", {"path": "a.py"})
    assert result == "a.py: 3 lines"

"""append_file tool #26 — tool_enhance.md productionization pass
(2026-08-18).

No new vulnerability found this turn — append_file's worktree-boundary
check was already fixed for both real implementations during tool #11's
(undo_changes) cross-cutting audit. This turn re-verified that directly
(not assumed) and modularized the tool per tool_enhance.md's mandatory
rule.

Every test here proves behavior against the REAL dispatch methods
(ChatAgent._execute_tool and the real make_chat_handlers() handler), not
a reimplementation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.append_file import APPEND_FILE_TOOL, append_file_handler


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_append_file_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_append_file_tool_schema_requires_path_and_content() -> None:
    assert APPEND_FILE_TOOL["name"] == "append_file"
    assert APPEND_FILE_TOOL["input_schema"]["required"] == ["path", "content"]


# ---------------------------------------------------------------------------
# Worktree boundary — already fixed in tool #11, re-verified here
# ---------------------------------------------------------------------------


def test_handler_rejects_absolute_path_outside_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    result = append_file_handler(repo, str(repo), {"path": str(outside), "content": "x"})
    assert result.startswith("[POLICY DENIED]")
    assert not outside.exists()


def test_handler_rejects_dotenv(tmp_path: Path) -> None:
    result = append_file_handler(tmp_path, str(tmp_path), {"path": ".env", "content": "X=1"})
    assert result.startswith("[POLICY DENIED]")
    assert not (tmp_path / ".env").exists()


# ---------------------------------------------------------------------------
# Regression — real appends, creation-on-first-write, error surfacing
# ---------------------------------------------------------------------------


def test_handler_creates_file_on_first_append(tmp_path: Path) -> None:
    result = append_file_handler(tmp_path, str(tmp_path), {"path": "log.txt", "content": "line1\n"})
    assert result == "Appended 6 bytes to log.txt"
    assert (tmp_path / "log.txt").read_text() == "line1\n"


def test_handler_appends_to_existing_file(tmp_path: Path) -> None:
    (tmp_path / "log.txt").write_text("line1\n")
    result = append_file_handler(tmp_path, str(tmp_path), {"path": "log.txt", "content": "line2\n"})
    assert result == "Appended 6 bytes to log.txt"
    assert (tmp_path / "log.txt").read_text() == "line1\nline2\n"


def test_handler_creates_parent_directories(tmp_path: Path) -> None:
    result = append_file_handler(
        tmp_path, str(tmp_path), {"path": "nested/dir/log.txt", "content": "hi"}
    )
    assert result == "Appended 2 bytes to nested/dir/log.txt"
    assert (tmp_path / "nested/dir/log.txt").read_text() == "hi"


def test_handler_surfaces_write_errors_without_raising(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory")
    result = append_file_handler(
        tmp_path, str(tmp_path), {"path": "blocker/child.txt", "content": "x"}
    )
    assert result.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# Real call sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_append_file_real_execution(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    r1 = await agent._execute_tool("append_file", {"path": "log.txt", "content": "a\n"})
    r2 = await agent._execute_tool("append_file", {"path": "log.txt", "content": "b\n"})
    assert r1 == "Appended 2 bytes to log.txt"
    assert r2 == "Appended 2 bytes to log.txt"
    assert (tmp_path / "log.txt").read_text() == "a\nb\n"


@pytest.mark.asyncio
async def test_chat_agent_append_file_rejects_escape(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    outside = tmp_path.parent / f"td_append_outside_{tmp_path.name}.txt"
    result = await agent._execute_tool(
        "append_file", {"path": str(outside), "content": "x"}
    )
    assert result.startswith("[POLICY DENIED]")
    assert not outside.exists()


def test_make_chat_handlers_append_file_real_execution(tmp_path: Path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["append_file"]({"path": "log.txt", "content": "hello"})
    assert result == "Appended 5 bytes to log.txt"
    assert (tmp_path / "log.txt").read_text() == "hello"

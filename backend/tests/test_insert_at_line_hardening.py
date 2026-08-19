"""insert_at_line tool #47 — tool_enhance.md productionization pass
(2026-08-19).

No new security vulnerability found — both real implementations were
already identical and already correctly worktree-bounded (tool #11's
fix, re-verified here).

Real, empirically-proven functionality bug found instead: the schema
documents `line: 0` as "Use 0 to prepend," but the original logic sent
`line_num <= 0` to the END of the file, the exact opposite of the
documented contract. Proved live: inserting with `line=0` into a real
2-line file placed the new content AFTER both existing lines. Fixed:
`line_num <= 0` now correctly prepends.

Every test here uses a real file on disk and proves both the fix
against the REAL dispatch methods (ChatAgent._execute_tool and the
real make_chat_handlers() handler).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.insert_at_line import INSERT_AT_LINE_TOOL


def _real_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "f.txt").write_text("line1\nline2\nline3\n")
    return repo


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_insert_at_line_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_insert_at_line_tool_schema_requires_fields() -> None:
    assert INSERT_AT_LINE_TOOL["name"] == "insert_at_line"
    assert INSERT_AT_LINE_TOOL["input_schema"]["required"] == [
        "path",
        "line",
        "content",
    ]


def test_insert_at_line_is_in_chat_tools_exactly_once() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("insert_at_line") == 1


# ---------------------------------------------------------------------------
# The proven prepend-bug finding — verified closed on both real call
# sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_insert_at_line_zero_really_prepends(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "insert_at_line", {"path": "f.txt", "line": 0, "content": "FIRST"}
    )
    assert result.startswith("Inserted")
    assert (repo / "f.txt").read_text() == "FIRST\nline1\nline2\nline3\n"


def test_make_chat_handlers_insert_at_line_zero_really_prepends(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    handlers = make_chat_handlers(str(repo))

    result = handlers["insert_at_line"](
        {"path": "f.txt", "line": 0, "content": "FIRST"}
    )
    assert result.startswith("Inserted")
    assert (repo / "f.txt").read_text() == "FIRST\nline1\nline2\nline3\n"


# ---------------------------------------------------------------------------
# Regression — every other position must keep working exactly as before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_insert_at_line_middle(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "insert_at_line", {"path": "f.txt", "line": 2, "content": "INSERTED"}
    )
    assert result.startswith("Inserted")
    assert (repo / "f.txt").read_text() == "line1\nINSERTED\nline2\nline3\n"


@pytest.mark.asyncio
async def test_chat_agent_insert_at_line_beyond_end_clamps_to_append(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "insert_at_line", {"path": "f.txt", "line": 999, "content": "APPENDED"}
    )
    assert result.startswith("Inserted")
    assert (repo / "f.txt").read_text() == "line1\nline2\nline3\nAPPENDED\n"


@pytest.mark.asyncio
async def test_chat_agent_insert_at_line_rejects_protected_path(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "insert_at_line", {"path": ".env", "line": 1, "content": "x"}
    )
    assert result.startswith("[POLICY DENIED]")


@pytest.mark.asyncio
async def test_chat_agent_insert_at_line_rejects_outside_repo_path(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "insert_at_line", {"path": "/etc/hostname", "line": 1, "content": "x"}
    )
    assert result.startswith("[POLICY DENIED]")


@pytest.mark.asyncio
async def test_chat_agent_insert_at_line_file_not_found(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "insert_at_line", {"path": "nonexistent.txt", "line": 1, "content": "x"}
    )
    assert result.startswith("[ERROR]")

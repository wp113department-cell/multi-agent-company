"""find_references tool #74 — tool_enhance.md productionization pass
(2026-08-22).

Audited for every finding class this initiative has established (shell
injection, flag/program injection, worktree-boundary escape, unbounded
timeout, advertised-but-not-dispatched, uncaught-exception info-leak)
— none apply. No path/directory field exists in this tool's schema at
all — the search root is always the fixed repo root. `symbol` is
always wrapped with a literal `\\b` word-boundary prefix/suffix before
reaching grep, so it can never be interpreted as a flag, unlike
`search_code` (tool #69).

Pure modularization turn; these tests exist to prove the behavior
(including a live flag-injection attempt) rather than assert it from
reading alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    READ_ONLY_TOOLS,
    make_chat_handlers,
    make_read_only_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.find_references import FIND_REFERENCES_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_find_references_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_find_references_tool_schema_requires_symbol() -> None:
    assert FIND_REFERENCES_TOOL["name"] == "find_references"
    assert FIND_REFERENCES_TOOL["input_schema"]["required"] == ["symbol"]  # type: ignore[index]


def test_read_only_tools_index_nine_is_still_find_references() -> None:
    assert READ_ONLY_TOOLS[9]["name"] == "find_references"


# ---------------------------------------------------------------------------
# Attempted flag-injection — structurally impossible, verified live
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_find_references_flag_shaped_symbol_is_harmless(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("def real_function_marker():\n    pass\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_references", {"symbol": "-e"})
    assert "no references" in result


def test_canonical_read_only_handlers_flag_shaped_symbol_is_harmless(
    tmp_path: Path,
) -> None:
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["find_references"]({"symbol": "-e"})
    assert "no references" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# both real dispatch paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_find_references_finds_real_usages(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text(
        "def real_function_marker():\n    pass\n\n"
        "real_function_marker()\n"
    )
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "find_references", {"symbol": "real_function_marker"}
    )
    assert "target.py" in result
    assert result.count("real_function_marker") >= 2


@pytest.mark.asyncio
async def test_chat_agent_find_references_respects_file_pattern(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("marker_value = 1\n")
    (tmp_path / "target.ts").write_text("marker_value = 1\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "find_references", {"symbol": "marker_value", "file_pattern": "*.py"}
    )
    assert "target.py" in result
    assert "target.ts" not in result


def test_canonical_read_only_handlers_finds_real_usages(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text("def real_function_marker():\n    pass\n")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["find_references"]({"symbol": "real_function_marker"})
    assert "target.py" in result


def test_make_chat_handlers_find_references_finds_real_usages(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("def real_function_marker():\n    pass\n")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["find_references"]({"symbol": "real_function_marker"})
    assert "target.py" in result


def test_no_matches_reports_cleanly(tmp_path: Path) -> None:
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["find_references"]({"symbol": "definitely_not_present_xyz"})
    assert "no references" in result


def test_find_references_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("find_references") == 1

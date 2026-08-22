"""search_symbols tool #73 — tool_enhance.md productionization pass
(2026-08-22).

Audited for every finding class this initiative has established (shell
injection, flag/program injection, worktree-boundary escape, unbounded
timeout, advertised-but-not-dispatched, uncaught-exception info-leak)
— none apply, verified live, not assumed. No path/directory field
exists in this tool's schema at all — the search root is always the
fixed repo root. `name` is always concatenated after a fixed literal
prefix (`"def "`, `"class "`, etc.) before reaching grep, so it can
never be interpreted as a flag, unlike `search_code` (tool #69).

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
from app.tools.filesystem.search_symbols import SEARCH_SYMBOLS_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_search_symbols_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_search_symbols_tool_schema_requires_name() -> None:
    assert SEARCH_SYMBOLS_TOOL["name"] == "search_symbols"
    assert SEARCH_SYMBOLS_TOOL["input_schema"]["required"] == ["name"]  # type: ignore[index]


def test_read_only_tools_index_three_is_still_search_symbols() -> None:
    assert READ_ONLY_TOOLS[3]["name"] == "search_symbols"


# ---------------------------------------------------------------------------
# Attempted flag-injection — structurally impossible, verified live
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_search_symbols_flag_shaped_name_is_harmless(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("def real_function_marker():\n    pass\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("search_symbols", {"name": "-e"})
    assert "no symbol" in result


def test_canonical_read_only_handlers_flag_shaped_name_is_harmless(
    tmp_path: Path,
) -> None:
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["search_symbols"]({"name": "-e"})
    assert "no symbol" in result


@pytest.mark.asyncio
async def test_chat_agent_search_symbols_out_of_enum_kind_is_harmless(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("def real_function_marker():\n    pass\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "search_symbols", {"name": "real_function_marker", "kind": "bogus_kind"}
    )
    assert "no symbol" in result  # neither branch fires, no crash


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# both real dispatch paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_search_symbols_finds_a_real_function(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("def real_function_marker():\n    pass\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "search_symbols", {"name": "real_function_marker"}
    )
    assert "real_function_marker" in result
    assert "target.py" in result


@pytest.mark.asyncio
async def test_chat_agent_search_symbols_finds_a_real_class(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text("class RealClassMarker:\n    pass\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "search_symbols", {"name": "RealClassMarker", "kind": "class"}
    )
    assert "RealClassMarker" in result


def test_canonical_read_only_handlers_finds_a_real_function(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text("def real_function_marker():\n    pass\n")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["search_symbols"]({"name": "real_function_marker"})
    assert "real_function_marker" in result


def test_make_chat_handlers_search_symbols_finds_a_real_function(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("def real_function_marker():\n    pass\n")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["search_symbols"]({"name": "real_function_marker"})
    assert "real_function_marker" in result


def test_no_match_reports_cleanly(tmp_path: Path) -> None:
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["search_symbols"]({"name": "definitely_not_present_xyz"})
    assert "no symbol" in result


def test_search_symbols_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("search_symbols") == 1

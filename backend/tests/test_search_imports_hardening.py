"""search_imports tool #75 — tool_enhance.md productionization pass
(2026-08-22).

Audited for every finding class this initiative has established (shell
injection, flag/program injection, worktree-boundary escape, unbounded
timeout, advertised-but-not-dispatched, uncaught-exception info-leak)
— none apply. No path/directory field exists in this tool's schema at
all — the search root is always the fixed repo root. `module` is
always embedded inside a fixed-prefix pattern (`"import "`, `"from "`,
`'require("'`, etc.) before reaching grep, so it can never be
interpreted as a flag, unlike `search_code` (tool #69).

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
from app.tools.filesystem.search_imports import SEARCH_IMPORTS_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_search_imports_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_search_imports_tool_schema_requires_module() -> None:
    assert SEARCH_IMPORTS_TOOL["name"] == "search_imports"
    assert SEARCH_IMPORTS_TOOL["input_schema"]["required"] == ["module"]  # type: ignore[index]


def test_read_only_tools_index_eleven_is_still_search_imports() -> None:
    assert READ_ONLY_TOOLS[11]["name"] == "search_imports"


# ---------------------------------------------------------------------------
# Attempted flag-injection — structurally impossible, verified live
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_search_imports_flag_shaped_module_is_harmless(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("import real_module_marker\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("search_imports", {"module": "-e"})
    assert "no imports" in result


def test_canonical_read_only_handlers_flag_shaped_module_is_harmless(
    tmp_path: Path,
) -> None:
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["search_imports"]({"module": "-e"})
    assert "no imports" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# both real dispatch paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_search_imports_finds_a_real_python_import(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("import real_module_marker\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "search_imports", {"module": "real_module_marker"}
    )
    assert "real_module_marker" in result
    assert "target.py" in result


@pytest.mark.asyncio
async def test_chat_agent_search_imports_finds_a_real_from_import(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("from real_module_marker import thing\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "search_imports", {"module": "real_module_marker"}
    )
    assert "real_module_marker" in result


@pytest.mark.asyncio
async def test_chat_agent_search_imports_finds_a_real_js_require(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.js").write_text('const x = require("real_module_marker");\n')
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "search_imports", {"module": "real_module_marker"}
    )
    assert "real_module_marker" in result


@pytest.mark.asyncio
async def test_chat_agent_search_imports_respects_file_pattern(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("import real_module_marker\n")
    (tmp_path / "target.ts").write_text("import real_module_marker\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "search_imports", {"module": "real_module_marker", "file_pattern": "*.py"}
    )
    assert "target.py" in result
    assert "target.ts" not in result


def test_canonical_read_only_handlers_finds_a_real_import(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text("import real_module_marker\n")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["search_imports"]({"module": "real_module_marker"})
    assert "real_module_marker" in result


def test_make_chat_handlers_search_imports_finds_a_real_import(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.py").write_text("import real_module_marker\n")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["search_imports"]({"module": "real_module_marker"})
    assert "real_module_marker" in result


def test_no_matches_reports_cleanly(tmp_path: Path) -> None:
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["search_imports"]({"module": "definitely_not_present_xyz"})
    assert "no imports" in result


def test_search_imports_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("search_imports") == 1

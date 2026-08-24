"""find_todos tool #77 — tool_enhance.md productionization pass
(2026-08-23).

Two real, empirically-verified findings, both fixed at the shared
`find_todos_handler()` in `app.tools.filesystem.find_todos`:

1. Worktree-boundary escape on BOTH implementations, INCLUDING the
   canonical `make_read_only_handlers()` factory — same class as tool
   #76's `analyze_file`. Proved live: `find_todos({"directory":
   "/tmp/outside"})` genuinely returned a real TODO comment's content
   from a file outside the repo.
2. A real functionality-parity gap: `chat_agent.py`'s dispatch was
   missing `--include=*.js`, silently never finding TODOs in `.js`
   files that the canonical implementation already found.

`kind` was checked and confirmed structurally immune to the tool #69
flag-injection class (always wrapped in a fixed "(" ... "):" prefix
before reaching grep) — proved live with `kind="-e"`.

All tests here use real files on disk — nothing is mocked.
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
from app.tools.filesystem.find_todos import FIND_TODOS_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_find_todos_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_find_todos_tool_schema_has_no_required_fields() -> None:
    assert FIND_TODOS_TOOL["name"] == "find_todos"
    assert FIND_TODOS_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_read_only_tools_index_ten_is_still_find_todos() -> None:
    assert READ_ONLY_TOOLS[10]["name"] == "find_todos"


# ---------------------------------------------------------------------------
# Finding #1 — worktree-boundary escape (both real implementations,
# including the canonical factory)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_find_todos_rejects_directory_outside_repo(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "find_todos_hardening_outside"
    outside.mkdir(exist_ok=True)
    secret = outside / "secret.py"
    secret.write_text("# TODO: rotate the real production secret\n")
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "find_todos", {"directory": str(outside)}
        )
        assert "[POLICY DENIED]" in result
        assert "rotate the real production secret" not in result
    finally:
        secret.unlink()
        outside.rmdir()


def test_canonical_read_only_handlers_rejects_directory_outside_repo(
    tmp_path: Path,
) -> None:
    """The canonical implementation itself was vulnerable this time —
    verify it's now fixed too, not just chat_agent.py's copy."""
    outside = tmp_path.parent / "find_todos_hardening_outside2"
    outside.mkdir(exist_ok=True)
    secret = outside / "secret.py"
    secret.write_text("# FIXME: another real secret marker\n")
    try:
        handlers = make_read_only_handlers(str(tmp_path))
        result = handlers["find_todos"]({"directory": str(outside)})
        assert "[POLICY DENIED]" in result
        assert "another real secret marker" not in result
    finally:
        secret.unlink()
        outside.rmdir()


@pytest.mark.asyncio
async def test_chat_agent_find_todos_rejects_dotdot_traversal(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "find_todos", {"directory": "../../../../../../etc"}
    )
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — functionality parity: *.js inclusion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_find_todos_detects_js_marker(tmp_path: Path) -> None:
    """chat_agent.py's dispatch previously missed *.js files entirely."""
    (tmp_path / "app.js").write_text("// TODO: fix this js bug\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_todos", {})
    assert "fix this js bug" in result


def test_make_chat_handlers_find_todos_detects_js_marker(tmp_path: Path) -> None:
    (tmp_path / "app.js").write_text("// TODO: fix this js bug too\n")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["find_todos"]({})
    assert "fix this js bug too" in result


# ---------------------------------------------------------------------------
# kind — structurally immune to flag injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_find_todos_kind_is_flag_injection_immune(
    tmp_path: Path,
) -> None:
    (tmp_path / "x.py").write_text("# TODO: a real marker\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_todos", {"kind": "-e"})
    # A flag-shaped kind is embedded inside a fixed "(...):" wrapper —
    # never interpreted as a grep option — and simply finds nothing.
    assert "[ERROR]" not in result
    assert "a real marker" not in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# both real dispatch paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_find_todos_finds_real_markers(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("# TODO: implement real feature\n")
    (tmp_path / "b.py").write_text("# FIXME: real bug here\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_todos", {})
    assert "implement real feature" in result
    assert "real bug here" in result


@pytest.mark.asyncio
async def test_chat_agent_find_todos_kind_filter_narrows_results(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.py").write_text("# TODO: todo marker\n")
    (tmp_path / "b.py").write_text("# FIXME: fixme marker\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_todos", {"kind": "FIXME"})
    assert "fixme marker" in result
    assert "todo marker" not in result


@pytest.mark.asyncio
async def test_chat_agent_find_todos_no_markers_returns_clean_message(
    tmp_path: Path,
) -> None:
    (tmp_path / "clean.py").write_text("def real_function():\n    pass\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_todos", {})
    assert result == "(no TODOs found)"


def test_canonical_read_only_handlers_finds_real_markers(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("# TODO: canonical marker\n")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["find_todos"]({})
    assert "canonical marker" in result


def test_find_todos_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("find_todos") == 1

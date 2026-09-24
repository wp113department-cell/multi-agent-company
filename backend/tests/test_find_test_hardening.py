"""find_test tool #140 — tool_enhance.md productionization pass
(2026-09-11).

No path field in this tool's schema at all (only `function_name`) —
worktree-boundary escape does not apply. Checked live for the
shell-injection / grep-own-flag-collision class already established
repeatedly this initiative for chat_agent.py's `shell=True` grep
dispatches — does NOT apply here (`function_name` always reaches grep
embedded inside a literal "def test_"-prefixed pattern, never as a
bare argv token, and `shlex.quote()` correctly neutralizes shell
metacharacters) — verified live with a real payload, no injected
command executed.

One real finding — a functionality-divergence bug:
`chat_agent.py`'s dispatch was a separately-drifted, narrower
reimplementation of the same tool: missing the search pattern that
catches JS/TS `test("...")`-style test descriptions, a narrower
`--include` filter, and a generic `"(no output)"` fallback instead of
a clear "No tests found" message. Proved live: a real JS-style test
file was found by the canonical `make_chat_handlers()` implementation
but silently missed by `chat_agent.py`'s dispatch.

Both real call sites now delegate to a shared, canonical
`find_test_handler()`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.find_test import FIND_TEST_TOOL, find_test_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_find_test_hardening", repo_path=repo)
    return ChatAgent(session)


def test_find_test_tool_schema() -> None:
    assert FIND_TEST_TOOL["name"] == "find_test"
    assert FIND_TEST_TOOL["input_schema"]["required"] == ["function_name"]  # type: ignore[index]


def test_find_test_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("find_test") == 1


# ---------------------------------------------------------------------------
# Verified-safe check — no shell injection / flag collision (not
# assumed; empirically re-confirmed here)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_is_not_shell_injectable(tmp_path: Path) -> None:
    marker = tmp_path / "PWNED_MARKER"
    payload = f"x'; touch {marker}; echo x"
    agent = _agent(str(tmp_path))
    await agent._execute_tool("find_test", {"function_name": payload})
    assert not marker.exists()


# ---------------------------------------------------------------------------
# Finding — chat_agent.py's dispatch no longer misses JS-style tests
# or returns the unhelpful "(no output)" fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_now_finds_js_style_tests(tmp_path: Path) -> None:
    """The real, live-proven divergence: chat_agent.py's dispatch used
    to miss this match entirely."""
    (tmp_path / "sample.test.ts").write_text(
        'test("special_widget renders correctly", () => {\n'
        "  expect(true).toBe(true);\n"
        "});\n"
    )
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("find_test", {"function_name": "special_widget"})
    assert "special_widget" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_gives_clear_not_found_message(
    tmp_path: Path,
) -> None:
    """chat_agent.py's dispatch used to return the generic "(no
    output)" from its own shell wrapper instead of this message."""
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "find_test", {"function_name": "totally_nonexistent_xyz"}
    )
    assert result == "No tests found for 'totally_nonexistent_xyz'"
    assert result != "(no output)"


def test_make_chat_handlers_finds_js_style_tests(tmp_path: Path) -> None:
    (tmp_path / "sample.test.ts").write_text(
        'test("special_widget renders correctly", () => {\n'
        "  expect(true).toBe(true);\n"
        "});\n"
    )
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["find_test"]({"function_name": "special_widget"})
    assert "special_widget" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths, for Python-style tests too
# ---------------------------------------------------------------------------


def test_handler_finds_a_real_python_test(tmp_path: Path) -> None:
    (tmp_path / "test_sample.py").write_text(
        "def test_my_function():\n    assert True\n"
    )
    result = find_test_handler(str(tmp_path), {"function_name": "my_function"})
    assert "test_my_function" in result


def test_handler_reports_no_tests_found(tmp_path: Path) -> None:
    result = find_test_handler(str(tmp_path), {"function_name": "ghost_xyzzy_func"})
    assert result == "No tests found for 'ghost_xyzzy_func'"


@pytest.mark.asyncio
async def test_chat_agent_dispatch_finds_a_real_python_test(tmp_path: Path) -> None:
    (tmp_path / "test_sample.py").write_text(
        "def test_my_function():\n    assert True\n"
    )
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("find_test", {"function_name": "my_function"})
    assert "test_my_function" in result

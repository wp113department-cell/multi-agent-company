"""analyze_error tool #121 — tool_enhance.md productionization pass
(2026-08-26).

One real, severe finding — a field-name mismatch causing a 100%
functional-failure rate, same class as tool #111's `find_function_body`:
`bf_analyze_error` (`make_bug_fix_handlers`) read `inp.get("traceback",
"")`, but the tool's own schema requires (and every real caller sends)
`error`, never `traceback`. Proved live: a genuine, well-formed
traceback passed as the schema's own documented `{"error": ...}` shape
produced `"(no error markers found)"` every single time.

`analyze_error` (`make_chat_handlers`) and `chat_agent.py`'s dispatch
both already read `inp["error"]` correctly and implement the tool's
full documented contract — `bf_analyze_error` is now fully replaced
with that same shared, correct logic.

A pre-existing test (`test_day2_agents.py::
TestBugFixHandlers::test_analyze_error_extracts_markers`) previously
called the handler with the WRONG field name (`traceback`), matching
the bug rather than the real schema — this let the test pass while the
real tool was 100% broken for every genuine call. That test has been
corrected to use the schema's real field name (`error`) as part of
this turn.
"""

from __future__ import annotations

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    analyze_error_handler,
    make_bug_fix_handlers,
    make_chat_handlers,
)
from app.models.chat import ChatSession
from app.tools.execution.analyze_error import ANALYZE_ERROR_TOOL

REAL_TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "app.py", line 5, in foo\n'
    "    bar()\n"
    "ValueError: boom"
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_analyze_error_hardening", repo_path=repo)
    return ChatAgent(session)


def test_analyze_error_tool_schema() -> None:
    assert ANALYZE_ERROR_TOOL["name"] == "analyze_error"
    assert ANALYZE_ERROR_TOOL["input_schema"]["required"] == ["error"]  # type: ignore[index]


def test_analyze_error_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("analyze_error") == 1


# ---------------------------------------------------------------------------
# Finding — bf_analyze_error's field-name mismatch, now fixed
# ---------------------------------------------------------------------------


def test_bf_analyze_error_no_longer_broken_on_the_real_schema_field(
    tmp_path,
) -> None:
    """The severe, live-proven bug: calling with the schema's own
    documented `error` field (what every real LLM call actually sends)
    used to always return "(no error markers found)"."""
    handlers = make_bug_fix_handlers(str(tmp_path))
    result = handlers["analyze_error"]({"error": REAL_TRACEBACK})
    assert result != "(no error markers found)"
    assert "ValueError: boom" in result
    assert "Error Analysis" in result


def test_bf_analyze_error_matches_the_other_two_implementations(tmp_path) -> None:
    bf_handlers = make_bug_fix_handlers(str(tmp_path))
    chat_handlers = make_chat_handlers(str(tmp_path))
    bf_result = bf_handlers["analyze_error"]({"error": REAL_TRACEBACK})
    chat_result = chat_handlers["analyze_error"]({"error": REAL_TRACEBACK})
    assert bf_result == chat_result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on all three real
# access paths, including suggestion heuristics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory",
    [make_bug_fix_handlers, make_chat_handlers],
)
def test_all_factories_extract_exception_and_frame(tmp_path, factory) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["analyze_error"]({"error": REAL_TRACEBACK})
    assert "Exception: ValueError: boom" in result
    assert 'File "app.py", line 5, in foo' in result


@pytest.mark.parametrize(
    "factory",
    [make_bug_fix_handlers, make_chat_handlers],
)
def test_all_factories_give_module_not_found_suggestion(tmp_path, factory) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["analyze_error"](
        {"error": "ModuleNotFoundError: No module named 'fastapi'"}
    )
    assert "pip install" in result.lower()


@pytest.mark.asyncio
async def test_chat_agent_dispatch_extracts_exception_and_frame(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("analyze_error", {"error": REAL_TRACEBACK})
    assert "Exception: ValueError: boom" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_gives_valueerror_suggestion(tmp_path) -> None:
    """chat_agent.py's own copy was missing the `valueerror` suggestion
    branch present in make_chat_handlers()'s version — now unified onto
    the shared handler, closing that drift too."""
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("analyze_error", {"error": "ValueError: bad"})
    assert "Invalid value" in result


def test_handler_returns_fallback_message_for_input_with_no_error_markers() -> None:
    result = analyze_error_handler({"error": "just some plain text, nothing special"})
    assert result == "=== Error Analysis ==="

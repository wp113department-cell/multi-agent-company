"""run_python_snippet tool #14 — tool_enhance.md productionization pass
(2026-08-17).

Real finding (moderate severity, resource-exhaustion class — not a data
breach): both real, reachable implementations (chat_agent.py's dispatch
and make_chat_handlers's own) accepted an LLM-controlled `timeout` field
with no upper bound, passed straight into `subprocess.run(..., timeout=...)`.
Proved directly (mocking only the subprocess boundary, not the fix logic)
that a timeout of 999999999 was passed straight through before the fix;
this file proves it's now clamped.

Every test here proves the fix against the REAL dispatch methods
(ChatAgent._execute_tool and the real make_chat_handlers() handler), not
a reimplementation.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.python_snippet import (
    MAX_PYTHON_SNIPPET_TIMEOUT_SECONDS,
    RUN_PYTHON_SNIPPET_TOOL,
    run_python_snippet_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_run_python_snippet_hardening", repo_path=repo)
    return ChatAgent(session)


def test_run_python_snippet_tool_schema_has_required_fields() -> None:
    assert RUN_PYTHON_SNIPPET_TOOL["name"] == "run_python_snippet"
    assert RUN_PYTHON_SNIPPET_TOOL["input_schema"]["required"] == ["code"]


def test_handler_clamps_an_excessive_timeout_before_it_reaches_subprocess(
    tmp_path,
) -> None:
    with patch("app.tools.execution.python_snippet.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        run_python_snippet_handler(
            str(tmp_path),
            {"code": "pass", "timeout": 999999999},
            activate_snippet="true",
        )
    assert mock_run.call_args.kwargs["timeout"] == MAX_PYTHON_SNIPPET_TIMEOUT_SECONDS


def test_handler_clamps_a_negative_or_zero_timeout_to_at_least_one_second(
    tmp_path,
) -> None:
    with patch("app.tools.execution.python_snippet.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        run_python_snippet_handler(
            str(tmp_path), {"code": "pass", "timeout": -5}, activate_snippet="true"
        )
    assert mock_run.call_args.kwargs["timeout"] == 1


def test_handler_preserves_a_reasonable_requested_timeout(tmp_path) -> None:
    with patch("app.tools.execution.python_snippet.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        run_python_snippet_handler(
            str(tmp_path), {"code": "pass", "timeout": 45}, activate_snippet="true"
        )
    assert mock_run.call_args.kwargs["timeout"] == 45


def test_handler_defaults_to_30_seconds_when_timeout_omitted(tmp_path) -> None:
    with patch("app.tools.execution.python_snippet.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        run_python_snippet_handler(str(tmp_path), {"code": "pass"}, activate_snippet="true")
    assert mock_run.call_args.kwargs["timeout"] == 30


def test_handler_runs_real_code_and_captures_stdout(tmp_path) -> None:
    result = run_python_snippet_handler(
        str(tmp_path), {"code": "print(2 + 2)"}, activate_snippet="true"
    )
    assert "4" in result


def test_handler_truncates_huge_output_to_5000_chars(tmp_path) -> None:
    result = run_python_snippet_handler(
        str(tmp_path),
        {"code": "print('x' * 100000)"},
        activate_snippet="true",
    )
    assert len(result) <= 5000


def test_handler_reports_a_real_timeout_expiring(tmp_path) -> None:
    result = run_python_snippet_handler(
        str(tmp_path),
        {"code": "import time; time.sleep(5)", "timeout": 1},
        activate_snippet="true",
    )
    assert result.startswith("[ERROR]")
    assert "timed out" in result


def test_handler_captures_a_real_syntax_error(tmp_path) -> None:
    result = run_python_snippet_handler(
        str(tmp_path), {"code": "def bad(:\n    pass"}, activate_snippet="true"
    )
    assert "SyntaxError" in result or "Error" in result


# ---------------------------------------------------------------------------
# Real call sites — previously untested for chat_agent.py's own dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_run_python_snippet_real_execution(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("run_python_snippet", {"code": "print(2 + 2)"})
    assert "4" in result


@pytest.mark.asyncio
async def test_chat_agent_run_python_snippet_clamps_excessive_timeout(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    with patch("app.tools.execution.python_snippet.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        await agent._execute_tool(
            "run_python_snippet", {"code": "pass", "timeout": 10**9}
        )
    assert mock_run.call_args.kwargs["timeout"] == MAX_PYTHON_SNIPPET_TIMEOUT_SECONDS


def test_make_chat_handlers_run_python_snippet_real_execution(tmp_path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["run_python_snippet"]({"code": "print(3 + 3)"})
    assert "6" in result


def test_make_chat_handlers_run_python_snippet_clamps_excessive_timeout(tmp_path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    with patch("app.tools.execution.python_snippet.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        handlers["run_python_snippet"]({"code": "pass", "timeout": 10**9})
    assert mock_run.call_args.kwargs["timeout"] == MAX_PYTHON_SNIPPET_TIMEOUT_SECONDS

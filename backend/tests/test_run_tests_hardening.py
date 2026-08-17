"""run_tests tool #16 — tool_enhance.md productionization pass
(2026-08-17).

Real, empirically-verified finding (same bug class as tool #8's
run_migration): `chat_agent.py`'s real dispatch interpolated `path`/
`flags` (LLM-controlled) directly into an f-string `shell=True` command
with zero validation or quoting. Proved directly: a `path` value of
`"; touch /tmp/PWNED...; echo "` created a real marker file on the host,
completely outside the intended pytest invocation.

`make_chat_handlers`'s own `run_tests` (the other real, reachable
implementation) was already correctly guarded — this fix reuses that
already-proven-correct pattern (`shlex.quote(path)` +
`_shell_metachar_reason(flags)`) rather than inventing a new one.

Every test here proves the fix against the REAL dispatch methods
(ChatAgent._execute_tool and the real make_chat_handlers() handler), not
a reimplementation — real subprocess/pytest execution throughout.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.run_tests import RUN_TESTS_TOOL, run_tests_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_run_tests_hardening", repo_path=repo)
    return ChatAgent(session)


def _write_passing_test(repo: Path) -> None:
    (repo / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")


def _write_failing_test(repo: Path) -> None:
    (repo / "test_fail.py").write_text(
        "def test_fail():\n    assert 1 + 1 == 3, 'real failure'\n"
    )


def test_run_tests_tool_schema_has_runner_enum() -> None:
    assert RUN_TESTS_TOOL["name"] == "run_tests"
    assert set(RUN_TESTS_TOOL["input_schema"]["properties"]["runner"]["enum"]) == {
        "pytest",
        "npm_test",
        "tsc",
    }


# ---------------------------------------------------------------------------
# The real, proven exploit — verified closed
# ---------------------------------------------------------------------------


def test_handler_rejects_shell_injection_via_path(tmp_path: Path) -> None:
    marker = tmp_path / "PWNED_via_path.txt"
    payload_path = f"; touch {marker}; echo "
    result = run_tests_handler(
        str(tmp_path), {"path": payload_path}, activate_snippet="true"
    )
    assert not marker.exists()
    # The payload is now safely quoted as a single (nonexistent) pytest
    # path argument — pytest itself reports "not found", not a shell error.
    assert "not found" in result or "[ERROR]" in result


def test_handler_rejects_shell_injection_via_flags(tmp_path: Path) -> None:
    marker = tmp_path / "PWNED_via_flags.txt"
    payload_flags = f"; touch {marker}; echo "
    result = run_tests_handler(
        str(tmp_path), {"flags": payload_flags}, activate_snippet="true"
    )
    assert not marker.exists()
    assert result.startswith("[POLICY DENIED]")


def test_handler_rejects_shell_metacharacters_in_flags_for_every_runner(
    tmp_path: Path,
) -> None:
    for runner in ("pytest", "npm_test", "tsc"):
        result = run_tests_handler(
            str(tmp_path),
            {"runner": runner, "flags": "&& echo pwned"},
            activate_snippet="true",
        )
        assert result.startswith("[POLICY DENIED]"), f"{runner}: {result!r}"


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before
# ---------------------------------------------------------------------------


def test_handler_real_passing_pytest_run(tmp_path: Path) -> None:
    _write_passing_test(tmp_path)
    result = run_tests_handler(
        str(tmp_path), {"path": "test_ok.py"}, activate_snippet="true"
    )
    assert not result.startswith("[ERROR]")
    assert "1 passed" in result


def test_handler_real_failing_pytest_run_is_flagged_as_error(tmp_path: Path) -> None:
    _write_failing_test(tmp_path)
    result = run_tests_handler(
        str(tmp_path), {"path": "test_fail.py"}, activate_snippet="true"
    )
    assert result.startswith("[ERROR]")
    assert "real failure" in result


def test_handler_unknown_runner_still_errors_cleanly(tmp_path: Path) -> None:
    result = run_tests_handler(
        str(tmp_path), {"runner": "bogus"}, activate_snippet="true"
    )
    assert result == "[ERROR] Unknown runner: bogus"


def test_handler_pytest_summary_prepended_on_real_failure(tmp_path: Path) -> None:
    _write_failing_test(tmp_path)
    result = run_tests_handler(
        str(tmp_path), {"path": "test_fail.py"}, activate_snippet="true"
    )
    assert "Test Summary" in result


# ---------------------------------------------------------------------------
# Real call sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_run_tests_real_dispatch_closes_the_exploit(
    tmp_path: Path,
) -> None:
    agent = _agent(str(tmp_path))
    marker = tmp_path / "PWNED_chat_agent.txt"
    payload_path = f"; touch {marker}; echo "
    result = await agent._execute_tool("run_tests", {"path": payload_path})
    assert not marker.exists()
    assert "[ERROR]" in result


@pytest.mark.asyncio
async def test_chat_agent_run_tests_real_dispatch_legit_passing_run(
    tmp_path: Path,
) -> None:
    _write_passing_test(tmp_path)
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("run_tests", {"path": "test_ok.py"})
    assert not result.startswith("[ERROR]")
    assert "1 passed" in result


@pytest.mark.asyncio
async def test_chat_agent_run_tests_real_dispatch_legit_failing_run(
    tmp_path: Path,
) -> None:
    _write_failing_test(tmp_path)
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("run_tests", {"path": "test_fail.py"})
    assert result.startswith("[ERROR]")
    assert "real failure" in result


def test_make_chat_handlers_run_tests_closes_the_exploit(tmp_path: Path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    marker = tmp_path / "PWNED_handlers.txt"
    payload_path = f"; touch {marker}; echo "
    result = handlers["run_tests"]({"path": payload_path})
    assert not marker.exists()
    assert "[ERROR]" in result


def test_make_chat_handlers_run_tests_legit_run(tmp_path: Path) -> None:
    _write_passing_test(tmp_path)
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["run_tests"]({"path": "test_ok.py"})
    assert not result.startswith("[ERROR]")

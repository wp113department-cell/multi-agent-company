"""Gap-closure Day 15 (Stage 1.2, answers.md) — proves run_tests now parses
the test runner's REAL exit code into its output, instead of discarding it
entirely (confirmed by reading the pre-fix code: `subprocess.run(...)`'s
`result.returncode` was never referenced anywhere in either `run_tests`
implementation in `app/agents/tools.py`, nor in `app/agents/chat_agent.py`'s
own separate `run_tests` dispatch). Before this, a real failing test run's
output — captured for real, no exception — still read as a clean,
verification-flag-setting success to every consumer
(bug_fix/dependency_agent/refactor_agent/chat_agent all map
`"run_tests": "tests_passed"`; agent_debugger/agent_performance_reviewer/
quality_auditor map it to `"tests_run"`).

Uses a REAL pytest subprocess against a real, throwaway test file in
tmp_path — not mocked — since the exit code itself is exactly the thing
under test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.base_graph import (
    AgentRunState,
    VerificationConfig,
    _make_execute_tools_node,
)
from app.agents.chat_agent import _run_subprocess
from app.agents.tools import make_chat_handlers, make_fleet_apply_handlers

_RUN_TESTS_TOOL = {
    "name": "run_tests",
    "description": "Run tests",
    "input_schema": {
        "type": "object",
        "properties": {
            "runner": {"type": "string"},
            "path": {"type": "string"},
            "flags": {"type": "string"},
        },
    },
}


def _write_passing_test(repo: Path) -> None:
    (repo / "test_ok.py").write_text(
        "def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8"
    )


def _write_failing_test(repo: Path) -> None:
    (repo / "test_fail.py").write_text(
        "def test_fail():\n    assert 1 + 1 == 3, 'real failure'\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# make_chat_handlers().run_tests — real pytest subprocess
# ---------------------------------------------------------------------------


def test_chat_handlers_run_tests_marks_a_real_failure_as_error(tmp_path: Path) -> None:
    _write_failing_test(tmp_path)
    handlers = make_chat_handlers(str(tmp_path))
    out = handlers["run_tests"]({"path": "test_fail.py"})
    assert out.startswith("[ERROR]")
    assert "real failure" in out


def test_chat_handlers_run_tests_does_not_flag_a_real_pass(tmp_path: Path) -> None:
    _write_passing_test(tmp_path)
    handlers = make_chat_handlers(str(tmp_path))
    out = handlers["run_tests"]({"path": "test_ok.py"})
    assert not out.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# make_fleet_apply_handlers().run_tests — real pytest subprocess
# ---------------------------------------------------------------------------


def test_fleet_apply_handlers_run_tests_marks_a_real_failure_as_error(
    tmp_path: Path,
) -> None:
    _write_failing_test(tmp_path)
    handlers = make_fleet_apply_handlers(str(tmp_path))
    out = handlers["run_tests"]({"path": "test_fail.py"})
    assert out.startswith("[ERROR]")
    assert "real failure" in out


def test_fleet_apply_handlers_run_tests_does_not_flag_a_real_pass(
    tmp_path: Path,
) -> None:
    _write_passing_test(tmp_path)
    handlers = make_fleet_apply_handlers(str(tmp_path))
    out = handlers["run_tests"]({"path": "test_ok.py"})
    assert not out.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# chat_agent.py's _run_subprocess(fail_on_nonzero_exit=...)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_subprocess_fail_on_nonzero_exit_true_flags_real_failure(
    tmp_path: Path,
) -> None:
    _write_failing_test(tmp_path)
    out = _run_subprocess(
        "python -m pytest test_fail.py --tb=short -q",
        str(tmp_path),
        fail_on_nonzero_exit=True,
    )
    assert out.startswith("[ERROR]")
    assert "real failure" in out


@pytest.mark.asyncio
async def test_run_subprocess_fail_on_nonzero_exit_false_preserves_bash_tool_behavior(
    tmp_path: Path,
) -> None:
    """The generic bash tool's default (fail_on_nonzero_exit=False) must
    stay unchanged — a nonzero exit (e.g. grep finding nothing) is
    informational output, not an [ERROR]."""
    out = _run_subprocess("exit 1", str(tmp_path))
    assert not out.startswith("[ERROR]")
    assert "[exit 1]" in out


# ---------------------------------------------------------------------------
# End-to-end through the real graph-enforcement path: a real failing test
# run must NOT set the verification flag, tying both Day 15 fixes together.
# ---------------------------------------------------------------------------


def test_real_failing_test_run_does_not_set_tests_passed_flag(tmp_path: Path) -> None:
    _write_failing_test(tmp_path)
    handlers = make_chat_handlers(str(tmp_path))

    cfg = VerificationConfig(set_by={"run_tests": "tests_passed"})
    node = _make_execute_tools_node(
        tool_handlers={"run_tests": handlers["run_tests"]},
        verification_cfg=cfg,
        human_approval_required=False,
        tools=[_RUN_TESTS_TOOL],
    )
    state: AgentRunState = {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu1",
                        "name": "run_tests",
                        "input": {"path": "test_fail.py"},
                    }
                ],
            }
        ],
        "verification": {"tests_passed": False},
        "result": {},
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": 0,
        "tokens_out": 0,
        "turns": 1,
        "confidence": 1.0,
        "critique_result": {},
    }

    result = node(state)
    assert result["verification"].get("tests_passed") is not True


def test_real_passing_test_run_sets_tests_passed_flag(tmp_path: Path) -> None:
    _write_passing_test(tmp_path)
    handlers = make_chat_handlers(str(tmp_path))

    cfg = VerificationConfig(set_by={"run_tests": "tests_passed"})
    node = _make_execute_tools_node(
        tool_handlers={"run_tests": handlers["run_tests"]},
        verification_cfg=cfg,
        human_approval_required=False,
        tools=[_RUN_TESTS_TOOL],
    )
    state: AgentRunState = {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu1",
                        "name": "run_tests",
                        "input": {"path": "test_ok.py"},
                    }
                ],
            }
        ],
        "verification": {"tests_passed": False},
        "result": {},
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": 0,
        "tokens_out": 0,
        "turns": 1,
        "confidence": 1.0,
        "critique_result": {},
    }

    result = node(state)
    assert result["verification"].get("tests_passed") is True

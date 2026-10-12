"""Sol A21 (2026-10-12): quality checks have four outcomes — passed,
failed, unavailable, skipped — and a required check that could not run
blocks the step instead of counting as passed.

Before: an exception in a reviewer (timeout, malformed output, scanner or
service outage) was logged and treated as "no blocking reason", so a step
was marked done with its security check never having run. No AI runs: the
reviewers are fakes.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from app.agents.agent_result import AgentResult
from app.agents.manager import _run_advisory_quality_gates
from app.config import get_settings


def _ok(**raw: Any) -> AgentResult:
    return AgentResult(
        summary="ok",
        findings=[],
        files_touched=[],
        verified=True,
        requires_human_approval=False,
        tokens_in=1,
        tokens_out=1,
        status="completed",
        raw=raw,
    )


def _no_verdict(status: str) -> AgentResult:
    return AgentResult(
        summary="reviewer did not finish",
        findings=[],
        files_touched=[],
        verified=False,
        requires_human_approval=False,
        tokens_in=1,
        tokens_out=1,
        status=status,
        raw={},
    )


def _run(security: Any, architecture: Any, dependency: Any, **kw: Any) -> str | None:
    def fake(value: Any) -> Any:
        return (
            {"side_effect": value}
            if isinstance(value, Exception)
            else {"return_value": value}
        )

    with (
        patch("app.agents.security_reviewer.run_security_review", **fake(security)),
        patch("app.agents.architecture_reviewer.run_arch_review", **fake(architecture)),
        patch(
            "app.agents.dependency_security_agent.run_dependency_security_agent",
            **fake(dependency),
        ),
    ):
        _, _, reason = asyncio.run(
            _run_advisory_quality_gates(
                task_id=1, subtask_id=1, repo="/tmp/x", epic_id=None, db=None, **kw
            )
        )
    return reason


def test_all_checks_passing_does_not_block() -> None:
    assert _run(_ok(), _ok(), _ok()) is None


@pytest.mark.parametrize(
    "broken",
    [TimeoutError("reviewer timed out"), ValueError("malformed output")],
)
def test_a_required_check_that_crashes_blocks(broken: Exception) -> None:
    reason = _run(_ok(), _ok(), broken)
    assert reason is not None and "dependency check could not run" in reason


@pytest.mark.parametrize("status", ["failed", "blocked"])
def test_a_reviewer_that_gave_no_verdict_counts_as_unavailable(status: str) -> None:
    reason = _run(_no_verdict(status), _ok(), _ok())
    assert reason is not None and "security check could not run" in reason


def test_an_optional_check_that_crashes_does_not_block() -> None:
    assert _run(_ok(), RuntimeError("down"), _ok()) is None


def test_checks_skipped_on_purpose_stay_skipped() -> None:
    boom = RuntimeError("must not be called")
    assert _run(boom, boom, boom, llm_gates=False) is None


def test_the_owner_can_switch_fail_closed_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "quality_gates_fail_closed", False)
    assert _run(RuntimeError("down"), _ok(), _ok()) is None

"""G6 (2026-10-12): an automatic prompt rollback is decided only on runs
made with the deployed prompt, and always lands on the audit trail.

Before: the rollback loop used the agent's recent-runs window, which could
include runs from before the prompt was deployed, so a prompt could be
rolled back for results it never produced; the rollback itself wrote no
audit entry although no human is involved. No AI runs: metrics are fakes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.fleet.benchmark_manager import BenchmarkResult
from app.fleet.metrics import RunMetrics
from app.main import _regressed_under_deployed_prompt, _run_prompt_auto_rollback_once

DEPLOYED = datetime(2026, 10, 10, tzinfo=timezone.utc)


def _run(when: datetime, good: bool) -> RunMetrics:
    run = RunMetrics(trace_id="t", agent_name="g6_role")
    run.started_at = when.isoformat()
    # a bad run: low verification coverage and its reflection disagreed
    run.verification_pct = 1.0 if good else 0.0  # type: ignore[attr-defined]
    run.reflection_unsatisfied = 0 if good else 3  # type: ignore[attr-defined]
    return run


def _collector(runs: list[RunMetrics]) -> Any:
    fake = MagicMock()
    fake.by_agent.return_value = runs
    fake.p50_latency_ms.return_value = None
    fake.avg_tool_accuracy.return_value = None
    return fake


@pytest.fixture
def good_baseline() -> Any:
    from app.fleet import benchmark_manager

    bm = benchmark_manager.get_benchmark_manager()
    baseline = BenchmarkResult(
        agent_name="g6_role",
        objectives={"benchmark_score": 1.0, "sample_count": 50.0},
    )
    with patch.object(bm, "_get_baseline", return_value=baseline):
        yield bm


def _check(runs: list[RunMetrics], bm: Any) -> bool:
    with patch.object(bm, "_collector", _collector(runs)):
        with patch(
            "app.fleet.metrics.get_metrics_collector", return_value=_collector(runs)
        ):
            return _regressed_under_deployed_prompt("g6_role", DEPLOYED.isoformat())


def test_bad_runs_from_before_the_deploy_do_not_count(good_baseline: Any) -> None:
    before = [_run(DEPLOYED - timedelta(hours=h), good=False) for h in range(1, 10)]
    after = [_run(DEPLOYED + timedelta(hours=h), good=True) for h in range(1, 7)]
    assert _check(before + after, good_baseline) is False


def test_too_few_runs_under_the_new_prompt_never_roll_back(good_baseline: Any) -> None:
    after = [_run(DEPLOYED + timedelta(hours=h), good=False) for h in range(1, 3)]
    assert _check(after, good_baseline) is False  # 2 runs < BENCHMARK_MIN_SAMPLES


def test_a_real_drop_under_the_new_prompt_rolls_back(good_baseline: Any) -> None:
    after = [_run(DEPLOYED + timedelta(hours=h), good=False) for h in range(1, 9)]
    assert _check(after, good_baseline) is True


@pytest.mark.asyncio
async def test_every_automatic_rollback_is_audited() -> None:
    gate = SimpleNamespace(
        agent_name="g6_role",
        blocked=True,
        report=SimpleNamespace(current_score=0.4, baseline_score=0.9, delta=-0.5),
    )
    detector = MagicMock()
    detector.check_fleet.return_value = [gate]
    registry = MagicMock()
    registry.get_deployed.return_value = SimpleNamespace(
        id=2, deployed_at=DEPLOYED.isoformat()
    )
    registry.rollback.return_value = SimpleNamespace(version_number=1)
    db = AsyncMock()

    class _Ctx:
        async def __aenter__(self) -> Any:
            return db

        async def __aexit__(self, *a: Any) -> None:
            return None

    with (
        patch(
            "app.fleet.regression_detector.get_regression_detector",
            return_value=detector,
        ),
        patch("app.fleet.prompt_registry.get_prompt_registry", return_value=registry),
        patch("app.db.session.get_session_factory", return_value=lambda: _Ctx()),
        patch("app.db.repository.get_setting", new=AsyncMock(return_value=None)),
        patch("app.db.repository.set_setting", new=AsyncMock()),
        patch("app.main._regressed_under_deployed_prompt", return_value=True),
        patch("app.fleet.audit_log.audit") as audit,
    ):
        await _run_prompt_auto_rollback_once()

    audit.assert_called_once()
    assert audit.call_args.kwargs["action_type"] == "prompt_auto_rollback"
    assert "version 1" in audit.call_args.kwargs["description"]

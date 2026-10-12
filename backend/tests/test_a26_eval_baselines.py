"""Sol A26 (2026-10-12): a task the judge could not grade is "unassessed",
never passed, and eval results are kept as versioned baselines that a
later run is compared with.

Before: when the LLM judge failed (network, quota, malformed reply), a task
stayed passed on its schema checks alone, so unproven quality was reported
as proven; and the only "regression gate" compared a deliberately regressed
fixture, not this codebase against what it achieved before. No AI runs.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.evals.eval_runner import (
    EvalResult,
    apply_judge,
    compare_with_baseline,
    latest_baseline,
    print_summary,
    save_baseline,
)


def _result(eval_id: str, passed: bool = True, score: float = 1.0) -> EvalResult:
    return EvalResult(
        eval_id=eval_id,
        agent="research",
        passed=passed,
        score=score,
        checks_passed=1,
        checks_total=1,
        elapsed_seconds=1.0,
        tokens_in=1,
        tokens_out=1,
    )


def test_a_task_the_judge_could_not_grade_is_unassessed_not_passed(capsys) -> None:  # type: ignore[no-untyped-def]
    scored = _result("t1")
    task = {"id": "t1", "quality_checks": ["names a real library"]}
    agent_result = SimpleNamespace(status="completed", raw={"x": 1}, summary="s")
    with patch(
        "tests.evals.eval_runner.judge_quality_checks",
        side_effect=TimeoutError("judge timed out"),
    ):
        apply_judge(task, agent_result, scored)
    assert scored.assessed is False and scored.passed is False
    print_summary([scored, _result("t2")])
    out = capsys.readouterr().out
    assert "1/2 passed, 1 unassessed" in out


def test_baselines_are_versioned_and_compared(tmp_path: Path) -> None:
    first = save_baseline([_result("a"), _result("b", score=0.9)], tmp_path)
    assert first.name.startswith("baseline_") and '"commit"' in first.read_text()
    baseline = latest_baseline(tmp_path)
    assert baseline is not None
    now = [_result("a", passed=False, score=0.0), _result("b", score=0.5)]
    regressions = compare_with_baseline(now, baseline)
    assert any(r.startswith("a: passed in") for r in regressions)
    assert any(r.startswith("b: score 0.90 -> 0.50") for r in regressions)


def test_unassessed_runs_are_never_compared(tmp_path: Path) -> None:
    save_baseline([_result("a")], tmp_path)
    unjudged = _result("a", passed=False, score=0.0)
    unjudged.assessed = False
    baseline = latest_baseline(tmp_path)
    assert baseline is not None
    assert compare_with_baseline([unjudged], baseline) == []

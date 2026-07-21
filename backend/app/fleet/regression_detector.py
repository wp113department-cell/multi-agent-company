"""Regression Detector — Day 11.

No repo in /repos implements "compare against a stored baseline, block on
decline" (verified: swe-agent's reviewer.py does variance-reduction over N
samples of the same run, not baseline comparison; autogen's MagenticOne stall
detection is in-run progress tracking, not cross-run). That mechanism already
exists in this codebase — Day 10's benchmark_manager.compare_to_baseline().

This module does not reimplement comparison logic. It is a thin deploy-time
gate: the concrete answer to "tests passing alone is NOT sufficient" — it runs
independently of pytest, wired into prompt_registry.deploy().
"""

from __future__ import annotations

from dataclasses import dataclass

from app.fleet.benchmark_manager import (
    BenchmarkManager,
    RegressionReport,
    get_benchmark_manager,
)


@dataclass
class RegressionGate:
    agent_name: str
    blocked: bool
    reason: str
    report: RegressionReport


class DeploymentBlocked(Exception):
    def __init__(self, agent_name: str, reason: str, report: RegressionReport) -> None:
        self.agent_name = agent_name
        self.reason = reason
        self.report = report
        super().__init__(f"Deployment blocked for {agent_name!r}: {reason}")


def _build_reason(report: RegressionReport) -> str:
    if not report.is_regression:
        return "no regression detected"
    worsened = sorted(
        (
            (k, v)
            for k, v in report.per_objective_delta.items()
            if k != "benchmark_score" and v < 0
        ),
        key=lambda kv: kv[1],
    )
    if not worsened:
        return f"benchmark_score dropped {report.delta:.3f} (baseline={report.baseline_score})"
    detail = ", ".join(f"{k} {v:+.3f}" for k, v in worsened)
    return (
        f"benchmark_score dropped {report.delta:.3f} — regressed objectives: {detail}"
    )


class RegressionDetector:
    def __init__(self, benchmark_manager: BenchmarkManager | None = None) -> None:
        self._bm = benchmark_manager or get_benchmark_manager()

    def check_agent(self, agent_name: str, n: int = 20) -> RegressionGate:
        report = self._bm.compare_to_baseline(agent_name, n=n)
        return RegressionGate(
            agent_name=agent_name,
            blocked=report.is_regression,
            reason=_build_reason(report),
            report=report,
        )

    def gate_deploy(self, agent_name: str, n: int = 20) -> None:
        """Raise DeploymentBlocked if agent_name has regressed against its stored
        baseline. Call this before any deploy/promote action — independent of
        whatever the test suite says."""
        gate = self.check_agent(agent_name, n=n)
        if gate.blocked:
            raise DeploymentBlocked(agent_name, gate.reason, gate.report)

    def check_fleet(self, n: int = 20) -> list[RegressionGate]:
        from app.fleet.capability_registry import get_capability_registry

        return [
            self.check_agent(cap.name, n=n) for cap in get_capability_registry().all()
        ]


_regression_detector_singleton: RegressionDetector | None = None


def get_regression_detector() -> RegressionDetector:
    global _regression_detector_singleton
    if _regression_detector_singleton is None:
        _regression_detector_singleton = RegressionDetector()
    return _regression_detector_singleton

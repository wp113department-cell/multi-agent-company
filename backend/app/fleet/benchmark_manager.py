"""Benchmark Manager — Day 10.

Computes 7 objectives per agent from real MetricsCollector data (grounded
against what's actually computable, not guessed):
  latency_p50, tool_accuracy, verification_coverage, retry_success,
  compile_success, hallucination_rate, benchmark_score (composite)

Baselines are stored in Postgres (agent_benchmarks table, migration 012) —
an in-process-only store would lose regression history on every restart,
defeating the point. Fixture-repos-per-agent-type are explicitly deferred:
this measures real production runs, not synthetic scenarios, until enough
real data exists to justify fixtures.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.fleet.metrics import MetricsCollector, RunMetrics, get_metrics_collector

_COMPILE_TOOLS = ("run_tests", "run_linter")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class BenchmarkResult:
    agent_name: str
    objectives: dict[str, float]
    timestamp: str = field(default_factory=_now_iso)


@dataclass
class RegressionReport:
    agent_name: str
    is_regression: bool
    current_score: float
    baseline_score: float | None
    delta: float
    per_objective_delta: dict[str, float]


def _new_isolated_db_engine() -> Any:
    """A throwaway async engine, never the shared app.db.session singleton —
    see feedback_asyncio_isolated_engine: reusing one engine across multiple
    asyncio.run() calls in the same process raises 'attached to a different
    loop'. A fresh, disposed-after-use engine per call is always correct."""
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def _write_baseline(agent_name: str, objectives: dict[str, float]) -> None:
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import AgentBenchmark

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(
                update(AgentBenchmark)
                .where(
                    AgentBenchmark.agent_name == agent_name,
                    AgentBenchmark.is_baseline.is_(True),
                )
                .values(is_baseline=False)
            )
            session.add(
                AgentBenchmark(
                    agent_name=agent_name, objectives=objectives, is_baseline=True
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _read_baseline(agent_name: str) -> BenchmarkResult | None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import AgentBenchmark

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = (
                await session.execute(
                    select(AgentBenchmark)
                    .where(
                        AgentBenchmark.agent_name == agent_name,
                        AgentBenchmark.is_baseline.is_(True),
                    )
                    .order_by(AgentBenchmark.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return BenchmarkResult(
                agent_name=agent_name,
                objectives=dict(row.objectives),
                timestamp=row.created_at.isoformat(),
            )
    finally:
        await engine.dispose()


class BenchmarkManager:
    def __init__(self, collector: MetricsCollector | None = None) -> None:
        self._collector = collector or get_metrics_collector()
        self._baseline_cache: dict[str, BenchmarkResult] = {}

    def _latency_score(self, p50_ms: float | None) -> float:
        s = get_settings()
        if p50_ms is None:
            return 1.0  # no data yet — benign default, consistent with the other "no data" objectives
        target = s.benchmark_latency_target_ms
        if p50_ms <= target:
            return 1.0
        if p50_ms >= 2 * target:
            return 0.0
        return 1.0 - (p50_ms - target) / target

    def _compute_objectives(
        self, agent_name: str, runs: list[RunMetrics]
    ) -> dict[str, float]:
        s = get_settings()

        p50 = self._collector.p50_latency_ms(agent_name)
        tool_accuracy = self._collector.avg_tool_accuracy(agent_name)
        if tool_accuracy is None:
            tool_accuracy = (
                1.0  # no tool calls recorded — nothing to be inaccurate about
            )

        verification_coverage = (
            sum(m.verification_pct for m in runs) / len(runs) if runs else 1.0
        )

        retried_runs = [m for m in runs if m.retries > 0]
        retry_success = (
            sum(1 for m in retried_runs if m.status == "completed") / len(retried_runs)
            if retried_runs
            else 1.0  # no retries needed — vacuously successful
        )

        compile_calls = [
            tc for m in runs for tc in m.tool_calls if tc.tool_name in _COMPILE_TOOLS
        ]
        compile_success = (
            sum(1 for tc in compile_calls if tc.success) / len(compile_calls)
            if compile_calls
            else 1.0  # no compile/test tool calls this window — nothing failed
        )

        # Conservative hallucination-rate proxy: fraction of runs where
        # reflection_node judged its own tool output unsatisfactory at least
        # once. Approximation, not ground truth — documented in DAY10_PLAN.md.
        hallucination_rate = (
            sum(1 for m in runs if m.reflection_unsatisfied > 0) / len(runs)
            if runs
            else 0.0
        )

        latency_score = self._latency_score(p50)
        benchmark_score = (
            s.benchmark_weight_latency * latency_score
            + s.benchmark_weight_tool_accuracy * tool_accuracy
            + s.benchmark_weight_verification_coverage * verification_coverage
            + s.benchmark_weight_retry_success * retry_success
            + s.benchmark_weight_compile_success * compile_success
            + s.benchmark_weight_hallucination * (1.0 - hallucination_rate)
        )

        return {
            "latency_p50": p50 if p50 is not None else 0.0,
            "tool_accuracy": tool_accuracy,
            "verification_coverage": verification_coverage,
            "retry_success": retry_success,
            "compile_success": compile_success,
            "hallucination_rate": hallucination_rate,
            "benchmark_score": benchmark_score,
        }

    def run_benchmark(self, agent_name: str, n: int = 20) -> BenchmarkResult:
        runs = self._collector.by_agent(agent_name, n)
        objectives = self._compute_objectives(agent_name, runs)
        return BenchmarkResult(agent_name=agent_name, objectives=objectives)

    def store_baseline(self, agent_name: str, result: BenchmarkResult) -> None:
        """Persist as the new baseline. Flips any prior baseline row for this
        agent to is_baseline=False rather than deleting it — history stays
        append-only for audit."""
        asyncio.run(_write_baseline(agent_name, result.objectives))
        self._baseline_cache[agent_name] = result

    def _get_baseline(self, agent_name: str) -> BenchmarkResult | None:
        if agent_name in self._baseline_cache:
            return self._baseline_cache[agent_name]
        result = asyncio.run(_read_baseline(agent_name))
        if result is not None:
            self._baseline_cache[agent_name] = result
        return result

    def compare_to_baseline(self, agent_name: str, n: int = 20) -> RegressionReport:
        s = get_settings()
        current = self.run_benchmark(agent_name, n=n)
        baseline = self._get_baseline(agent_name)

        if baseline is None:
            return RegressionReport(
                agent_name=agent_name,
                is_regression=False,
                current_score=current.objectives["benchmark_score"],
                baseline_score=None,
                delta=0.0,
                per_objective_delta={},
            )

        current_score = current.objectives["benchmark_score"]
        baseline_score = baseline.objectives["benchmark_score"]
        delta = current_score - baseline_score
        fractional_drop = (-delta / baseline_score) if baseline_score > 0 else 0.0
        is_regression = fractional_drop > s.benchmark_regression_threshold

        per_objective_delta = {
            key: current.objectives.get(key, 0.0) - baseline.objectives.get(key, 0.0)
            for key in current.objectives
        }

        return RegressionReport(
            agent_name=agent_name,
            is_regression=is_regression,
            current_score=current_score,
            baseline_score=baseline_score,
            delta=delta,
            per_objective_delta=per_objective_delta,
        )


_benchmark_manager_singleton: BenchmarkManager | None = None


def get_benchmark_manager() -> BenchmarkManager:
    global _benchmark_manager_singleton
    if _benchmark_manager_singleton is None:
        _benchmark_manager_singleton = BenchmarkManager()
    return _benchmark_manager_singleton

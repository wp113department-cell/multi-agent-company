"""Day 10 — benchmark_manager.py: 7 objectives computed from real MetricsCollector
data, baseline persistence (Postgres, migration 012), and regression detection.

Uses a fresh in-process MetricsCollector per test (never the process singleton)
so seeded runs don't leak between tests. Baseline rows ARE written to the real
dev DB (agent_benchmarks table) — every test that calls store_baseline cleans
up its own rows in a try/finally, following the same pattern already
established for Day 9's enhancement_requests tests.
"""
from __future__ import annotations

import asyncio

import pytest

from app.config import get_settings
from app.fleet.benchmark_manager import BenchmarkManager, get_benchmark_manager
from app.fleet.metrics import MetricsCollector


def _delete_benchmarks(agent_name: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.models import AgentBenchmark

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(delete(AgentBenchmark).where(AgentBenchmark.agent_name == agent_name))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_run_benchmark_with_no_runs_uses_benign_defaults() -> None:
    bm = BenchmarkManager(MetricsCollector())
    result = bm.run_benchmark("td_bm_no_data_agent")

    assert result.objectives["latency_p50"] == 0.0
    assert result.objectives["tool_accuracy"] == 1.0
    assert result.objectives["verification_coverage"] == 1.0
    assert result.objectives["retry_success"] == 1.0
    assert result.objectives["compile_success"] == 1.0
    assert result.objectives["hallucination_rate"] == 0.0
    assert 0.0 < result.objectives["benchmark_score"] <= 1.0


def test_run_benchmark_computes_tool_accuracy_and_verification_coverage() -> None:
    collector = MetricsCollector()
    bm = BenchmarkManager(collector)

    m1 = collector.start_run("td_bm_agent_a", trace_id="a1")
    m1.verification_pct = 1.0
    m1.record_tool("read_file", True, 10.0)

    m2 = collector.start_run("td_bm_agent_a", trace_id="a2")
    m2.verification_pct = 0.0
    m2.record_tool("read_file", False, 10.0, "boom")

    result = bm.run_benchmark("td_bm_agent_a")
    assert result.objectives["tool_accuracy"] == 0.5
    assert result.objectives["verification_coverage"] == 0.5


def test_run_benchmark_retry_success_only_counts_retried_runs() -> None:
    collector = MetricsCollector()
    bm = BenchmarkManager(collector)

    m1 = collector.start_run("td_bm_agent_b", trace_id="b1")
    m1.retries = 0
    m1.finish("completed")

    m2 = collector.start_run("td_bm_agent_b", trace_id="b2")
    m2.retries = 2
    m2.finish("failed")

    m3 = collector.start_run("td_bm_agent_b", trace_id="b3")
    m3.retries = 1
    m3.finish("completed")

    result = bm.run_benchmark("td_bm_agent_b")
    # Only b2 and b3 had retries; 1 of 2 ended completed.
    assert result.objectives["retry_success"] == 0.5


def test_run_benchmark_compile_success_only_counts_test_and_lint_tool_calls() -> None:
    collector = MetricsCollector()
    bm = BenchmarkManager(collector)

    m = collector.start_run("td_bm_agent_c", trace_id="c1")
    m.record_tool("run_tests", True, 100.0)
    m.record_tool("run_linter", False, 50.0, "lint error")
    m.record_tool("read_file", False, 5.0, "irrelevant failure")  # must not count

    result = bm.run_benchmark("td_bm_agent_c")
    assert result.objectives["compile_success"] == 0.5


def test_run_benchmark_hallucination_rate_from_reflection_unsatisfied() -> None:
    collector = MetricsCollector()
    bm = BenchmarkManager(collector)

    m1 = collector.start_run("td_bm_agent_d", trace_id="d1")
    m1.reflection_unsatisfied = 0

    m2 = collector.start_run("td_bm_agent_d", trace_id="d2")
    m2.reflection_unsatisfied = 2

    result = bm.run_benchmark("td_bm_agent_d")
    assert result.objectives["hallucination_rate"] == 0.5


def test_latency_score_perfect_at_or_under_target_zero_at_double() -> None:
    s = get_settings()
    bm = BenchmarkManager(MetricsCollector())

    assert bm._latency_score(None) == 1.0
    assert bm._latency_score(s.benchmark_latency_target_ms) == 1.0
    assert bm._latency_score(2 * s.benchmark_latency_target_ms) == 0.0
    mid = bm._latency_score(1.5 * s.benchmark_latency_target_ms)
    assert 0.0 < mid < 1.0


def test_store_and_compare_to_baseline_no_regression_on_identical_data() -> None:
    agent_name = "td_bm_agent_baseline_stable"
    try:
        collector = MetricsCollector()
        bm = BenchmarkManager(collector)
        m = collector.start_run(agent_name, trace_id="stable1")
        m.verification_pct = 1.0
        m.record_tool("run_tests", True, 50.0)

        baseline_result = bm.run_benchmark(agent_name)
        bm.store_baseline(agent_name, baseline_result)

        report = bm.compare_to_baseline(agent_name)
        assert report.baseline_score == baseline_result.objectives["benchmark_score"]
        assert report.is_regression is False
        assert report.delta == pytest.approx(0.0)
    finally:
        _delete_benchmarks(agent_name)


def test_compare_to_baseline_flags_regression_on_degraded_run() -> None:
    agent_name = "td_bm_agent_regression"
    try:
        collector = MetricsCollector()
        bm = BenchmarkManager(collector)

        m_good = collector.start_run(agent_name, trace_id="good1")
        m_good.verification_pct = 1.0
        m_good.record_tool("run_tests", True, 50.0)
        m_good.execution_time_ms = 1000.0
        good_result = bm.run_benchmark(agent_name)
        bm.store_baseline(agent_name, good_result)

        m_bad = collector.start_run(agent_name, trace_id="bad1")
        m_bad.verification_pct = 0.0
        m_bad.record_tool("run_tests", False, 50.0, "fail")
        m_bad.record_tool("run_linter", False, 50.0, "fail")
        m_bad.reflection_unsatisfied = 1
        m_bad.execution_time_ms = 999_999.0

        report = bm.compare_to_baseline(agent_name)
        assert report.is_regression is True
        assert report.delta < 0
        assert report.per_objective_delta["tool_accuracy"] < 0
    finally:
        _delete_benchmarks(agent_name)


def test_compare_to_baseline_with_no_stored_baseline_is_not_a_regression() -> None:
    agent_name = "td_bm_agent_never_baselined"
    bm = BenchmarkManager(MetricsCollector())
    report = bm.compare_to_baseline(agent_name)
    assert report.is_regression is False
    assert report.baseline_score is None


def test_store_baseline_flips_prior_baseline_row_instead_of_deleting() -> None:
    agent_name = "td_bm_agent_history"
    try:
        collector = MetricsCollector()
        bm = BenchmarkManager(collector)

        m1 = collector.start_run(agent_name, trace_id="h1")
        m1.verification_pct = 0.2
        result1 = bm.run_benchmark(agent_name)
        bm.store_baseline(agent_name, result1)

        m2 = collector.start_run(agent_name, trace_id="h2")
        m2.verification_pct = 0.9
        result2 = bm.run_benchmark(agent_name)
        bm.store_baseline(agent_name, result2)

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.db.models import AgentBenchmark

        async def _query() -> tuple[int, int]:
            engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    total = (
                        await session.execute(
                            select(AgentBenchmark).where(AgentBenchmark.agent_name == agent_name)
                        )
                    ).scalars().all()
                    baselines = [r for r in total if r.is_baseline]
                    return len(total), len(baselines)
            finally:
                await engine.dispose()

        total_count, baseline_count = asyncio.run(_query())
        assert total_count == 2  # append-only history, both rows kept
        assert baseline_count == 1  # only the most recent is marked active
    finally:
        _delete_benchmarks(agent_name)


def test_get_benchmark_manager_returns_singleton() -> None:
    assert get_benchmark_manager() is get_benchmark_manager()

"""Day 11 — regression_detector.py: a thin deploy-time gate wrapping Day 10's
benchmark_manager.compare_to_baseline(). No new comparison logic — this only
tests the gate/wrapper behavior (blocked flag, reason text, DeploymentBlocked
exception, fleet-wide check), since the underlying comparison math is already
covered by test_benchmark_manager.py.

Real Postgres round-trip via BenchmarkManager.store_baseline() — every test
cleans up its own agent_benchmarks rows in a try/finally.
"""
from __future__ import annotations

import asyncio

import pytest

from app.fleet.benchmark_manager import BenchmarkManager
from app.fleet.metrics import MetricsCollector
from app.fleet.regression_detector import (
    DeploymentBlocked,
    RegressionDetector,
    get_regression_detector,
)


def _delete_benchmarks(agent_name: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
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


def test_check_agent_not_blocked_with_no_baseline() -> None:
    rd = RegressionDetector(BenchmarkManager(MetricsCollector()))
    gate = rd.check_agent("td_rd_never_baselined")
    assert gate.blocked is False
    assert gate.report.baseline_score is None


def test_check_agent_not_blocked_when_stable() -> None:
    agent_name = "td_rd_stable"
    try:
        collector = MetricsCollector()
        bm = BenchmarkManager(collector)
        rd = RegressionDetector(bm)

        m = collector.start_run(agent_name, trace_id="s1")
        m.verification_pct = 1.0
        result = bm.run_benchmark(agent_name)
        bm.store_baseline(agent_name, result)

        gate = rd.check_agent(agent_name)
        assert gate.blocked is False
        assert gate.reason == "no regression detected"
    finally:
        _delete_benchmarks(agent_name)


def test_check_agent_blocked_and_reason_lists_regressed_objectives() -> None:
    agent_name = "td_rd_degraded"
    try:
        collector = MetricsCollector()
        bm = BenchmarkManager(collector)
        rd = RegressionDetector(bm)

        m_good = collector.start_run(agent_name, trace_id="g1")
        m_good.verification_pct = 1.0
        m_good.record_tool("run_tests", True, 50.0)
        good = bm.run_benchmark(agent_name)
        bm.store_baseline(agent_name, good)

        m_bad = collector.start_run(agent_name, trace_id="b1")
        m_bad.verification_pct = 0.0
        m_bad.record_tool("run_tests", False, 50.0, "fail")

        gate = rd.check_agent(agent_name)
        assert gate.blocked is True
        assert "regressed objectives" in gate.reason
        assert "verification_coverage" in gate.reason
        assert "tool_accuracy" in gate.reason
    finally:
        _delete_benchmarks(agent_name)


def test_gate_deploy_raises_deployment_blocked_on_regression() -> None:
    agent_name = "td_rd_gate_deploy"
    try:
        collector = MetricsCollector()
        bm = BenchmarkManager(collector)
        rd = RegressionDetector(bm)

        m_good = collector.start_run(agent_name, trace_id="gd1")
        m_good.verification_pct = 1.0
        good = bm.run_benchmark(agent_name)
        bm.store_baseline(agent_name, good)

        m_bad = collector.start_run(agent_name, trace_id="gd2")
        m_bad.verification_pct = 0.0
        m_bad.reflection_unsatisfied = 1

        with pytest.raises(DeploymentBlocked) as exc_info:
            rd.gate_deploy(agent_name)
        assert exc_info.value.agent_name == agent_name
        assert exc_info.value.report.is_regression is True
    finally:
        _delete_benchmarks(agent_name)


def test_gate_deploy_does_not_raise_when_no_regression() -> None:
    agent_name = "td_rd_gate_deploy_ok"
    try:
        collector = MetricsCollector()
        bm = BenchmarkManager(collector)
        rd = RegressionDetector(bm)

        m = collector.start_run(agent_name, trace_id="ok1")
        m.verification_pct = 1.0
        result = bm.run_benchmark(agent_name)
        bm.store_baseline(agent_name, result)

        rd.gate_deploy(agent_name)  # must not raise
    finally:
        _delete_benchmarks(agent_name)


def test_check_fleet_returns_a_gate_per_registered_agent() -> None:
    from app.fleet.capability_registry import AgentCapability, get_capability_registry

    get_capability_registry().register(
        AgentCapability(
            name="td_rd_fleet_agent",
            description="test",
            tools=[],
            input_types=["text"],
            output_types=["text"],
            capabilities=["td_rd_fleet_cap"],
        )
    )

    rd = RegressionDetector(BenchmarkManager(MetricsCollector()))
    gates = rd.check_fleet()
    assert any(g.agent_name == "td_rd_fleet_agent" for g in gates)


def test_get_regression_detector_returns_singleton() -> None:
    assert get_regression_detector() is get_regression_detector()

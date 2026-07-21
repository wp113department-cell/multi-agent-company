"""Gap-closure (2026-07-21) — Day 10 built benchmark_manager.store_baseline()
but nothing ever called it automatically; no real agent has ever had a
baseline, meaning regression_detector's gate was a no-op for everyone by
design ("no baseline" = "no regression"). This tests the new
_benchmark_baseline_loop() actually populates baselines for agents with real
runs and skips agents with none — using the same "let asyncio.sleep fire
once then cancel" technique as test_lesson_archive_loop.py.

Plain sync test functions (not @pytest.mark.asyncio) driving asyncio.run()
directly — mixing an async test with a sync asyncio.run()-based cleanup
helper hits the exact "asyncio.run() cannot be called from a running event
loop" bug documented in Day 13's own gap-closure notes; caught by running
this file, not assumed safe.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.fleet.benchmark_manager import get_benchmark_manager
from app.fleet.capability_registry import AgentCapability, get_capability_registry, register
from app.fleet.metrics import get_metrics_collector
from app.main import _benchmark_baseline_loop


def _cleanup_benchmark(agent_name: str) -> None:
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


def _existing_baseline_agent_names() -> set[str]:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import AgentBenchmark

    async def _run() -> set[str]:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                rows = (
                    await session.execute(select(AgentBenchmark.agent_name).where(AgentBenchmark.is_baseline.is_(True)))
                ).scalars().all()
                return set(rows)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _run_loop_once(own_agent_name: str) -> None:
    """Runs the REAL _benchmark_baseline_loop(), which sweeps EVERY agent in
    the process-wide capability_registry — not scoped to this test's own
    fixture agent. Other tests earlier in the same pytest session (e.g. Day
    12's pipeline tests) leave real MetricsCollector data for real agents
    like "pm"/"architect"/"decomposer"; without this before/after cleanup,
    every run of this file would create permanent baseline rows for them —
    confirmed by running the full suite, not assumed safe."""
    before = _existing_baseline_agent_names()

    call_count = {"n": 0}

    async def _sleep_once_then_cancel(*args: object, **kwargs: object) -> None:
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise asyncio.CancelledError()

    async def _drive() -> None:
        with patch("asyncio.sleep", side_effect=_sleep_once_then_cancel):
            with pytest.raises(asyncio.CancelledError):
                await _benchmark_baseline_loop()

    asyncio.run(_drive())

    after = _existing_baseline_agent_names()
    incidental = after - before - {own_agent_name}
    for agent_name in incidental:
        _cleanup_benchmark(agent_name)


def test_baseline_loop_stores_baseline_for_agent_with_real_runs() -> None:
    agent_name = "td_bbl_agent_with_runs"
    try:
        register(AgentCapability(
            name=agent_name, description="t", tools=[], input_types=[], output_types=[],
            capabilities=["td_bbl_cap"],
        ))
        m = get_metrics_collector().start_run(agent_name, trace_id="td-bbl-1")
        m.verification_pct = 1.0

        _run_loop_once(agent_name)

        report = get_benchmark_manager().compare_to_baseline(agent_name)
        assert report.baseline_score is not None
    finally:
        _cleanup_benchmark(agent_name)


def test_baseline_loop_skips_agent_with_no_runs() -> None:
    agent_name = "td_bbl_agent_no_runs"
    try:
        register(AgentCapability(
            name=agent_name, description="t", tools=[], input_types=[], output_types=[],
            capabilities=["td_bbl_cap_2"],
        ))

        _run_loop_once(agent_name)

        report = get_benchmark_manager().compare_to_baseline(agent_name)
        assert report.baseline_score is None  # nothing stored — no real runs to base it on
    finally:
        _cleanup_benchmark(agent_name)


def test_baseline_loop_does_not_overwrite_existing_baseline() -> None:
    agent_name = "td_bbl_agent_existing_baseline"
    try:
        register(AgentCapability(
            name=agent_name, description="t", tools=[], input_types=[], output_types=[],
            capabilities=["td_bbl_cap_3"],
        ))
        bm = get_benchmark_manager()
        collector = get_metrics_collector()

        m1 = collector.start_run(agent_name, trace_id="td-bbl-3a")
        m1.verification_pct = 1.0
        first_result = bm.run_benchmark(agent_name)
        bm.store_baseline(agent_name, first_result)

        m2 = collector.start_run(agent_name, trace_id="td-bbl-3b")
        m2.verification_pct = 0.0  # would look like a regression if a NEW baseline got stored from this

        _run_loop_once(agent_name)

        report = bm.compare_to_baseline(agent_name)
        assert report.baseline_score == first_result.objectives["benchmark_score"]
    finally:
        _cleanup_benchmark(agent_name)


def test_baseline_loop_disabled_when_interval_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "benchmark_baseline_interval_hours", 0)
    asyncio.run(_benchmark_baseline_loop())  # returns immediately, never sleeps, never raises

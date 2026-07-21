"""Day 10 — budget_manager.py: live per-run + daily cumulative spend enforcement.

Two-tier design (per-run + daily cumulative), following swe-agent's
per_instance_cost_limit / total_cost_limit pattern. Uses a fresh
MetricsCollector per test so daily-cost aggregation isn't polluted by other
tests or the process-wide singleton.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.fleet.budget_manager import BudgetExceeded, BudgetManager, get_budget_manager
from app.fleet.metrics import MetricsCollector, RunMetrics


def test_check_run_passes_when_under_all_limits() -> None:
    bm = BudgetManager(MetricsCollector())
    m = RunMetrics(trace_id="t1", agent_name="agent_x")
    m.record_tokens(100, 50)
    m.execution_time_ms = 1000.0
    bm.check_run(m)  # must not raise


def test_check_run_raises_on_token_overage() -> None:
    s = get_settings()
    bm = BudgetManager(MetricsCollector())
    m = RunMetrics(trace_id="t2", agent_name="agent_x")
    m.record_tokens(s.max_tokens_per_agent_run + 1, 0)

    with pytest.raises(BudgetExceeded) as exc_info:
        bm.check_run(m)
    assert exc_info.value.dimension == "tokens"
    assert exc_info.value.scope == "run"
    assert exc_info.value.actual == s.max_tokens_per_agent_run + 1


def test_check_run_raises_on_time_overage() -> None:
    s = get_settings()
    bm = BudgetManager(MetricsCollector())
    m = RunMetrics(trace_id="t3", agent_name="agent_x")
    m.execution_time_ms = (s.max_run_time_seconds + 5) * 1000

    with pytest.raises(BudgetExceeded) as exc_info:
        bm.check_run(m)
    assert exc_info.value.dimension == "time"
    assert exc_info.value.scope == "run"


def test_check_run_raises_on_memory_overage(monkeypatch: pytest.MonkeyPatch) -> None:
    bm = BudgetManager(MetricsCollector())
    m = RunMetrics(trace_id="t4", agent_name="agent_x")

    monkeypatch.setattr(
        "app.fleet.budget_manager._current_memory_mb", lambda: 999_999.0
    )

    with pytest.raises(BudgetExceeded) as exc_info:
        bm.check_run(m)
    assert exc_info.value.dimension == "memory"
    assert exc_info.value.scope == "run"
    assert exc_info.value.actual == 999_999.0


def test_check_daily_passes_when_under_limit() -> None:
    collector = MetricsCollector()
    bm = BudgetManager(collector)
    m = collector.start_run("agent_y")
    m.record_tokens(10, 10)

    bm.check_daily()  # must not raise
    bm.check_daily(agent_name="agent_y")  # must not raise


def test_check_daily_raises_when_cumulative_cost_exceeds_limit() -> None:
    s = get_settings()
    collector = MetricsCollector()
    bm = BudgetManager(collector)

    # Force enough tokens across several runs today to exceed COST_BUDGET_DAILY_USD.
    tokens_needed = int(s.cost_budget_daily_usd / s.cost_per_input_token) + 1000
    for i in range(3):
        m = collector.start_run("agent_z", trace_id=f"daily-{i}")
        m.record_tokens(tokens_needed // 3 + 1, 0)

    with pytest.raises(BudgetExceeded) as exc_info:
        bm.check_daily(agent_name="agent_z")
    assert exc_info.value.dimension == "cost"
    assert exc_info.value.scope == "daily"


def test_check_daily_ignores_runs_from_a_previous_day() -> None:
    s = get_settings()
    collector = MetricsCollector()
    bm = BudgetManager(collector)

    tokens_needed = int(s.cost_budget_daily_usd / s.cost_per_input_token) + 1000
    m = collector.start_run("agent_old", trace_id="yesterday-run")
    m.record_tokens(tokens_needed, 0)
    m.started_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    bm.check_daily(agent_name="agent_old")  # must not raise — that spend was yesterday


def test_check_daily_agent_filter_excludes_other_agents_spend() -> None:
    s = get_settings()
    collector = MetricsCollector()
    bm = BudgetManager(collector)

    tokens_needed = int(s.cost_budget_daily_usd / s.cost_per_input_token) + 1000
    m = collector.start_run("agent_big_spender", trace_id="big-spend")
    m.record_tokens(tokens_needed, 0)

    bm.check_daily(agent_name="agent_small_spender")  # must not raise — different agent


def test_get_budget_manager_returns_singleton() -> None:
    assert get_budget_manager() is get_budget_manager()


def test_budget_exceeded_str_message_is_informative() -> None:
    e = BudgetExceeded(dimension="tokens", scope="run", limit=100.0, actual=150.0)
    msg = str(e)
    assert "tokens" in msg
    assert "run" in msg
    assert "100.0" in msg
    assert "150.0" in msg

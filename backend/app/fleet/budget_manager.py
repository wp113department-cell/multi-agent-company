"""Budget Manager — Day 10.

Live enforcement against real spend/resource usage, complementary to (not a
replacement for):
- app/pipeline/concurrency.py — concurrency caps (how many run at once)
- app/pipeline/cost_controller.py — pre-flight cost *estimation* before an
  epic starts, gating human approval

BudgetManager checks actual RunMetrics after a run completes (per-run limits:
tokens, wall-clock time, memory) and cumulative spend across the process
(daily cost limit) — a two-tier design following swe-agent's
per_instance_cost_limit / total_cost_limit pattern
(repos/swe-agent/sweagent/agent/models.py).
"""
from __future__ import annotations

import resource
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import get_settings
from app.fleet.metrics import MetricsCollector, RunMetrics, get_metrics_collector


@dataclass
class BudgetExceeded(Exception):
    dimension: str  # "tokens" | "cost" | "time" | "memory"
    scope: str  # "run" | "daily"
    limit: float
    actual: float

    def __str__(self) -> str:
        return (
            f"Budget exceeded: {self.dimension} ({self.scope}) — "
            f"limit={self.limit}, actual={self.actual}"
        )


def _current_memory_mb() -> float:
    """Best-effort process-wide peak RSS (ru_maxrss), not per-run isolated
    memory — there is no cheap way to attribute memory to a single agent run
    inside one process. This is a coarse proxy, documented as such."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _is_same_utc_day(iso_timestamp: str, today: datetime) -> bool:
    try:
        ts = datetime.fromisoformat(iso_timestamp)
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).date() == today.date()


class BudgetManager:
    def __init__(self, collector: MetricsCollector | None = None) -> None:
        self._collector = collector or get_metrics_collector()

    def check_run(self, metrics: RunMetrics) -> None:
        """Raise BudgetExceeded if this single completed run is over its
        per-run limits (tokens, wall-clock time, memory)."""
        s = get_settings()

        total_tokens = metrics.tokens_in + metrics.tokens_out
        if total_tokens > s.max_tokens_per_agent_run:
            raise BudgetExceeded("tokens", "run", float(s.max_tokens_per_agent_run), float(total_tokens))

        run_time_seconds = metrics.execution_time_ms / 1000
        if run_time_seconds > s.max_run_time_seconds:
            raise BudgetExceeded("time", "run", float(s.max_run_time_seconds), run_time_seconds)

        mem_mb = _current_memory_mb()
        if mem_mb > s.max_memory_mb:
            raise BudgetExceeded("memory", "run", float(s.max_memory_mb), mem_mb)

    def check_daily(self, agent_name: str | None = None) -> None:
        """Raise BudgetExceeded if cumulative cost today (across the process's
        in-memory MetricsCollector ring, optionally filtered to one agent)
        exceeds COST_BUDGET_DAILY_USD."""
        s = get_settings()
        today = datetime.now(timezone.utc)
        total_cost = sum(
            m.cost_estimate_usd
            for m in self._collector.all_runs()
            if (agent_name is None or m.agent_name == agent_name) and _is_same_utc_day(m.started_at, today)
        )
        if total_cost > s.cost_budget_daily_usd:
            raise BudgetExceeded("cost", "daily", s.cost_budget_daily_usd, total_cost)


_budget_manager_singleton: BudgetManager | None = None


def get_budget_manager() -> BudgetManager:
    global _budget_manager_singleton
    if _budget_manager_singleton is None:
        _budget_manager_singleton = BudgetManager()
    return _budget_manager_singleton

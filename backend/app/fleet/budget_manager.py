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

import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import get_settings
from app.fleet.metrics import MetricsCollector, RunMetrics, get_metrics_collector

# `resource` is POSIX-only (no ru_maxrss/RUSAGE_SELF on Windows) — this
# blocked this module's import entirely on Windows, which in turn aborted
# pytest collection for the whole suite (found via real execution while
# setting up Windows-based test verification for Audit 04/05). ctypes is
# stdlib, so the Windows branch below adds no new dependency.
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    # Explicit argtypes/restype are required: ctypes' default (c_int) return
    # type for GetCurrentProcess() truncates the 64-bit pseudo-handle it
    # returns, so GetProcessMemoryInfo silently fails (returns 0) if called
    # with the untyped result. Confirmed via direct execution — the untyped
    # version always returned ok=0/peak=0 with no exception.
    ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    ctypes.windll.kernel32.GetCurrentProcess.argtypes = []
    ctypes.windll.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessMemoryCounters),
        wintypes.DWORD,
    ]
else:
    import resource


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
    """Best-effort process-wide peak RSS, not per-run isolated memory —
    there is no cheap way to attribute memory to a single agent run inside
    one process. This is a coarse proxy, documented as such."""
    if sys.platform == "win32":
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        )
        return (counters.PeakWorkingSetSize / (1024 * 1024)) if ok else 0.0
    # ru_maxrss is KB on Linux, bytes on macOS — this codebase's documented
    # prod target is Linux, so KB is assumed here (pre-existing behavior,
    # unchanged by this fix).
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
            raise BudgetExceeded(
                "tokens", "run", float(s.max_tokens_per_agent_run), float(total_tokens)
            )

        run_time_seconds = metrics.execution_time_ms / 1000
        if run_time_seconds > s.max_run_time_seconds:
            raise BudgetExceeded(
                "time", "run", float(s.max_run_time_seconds), run_time_seconds
            )

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
            if (agent_name is None or m.agent_name == agent_name)
            and _is_same_utc_day(m.started_at, today)
        )
        if total_cost > s.cost_budget_daily_usd:
            raise BudgetExceeded("cost", "daily", s.cost_budget_daily_usd, total_cost)

    def check_daily_db(self, agent_name: str | None = None) -> None:
        """Blocker (audit_v1.md 4.1 #4): check_daily() above sums from
        MetricsCollector's in-process `deque(maxlen=capacity)` — "since this
        process last restarted," not a real calendar-day limit; silently
        resets/fragments across restarts or multiple worker processes.
        This queries `agent_runs` directly (SUM(cost_estimate) WHERE
        started_at >= today), the real shared source of truth every worker
        process (and every restart) sees the same way.

        Sync facade over an async DB query — a fresh, disposed-after-use
        engine per call, never the shared app.db.session singleton (see
        fleet/failure_ladder.py's own _new_isolated_db_engine for the same
        pattern/reasoning: reusing one engine across independent
        asyncio.run()-style call boundaries raises "attached to a different
        loop"). Real callers (base_graph.py's post-run budget check) run
        inside a worker thread with no running event loop of its own
        (dispatched via asyncio.to_thread from manager.py), so asyncio.run()
        here is safe — never call this from a coroutine already running on
        an event loop.
        """
        import asyncio
        from datetime import datetime, timezone

        s = get_settings()

        async def _query() -> float:
            from sqlalchemy import func, select
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

            from app.db.models import AgentRun

            engine = create_async_engine(s.database_url, pool_pre_ping=True)
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    today_start = datetime.now(timezone.utc).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    stmt = select(
                        func.coalesce(func.sum(AgentRun.cost_estimate), 0)
                    ).where(AgentRun.started_at >= today_start)
                    if agent_name is not None:
                        stmt = stmt.where(AgentRun.agent_type == agent_name)
                    result = await session.execute(stmt)
                    return float(result.scalar_one())
            finally:
                await engine.dispose()

        total_cost = asyncio.run(_query())
        if total_cost > s.cost_budget_daily_usd:
            raise BudgetExceeded("cost", "daily", s.cost_budget_daily_usd, total_cost)


_budget_manager_singleton: BudgetManager | None = None


def get_budget_manager() -> BudgetManager:
    global _budget_manager_singleton
    if _budget_manager_singleton is None:
        _budget_manager_singleton = BudgetManager()
    return _budget_manager_singleton

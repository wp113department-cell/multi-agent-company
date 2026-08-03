"""Orchestration Analytics — Stage 2 Day 54 (answers.md Q8 "Orchestration
speed": NO — manager.py's epic-manager graph and pipeline/graph.py have no
dedicated orchestration-latency metric, only the whole-run execution_time_ms).

run_manager() spans multiple sub-agent dispatches (dev/QA/reviewer), each
under its own trace_id with its own RunMetrics entry — there is no single
per-run RunMetrics owner for the orchestration loop itself, so this mirrors
app/memory/analytics.py's own established pattern (Day 43) instead of trying
to force it through the trace_id-keyed RunMetrics mechanism: a simple
in-process rolling window, keyed by phase name, real wall-clock timings
recorded by run_manager()'s own two real call sites.
"""

from __future__ import annotations

from collections import deque

from app.config import get_settings

_orchestration_times: dict[str, deque[float]] = {}


def record_orchestration_time(phase_name: str, duration_ms: float) -> None:
    """Called by run_manager()'s real call sites after the real orchestration
    run completes. In-process only (resets on restart) — a rolling
    operational metric, not a durable audit trail."""
    settings = get_settings()
    window = _orchestration_times.get(phase_name)
    if window is None or window.maxlen != settings.orchestration_timing_window:
        window = deque(window or (), maxlen=settings.orchestration_timing_window)
        _orchestration_times[phase_name] = window
    window.append(duration_ms)


def get_orchestration_time_stats() -> dict[str, dict[str, float | int]]:
    stats: dict[str, dict[str, float | int]] = {}
    for name, samples in _orchestration_times.items():
        if not samples:
            continue
        stats[name] = {
            "count": len(samples),
            "avg_ms": round(sum(samples) / len(samples), 3),
            "min_ms": round(min(samples), 3),
            "max_ms": round(max(samples), 3),
        }
    return stats


def reset_orchestration_time_stats() -> None:
    """Test-only helper — mirrors memory/analytics.py's reset_retrieval_time_stats."""
    _orchestration_times.clear()

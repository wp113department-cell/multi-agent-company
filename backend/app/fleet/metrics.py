"""Run-level metrics and tracing — §18 of Master Prompt v4.

Every agent run logs:
  execution_time, tokens_in, tokens_out, cost_estimate, retries, failures,
  tool_calls[], verification_pct, memory_retrieved, memory_written,
  confidence, trace_id

Every run has a trace_id that correlates:
  - bus events
  - logs
  - approvals
  - checkpoints
  - rollbacks

A trace_id must allow replay of a failure into a coherent timeline.

Design decisions:
- RunMetrics is a plain dataclass, not a Pydantic model, so it never raises
  on construction and can always be created even in error paths.
- MetricsCollector is thread-safe and stores a fixed-size ring for in-process
  queries (dashboard, regression detection).
- Cost estimate uses the per-token rates from app.config so it matches the
  existing cost_controller.py accounting.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generator

_RING_CAPACITY = 1000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_trace() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ToolCallRecord:
    tool_name: str
    success: bool
    duration_ms: float
    error: str | None = None


@dataclass
class RunMetrics:
    """Metrics collected for a single agent run."""

    trace_id: str
    agent_name: str
    task_id: str | None = None

    # Timing
    started_at: str = field(default_factory=_now_iso)
    finished_at: str | None = None
    execution_time_ms: float = 0.0

    # LLM usage
    tokens_in: int = 0
    tokens_out: int = 0
    cost_estimate_usd: float = 0.0

    # Execution quality
    retries: int = 0
    failures: int = 0
    tool_calls: list[ToolCallRecord] = field(default_factory=list)

    # Verification
    verification_pct: float = 0.0

    # Memory
    memory_retrieved: int = 0
    memory_written: int = 0

    # Confidence (0.0 – 1.0, estimated by the agent at submit time)
    confidence: float = 1.0

    # Final outcome
    status: str = "running"

    def finish(self, status: str = "completed") -> None:
        self.finished_at = _now_iso()
        self.status = status

    def record_tool(self, tool_name: str, success: bool, duration_ms: float, error: str | None = None) -> None:
        self.tool_calls.append(ToolCallRecord(tool_name=tool_name, success=success, duration_ms=duration_ms, error=error))

    def record_tokens(self, tokens_in: int, tokens_out: int) -> None:
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self._recompute_cost()

    def _recompute_cost(self) -> None:
        try:
            from app.config import get_settings
            s = get_settings()
            self.cost_estimate_usd = (
                self.tokens_in * s.cost_per_input_token
                + self.tokens_out * s.cost_per_output_token
            )
        except Exception:
            pass

    @property
    def tool_accuracy(self) -> float:
        if not self.tool_calls:
            return 1.0
        success_count = sum(1 for t in self.tool_calls if t.success)
        return success_count / len(self.tool_calls)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "agent_name": self.agent_name,
            "task_id": self.task_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "execution_time_ms": self.execution_time_ms,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_estimate_usd": self.cost_estimate_usd,
            "retries": self.retries,
            "failures": self.failures,
            "tool_calls": [
                {"tool": t.tool_name, "success": t.success, "duration_ms": t.duration_ms, "error": t.error}
                for t in self.tool_calls
            ],
            "tool_accuracy": self.tool_accuracy,
            "verification_pct": self.verification_pct,
            "memory_retrieved": self.memory_retrieved,
            "memory_written": self.memory_written,
            "confidence": self.confidence,
            "status": self.status,
        }


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

class MetricsCollector:
    """Thread-safe ring buffer of RunMetrics with trace_id lookup."""

    def __init__(self, capacity: int = _RING_CAPACITY) -> None:
        self._ring: deque[RunMetrics] = deque(maxlen=capacity)
        self._index: dict[str, RunMetrics] = {}
        self._lock = threading.Lock()

    def start_run(self, agent_name: str, task_id: str | None = None, trace_id: str | None = None) -> RunMetrics:
        m = RunMetrics(
            trace_id=trace_id or _new_trace(),
            agent_name=agent_name,
            task_id=task_id,
        )
        with self._lock:
            self._ring.append(m)
            self._index[m.trace_id] = m
        return m

    def get(self, trace_id: str) -> RunMetrics | None:
        with self._lock:
            return self._index.get(trace_id)

    def recent(self, n: int = 20) -> list[RunMetrics]:
        with self._lock:
            return list(self._ring)[-n:]

    def by_agent(self, agent_name: str, n: int = 20) -> list[RunMetrics]:
        with self._lock:
            return [m for m in self._ring if m.agent_name == agent_name][-n:]

    def p50_latency_ms(self, agent_name: str) -> float | None:
        runs = [m.execution_time_ms for m in self.by_agent(agent_name) if m.execution_time_ms > 0]
        if not runs:
            return None
        runs.sort()
        return runs[len(runs) // 2]

    def p95_latency_ms(self, agent_name: str) -> float | None:
        runs = [m.execution_time_ms for m in self.by_agent(agent_name) if m.execution_time_ms > 0]
        if not runs:
            return None
        runs.sort()
        idx = int(len(runs) * 0.95)
        return runs[min(idx, len(runs) - 1)]

    def avg_tool_accuracy(self, agent_name: str) -> float | None:
        runs = self.by_agent(agent_name)
        accuracies = [m.tool_accuracy for m in runs if m.tool_calls]
        if not accuracies:
            return None
        return sum(accuracies) / len(accuracies)


# ---------------------------------------------------------------------------
# Context manager for automatic timing
# ---------------------------------------------------------------------------

@contextmanager
def run_span(
    agent_name: str,
    task_id: str | None = None,
    trace_id: str | None = None,
) -> Generator[RunMetrics, None, None]:
    """Usage:
        with run_span("bug_fix", task_id=str(task_id)) as m:
            m.record_tokens(1000, 200)
            result = do_work()
    """
    collector = get_metrics_collector()
    m = collector.start_run(agent_name, task_id=task_id, trace_id=trace_id)
    t0 = time.monotonic()
    try:
        yield m
        m.execution_time_ms = (time.monotonic() - t0) * 1000
        m.finish("completed")
    except Exception:
        m.execution_time_ms = (time.monotonic() - t0) * 1000
        m.finish("failed")
        raise


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    return _collector


def new_trace_id() -> str:
    return _new_trace()

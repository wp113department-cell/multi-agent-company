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

import logging
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generator

logger = logging.getLogger(__name__)

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
class PhaseTimingRecord:
    """Gap-closure Day 54 (Stage 2, answers.md Q8 "Planning speed"/"Memory
    retrieval speed": NO — record_tool() times individual tool calls, but no
    metric isolates a graph node's own time from the rest of a run). A
    record_tool()-equivalent for non-tool phases of a run (planner_node,
    memory retrieval, file scanning) — kept in its own list, not mixed into
    tool_calls, since tool_accuracy (tool_calls-derived) feeds directly into
    benchmark_manager.py's real regression-gate scoring; a synthetic
    always-succeeds phase entry in that list would silently skew it."""

    phase_name: str
    duration_ms: float
    success: bool = True
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

    # Gap-closure Day 54 — non-tool phase timings (planner_node, memory
    # retrieval, file scanning). See PhaseTimingRecord's own docstring for
    # why this is a separate list from tool_calls.
    phase_timings: list[PhaseTimingRecord] = field(default_factory=list)

    # Verification
    verification_pct: float = 0.0

    # Memory
    memory_retrieved: int = 0
    memory_written: int = 0

    # Confidence (0.0 – 1.0, estimated by the agent at submit time)
    confidence: float = 1.0

    # Stage 4 Tier 3 (2026-08-05, answer2.md Q43: "confidence is self-
    # reported by the LLM, never independently verified") — `confidence`
    # above is purely what the planner's own JSON output claims
    # (base_graph.py's planner_node, no ground-truth check possible without
    # real outcome-labeled data this project doesn't have). This is the
    # bounded, real check that IS possible today: does the model's own
    # confidence claim match what this run's OTHER independently-computed
    # signals (verification_pct, reflection_unsatisfied) actually say — a
    # real self-consistency check, not a claim of "verified accurate."
    # True means a real mismatch was found (e.g. high self-reported
    # confidence alongside poor real verification), not that confidence is
    # simply low.
    confidence_miscalibrated: bool = False

    # Times reflection_node judged its own tool output unsatisfactory this run
    # (a conservative hallucination-rate proxy — see benchmark_manager.py)
    reflection_unsatisfied: int = 0

    # Final outcome
    status: str = "running"

    # Phase 6.1 — the real OTEL span for this run (opentelemetry.sdk.trace.Span
    # or None if OTEL is unavailable/disabled). Not part of to_dict(); it's an
    # internal handle so record_tool() can attach real child spans.
    _otel_span: Any = field(default=None, repr=False, compare=False)

    def finish(self, status: str = "completed") -> None:
        self.finished_at = _now_iso()
        self.status = status

    def record_tool(
        self,
        tool_name: str,
        success: bool,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        self.tool_calls.append(
            ToolCallRecord(
                tool_name=tool_name,
                success=success,
                duration_ms=duration_ms,
                error=error,
            )
        )
        _record_tool_otel_span(self._otel_span, tool_name, success, duration_ms, error)

    def record_phase(
        self,
        phase_name: str,
        duration_ms: float,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        self.phase_timings.append(
            PhaseTimingRecord(
                phase_name=phase_name,
                duration_ms=duration_ms,
                success=success,
                error=error,
            )
        )

    def record_tokens(self, tokens_in: int, tokens_out: int) -> None:
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self._recompute_cost()

    def _recompute_cost(self) -> None:
        """Stage 4 Cluster P (2026-08-05) — cost is now computed at this
        run's own real tier (via model_router.route(self.agent_name).tier),
        not a single flat Haiku-priced rate applied to every agent
        regardless of which model it actually calls."""
        try:
            from app.config import get_settings
            from app.fleet.model_router import get_model_router
            from app.pipeline.cost_controller import cost_rates_for_tier

            s = get_settings()
            tier = get_model_router().route(self.agent_name).tier
            rate_in, rate_out = cost_rates_for_tier(tier, s)
            self.cost_estimate_usd = (
                self.tokens_in * rate_in + self.tokens_out * rate_out
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
                {
                    "tool": t.tool_name,
                    "success": t.success,
                    "duration_ms": t.duration_ms,
                    "error": t.error,
                }
                for t in self.tool_calls
            ],
            "tool_accuracy": self.tool_accuracy,
            "phase_timings": [
                {
                    "phase": p.phase_name,
                    "success": p.success,
                    "duration_ms": p.duration_ms,
                    "error": p.error,
                }
                for p in self.phase_timings
            ],
            "verification_pct": self.verification_pct,
            "memory_retrieved": self.memory_retrieved,
            "memory_written": self.memory_written,
            "confidence": self.confidence,
            "confidence_miscalibrated": self.confidence_miscalibrated,
            "reflection_unsatisfied": self.reflection_unsatisfied,
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

    def start_run(
        self, agent_name: str, task_id: str | None = None, trace_id: str | None = None
    ) -> RunMetrics:
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

    def all_runs(self) -> list[RunMetrics]:
        """Every run currently held in the ring (bounded by _RING_CAPACITY).
        Used by budget_manager's daily cumulative-spend check."""
        with self._lock:
            return list(self._ring)

    def p50_latency_ms(self, agent_name: str) -> float | None:
        runs = [
            m.execution_time_ms
            for m in self.by_agent(agent_name)
            if m.execution_time_ms > 0
        ]
        if not runs:
            return None
        runs.sort()
        return runs[len(runs) // 2]

    def p95_latency_ms(self, agent_name: str) -> float | None:
        runs = [
            m.execution_time_ms
            for m in self.by_agent(agent_name)
            if m.execution_time_ms > 0
        ]
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

    def tool_latency_stats(
        self, tool_names: str | tuple[str, ...]
    ) -> dict[str, float | int] | None:
        """Aggregate real per-call duration_ms across every tool_calls entry
        (already captured by record_tool(), base_graph.py:1703 — every tool
        call's real timing, not fabricated) matching tool_names, across the
        whole ring buffer. The per-tool-name equivalent of p50/p95_latency_ms's
        per-agent aggregation; powers editing_speed_stats() below and is
        reusable for any other single tool or tool group.
        """
        names = (tool_names,) if isinstance(tool_names, str) else tool_names
        durations = sorted(
            t.duration_ms
            for m in self.all_runs()
            for t in m.tool_calls
            if t.tool_name in names
        )
        if not durations:
            return None
        count = len(durations)
        return {
            "count": count,
            "avg_ms": round(sum(durations) / count, 3),
            "p50_ms": round(durations[count // 2], 3),
            "p95_ms": round(durations[min(int(count * 0.95), count - 1)], 3),
            "min_ms": round(durations[0], 3),
            "max_ms": round(durations[-1], 3),
        }


# File-mutating tool names registered across every tool-suite builder in
# app/agents/tools.py (backend/frontend dev, dependency-update, computer-use,
# chat) — all of them register under these exact literal names regardless of
# which handler set builds them.
EDIT_TOOL_NAMES: tuple[str, ...] = ("edit_file", "write_file", "apply_patch")


def editing_speed_stats() -> dict[str, float | int] | None:
    """"Editing speed" (AUDIT_Q_BATCH05_PERFORMANCE_ARCHITECTURE.md §8: "No
    dedicated timing metric for edit operations specifically" — NOT FOUND).
    Every edit_file/write_file/apply_patch call already has real duration_ms
    recorded via record_tool(); the gap was the missing aggregate across
    them, not missing instrumentation. Mirrors
    orchestration_analytics.get_orchestration_time_stats()/
    memory.analytics.get_retrieval_time_stats()'s existing per-category
    rollup shape instead of introducing a new one.
    """
    return get_metrics_collector().tool_latency_stats(EDIT_TOOL_NAMES)


# ---------------------------------------------------------------------------
# OpenTelemetry bridge (MASTER_AGENT_v2.md Phase 6.1)
# ---------------------------------------------------------------------------
#
# MetricsCollector/RunMetrics above remain the source of truth for the fleet
# dashboard — nothing here changes their behaviour. This bridge additionally
# emits the same run/tool-call timeline as real OTEL spans so trace_id
# correlates with an external collector too. Every OTEL call is wrapped so a
# broken or unconfigured OTEL setup can never break an agent run (same
# graceful-degradation shape as Sentry's DSN-gated init in app/main.py):
# the TracerProvider always records real spans once opentelemetry-sdk is
# installed; it only additionally *exports* them when
# settings.otel_exporter_endpoint is set.

_tracer_provider: Any = None
_tracer_lock = threading.Lock()


def _get_tracer_provider() -> Any:
    """Lazily build (and cache) the process TracerProvider. Returns False
    if the OTEL SDK isn't usable — callers must treat False/None the same
    (falsy) and skip span creation."""
    global _tracer_provider
    if _tracer_provider is not None:
        return _tracer_provider
    with _tracer_lock:
        if _tracer_provider is not None:
            return _tracer_provider
        try:
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
        except Exception:
            _tracer_provider = False
            return _tracer_provider

        try:
            from app.config import get_settings

            _settings = get_settings()
            service_name = _settings.otel_service_name
            endpoint = _settings.otel_exporter_endpoint
        except Exception:
            service_name, endpoint = "multi-agent-company", ""

        provider = TracerProvider(
            resource=Resource.create({"service.name": service_name})
        )
        if endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )
                from opentelemetry.sdk.trace.export import BatchSpanProcessor

                provider.add_span_processor(
                    BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
                )
            except Exception:
                logger.warning(
                    "otel_exporter_endpoint=%s is set but the OTLP exporter "
                    "could not be initialised; spans will be created but not "
                    "exported.",
                    endpoint,
                )
        _tracer_provider = provider
    return _tracer_provider


def configure_tracer_provider(provider: Any) -> None:
    """Inject a specific TracerProvider — used by app startup (a real OTLP-
    exporting provider) and by tests (a provider wired to an in-memory
    exporter so span nesting can be asserted on directly)."""
    global _tracer_provider
    with _tracer_lock:
        _tracer_provider = provider


def reset_tracer_provider_for_testing() -> None:
    """Clear the cached provider so the next _get_tracer_provider() call
    rebuilds it from current settings. Test-only."""
    global _tracer_provider
    with _tracer_lock:
        _tracer_provider = None


def _start_otel_span(m: "RunMetrics") -> Any:
    provider = _get_tracer_provider()
    if not provider:
        return None
    try:
        tracer = provider.get_tracer("multi_agent_company.fleet")
        return tracer.start_span(
            name=f"agent_run:{m.agent_name}",
            attributes={
                "agent.name": m.agent_name,
                "run.trace_id": m.trace_id,
                "run.task_id": m.task_id or "",
            },
        )
    except Exception:
        logger.debug(
            "OTEL span start failed for agent_run:%s", m.agent_name, exc_info=True
        )
        return None


def _end_otel_span(span: Any, status: str, exc: BaseException | None = None) -> None:
    if span is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode

        span.set_attribute("run.status", status)
        if exc is not None:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
        else:
            span.set_status(Status(StatusCode.OK))
        span.end()
    except Exception:
        logger.debug("OTEL span end failed", exc_info=True)


def _record_tool_otel_span(
    parent_span: Any,
    tool_name: str,
    success: bool,
    duration_ms: float,
    error: str | None,
) -> None:
    """Attach a real child span for one tool call under the run's span.
    record_tool() is only called AFTER the tool already finished (see
    execute_tools in base_graph.py), so this reconstructs the child span's
    timing retrospectively via explicit start_time/end_time rather than
    wrapping live execution — this still yields correct parent-child
    nesting in the exported trace, just not live."""
    if parent_span is None:
        return
    provider = _get_tracer_provider()
    if not provider:
        return
    try:
        from opentelemetry.trace import Status, StatusCode, set_span_in_context

        tracer = provider.get_tracer("multi_agent_company.fleet")
        parent_ctx = set_span_in_context(parent_span)
        end_ns = time.time_ns()
        start_ns = end_ns - max(int(duration_ms * 1_000_000), 0)
        child = tracer.start_span(
            name=f"tool_call:{tool_name}",
            context=parent_ctx,
            start_time=start_ns,
            attributes={
                "tool.name": tool_name,
                "tool.success": success,
                "tool.duration_ms": duration_ms,
            },
        )
        if error:
            child.set_attribute("tool.error", error[:200])
        child.set_status(Status(StatusCode.OK if success else StatusCode.ERROR))
        child.end(end_time=end_ns)
    except Exception:
        logger.debug(
            "OTEL child span failed for tool_call:%s", tool_name, exc_info=True
        )


# ---------------------------------------------------------------------------
# Gap-closure Day 54 — non-fatal record_phase() lookup by trace_id, mirroring
# the existing inline pattern at base_graph.py's record_tool() call site
# (get_metrics_collector().get(trace_id), no-op if that trace_id never had
# start_run()/run_span() called for it — e.g. no agent-run context at all).
# ---------------------------------------------------------------------------


def record_phase_timing(
    trace_id: str,
    phase_name: str,
    duration_ms: float,
    success: bool = True,
    error: str | None = None,
) -> None:
    if not trace_id:
        return
    try:
        m = get_metrics_collector().get(trace_id)
        if m is not None:
            m.record_phase(phase_name, duration_ms, success, error)
    except Exception:
        logger.debug("record_phase_timing failed for %s/%s", trace_id, phase_name)


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

    Also opens a real OTEL span for the run (see the bridge above);
    m.record_tool(...) attaches child spans for individual tool calls.
    """
    collector = get_metrics_collector()
    m = collector.start_run(agent_name, task_id=task_id, trace_id=trace_id)
    m._otel_span = _start_otel_span(m)
    t0 = time.monotonic()
    try:
        yield m
        m.execution_time_ms = (time.monotonic() - t0) * 1000
        m.finish("completed")
        _end_otel_span(m._otel_span, "completed")
    except Exception as exc:
        m.execution_time_ms = (time.monotonic() - t0) * 1000
        m.finish("failed")
        _end_otel_span(m._otel_span, "failed", exc)
        raise


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    return _collector


def new_trace_id() -> str:
    return _new_trace()


def check_confidence_calibration(
    confidence: float,
    verification_pct: float,
    reflection_unsatisfied: int,
) -> bool:
    """Stage 4 Tier 3 (2026-08-05, answer2.md Q43) — real, bounded
    self-consistency check between the model's own self-reported
    `confidence` and this same run's *other*, independently-computed
    signals. Returns True on a real mismatch (high self-reported confidence
    alongside poor real verification/repeated self-dissatisfaction) — never
    a positive claim that a "true" confidence score is right, since no
    ground-truth outcome labels exist to check against; a real, honest
    proxy, not a fabricated calibration.
    """
    from app.config import get_settings

    settings = get_settings()
    high_confidence = confidence >= settings.confidence_miscalibration_min_confidence
    poor_verification = (
        verification_pct < settings.confidence_miscalibration_max_verification_pct
    )
    repeated_dissatisfaction = (
        reflection_unsatisfied
        >= settings.confidence_miscalibration_min_reflection_unsatisfied
    )
    return high_confidence and (poor_verification or repeated_dissatisfaction)

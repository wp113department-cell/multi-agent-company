"""Tests for Fleet OS metrics.py — §18 trace_id + observability."""
from __future__ import annotations

import time

import pytest

from app.fleet.metrics import (
    MetricsCollector,
    RunMetrics,
    ToolCallRecord,
    get_metrics_collector,
    new_trace_id,
    run_span,
)


def test_new_trace_id_is_unique() -> None:
    ids = {new_trace_id() for _ in range(100)}
    assert len(ids) == 100


class TestRunMetrics:
    def test_tool_accuracy_perfect_when_all_succeed(self) -> None:
        m = RunMetrics(trace_id="t1", agent_name="qa")
        m.record_tool("run_tests", True, 500.0)
        m.record_tool("git_diff", True, 10.0)
        assert m.tool_accuracy == 1.0

    def test_tool_accuracy_partial(self) -> None:
        m = RunMetrics(trace_id="t1", agent_name="qa")
        m.record_tool("run_tests", True, 500.0)
        m.record_tool("edit_file", False, 5.0, error="protected path")
        assert m.tool_accuracy == pytest.approx(0.5)

    def test_tool_accuracy_1_when_no_calls(self) -> None:
        m = RunMetrics(trace_id="t1", agent_name="qa")
        assert m.tool_accuracy == 1.0

    def test_record_tokens_accumulates(self) -> None:
        m = RunMetrics(trace_id="t1", agent_name="coder")
        m.record_tokens(1000, 200)
        m.record_tokens(500, 100)
        assert m.tokens_in == 1500
        assert m.tokens_out == 300

    def test_finish_sets_status(self) -> None:
        m = RunMetrics(trace_id="t1", agent_name="qa")
        m.finish("completed")
        assert m.status == "completed"
        assert m.finished_at is not None

    def test_to_dict_has_all_required_keys(self) -> None:
        m = RunMetrics(trace_id="t1", agent_name="bug_fix", task_id="task-1")
        m.record_tool("edit_file", True, 50.0)
        m.record_tokens(1000, 200)
        m.finish("completed")
        d = m.to_dict()

        required_keys = {
            "trace_id", "agent_name", "task_id", "started_at", "finished_at",
            "execution_time_ms", "tokens_in", "tokens_out", "cost_estimate_usd",
            "retries", "failures", "tool_calls", "tool_accuracy",
            "verification_pct", "memory_retrieved", "memory_written",
            "confidence", "status",
        }
        assert required_keys.issubset(d.keys())


class TestMetricsCollector:
    def test_start_run_returns_metrics_with_trace_id(self) -> None:
        c = MetricsCollector()
        m = c.start_run("qa", task_id="task-1")
        assert m.trace_id != ""
        assert m.agent_name == "qa"
        assert m.task_id == "task-1"

    def test_get_by_trace_id(self) -> None:
        c = MetricsCollector()
        m = c.start_run("bug_fix")
        retrieved = c.get(m.trace_id)
        assert retrieved is m

    def test_recent_returns_latest(self) -> None:
        c = MetricsCollector()
        for _ in range(5):
            c.start_run("agent")
        assert len(c.recent(3)) == 3

    def test_by_agent_filters_correctly(self) -> None:
        c = MetricsCollector()
        c.start_run("agent_a")
        c.start_run("agent_b")
        c.start_run("agent_a")
        results = c.by_agent("agent_a")
        assert len(results) == 2

    def test_p50_latency_computable(self) -> None:
        c = MetricsCollector()
        for ms in [100.0, 200.0, 300.0, 400.0, 500.0]:
            m = c.start_run("qa")
            m.execution_time_ms = ms
            m.finish()
        p50 = c.p50_latency_ms("qa")
        assert p50 is not None
        assert 200.0 <= p50 <= 400.0

    def test_p95_latency_computable(self) -> None:
        c = MetricsCollector()
        for ms in [100.0] * 19 + [5000.0]:
            m = c.start_run("qa")
            m.execution_time_ms = ms
            m.finish()
        p95 = c.p95_latency_ms("qa")
        assert p95 is not None
        assert p95 >= 100.0

    def test_avg_tool_accuracy_computable(self) -> None:
        c = MetricsCollector()
        m1 = c.start_run("bug_fix")
        m1.record_tool("edit_file", True, 10.0)
        m1.record_tool("run_tests", True, 500.0)

        m2 = c.start_run("bug_fix")
        m2.record_tool("edit_file", False, 5.0)
        m2.record_tool("run_tests", True, 500.0)

        avg = c.avg_tool_accuracy("bug_fix")
        assert avg is not None
        assert 0.5 < avg < 1.0

    def test_custom_trace_id_is_preserved(self) -> None:
        c = MetricsCollector()
        m = c.start_run("qa", trace_id="my-custom-trace")
        assert m.trace_id == "my-custom-trace"
        assert c.get("my-custom-trace") is m


class TestRunSpan:
    def test_run_span_times_execution(self) -> None:
        with run_span("qa", task_id="t1") as m:
            time.sleep(0.01)
        assert m.execution_time_ms >= 5.0
        assert m.status == "completed"

    def test_run_span_marks_failed_on_exception(self) -> None:
        with pytest.raises(ValueError):
            with run_span("qa", task_id="t1") as m:
                raise ValueError("test error")
        assert m.status == "failed"

    def test_run_span_registers_in_collector(self) -> None:
        collector = get_metrics_collector()
        before = len(collector.recent(1000))
        with run_span("pm", task_id="t1", trace_id="span-test-001"):
            pass
        after = collector.recent(1000)
        traces = [m.trace_id for m in after]
        assert "span-test-001" in traces


# ---- Day 0 exit criterion: 7 measurable objectives computable from real data ----

def test_seven_measurable_objectives_computable() -> None:
    """§20 exit criterion: 7 measurable objectives computable for at least one agent."""
    c = MetricsCollector()

    for i, (ms, tokens_in, tokens_out, tool_success) in enumerate([
        (120.0, 1000, 150, True),
        (250.0, 1200, 200, True),
        (180.0, 900, 120, False),
        (310.0, 1500, 250, True),
    ]):
        m = c.start_run("bug_fix", task_id=f"task-{i}", trace_id=f"trace-{i}")
        m.record_tokens(tokens_in, tokens_out)
        m.record_tool("edit_file", tool_success, 30.0)
        m.record_tool("run_tests", True, ms)
        m.verification_pct = 0.85
        m.execution_time_ms = ms
        m.finish("completed" if tool_success else "failed")

    # 1. latency_p50
    p50 = c.p50_latency_ms("bug_fix")
    assert p50 is not None, "latency_p50 not measurable"

    # 2. latency_p95
    p95 = c.p95_latency_ms("bug_fix")
    assert p95 is not None, "latency_p95 not measurable"

    # 3. tool_accuracy
    acc = c.avg_tool_accuracy("bug_fix")
    assert acc is not None, "tool_accuracy not measurable"

    # 4. verification_coverage (verification_pct on any run)
    runs = c.by_agent("bug_fix")
    assert any(r.verification_pct > 0 for r in runs), "verification_coverage not measurable"

    # 5. tokens consumed (proxy for cost)
    total_tokens = sum(r.tokens_in + r.tokens_out for r in runs)
    assert total_tokens > 0, "token usage not measurable"

    # 6. retries tracked
    assert all(hasattr(r, "retries") for r in runs), "retry_success not trackable"

    # 7. status/success computable
    statuses = [r.status for r in runs]
    assert "completed" in statuses, "compile_success not measurable"

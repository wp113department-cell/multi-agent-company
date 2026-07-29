"""Tests for MASTER_AGENT_v2.md Phase 6.1 — OpenTelemetry bridge.

run_span()/RunMetrics.record_tool() (app/fleet/metrics.py) already collect
everything the fleet dashboard needs; this phase additionally emits the same
timeline as real OTEL spans. These tests wire a real
opentelemetry.sdk.trace.TracerProvider with an in-memory exporter (the
"even if locally-run... exporter" the spec's own DoD asks for) via
configure_tracer_provider(), run real run_span()/record_tool() calls, and
assert on the actually-exported spans — not on internal bookkeeping.
"""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.fleet import metrics as metrics_mod
from app.fleet.metrics import get_metrics_collector, run_span


@pytest.fixture()
def otel_exporter():
    """Real TracerProvider + in-memory exporter, injected for the duration
    of one test, restored to the lazily-rebuilt default afterward."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    metrics_mod.configure_tracer_provider(provider)
    try:
        yield exporter
    finally:
        metrics_mod.reset_tracer_provider_for_testing()


def test_run_span_produces_a_real_otel_span(otel_exporter) -> None:
    with run_span("test_agent", task_id="42") as m:
        pass

    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "agent_run:test_agent"
    assert span.attributes["agent.name"] == "test_agent"
    assert span.attributes["run.trace_id"] == m.trace_id
    assert span.attributes["run.task_id"] == "42"
    assert span.attributes["run.status"] == "completed"


def test_run_span_marks_error_status_on_exception(otel_exporter) -> None:
    with pytest.raises(ValueError):
        with run_span("test_agent"):
            raise ValueError("boom")

    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].attributes["run.status"] == "failed"
    assert spans[0].status.status_code.name == "ERROR"


def test_record_tool_creates_a_child_span_nested_under_the_run_span(
    otel_exporter,
) -> None:
    with run_span("test_agent", task_id="7") as m:
        m.record_tool("read_file", True, 12.5)

    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 2

    by_name = {s.name: s for s in spans}
    parent = by_name["agent_run:test_agent"]
    child = by_name["tool_call:read_file"]

    assert child.parent is not None
    assert child.parent.span_id == parent.context.span_id
    assert child.parent.trace_id == parent.context.trace_id
    assert child.attributes["tool.name"] == "read_file"
    assert child.attributes["tool.success"] is True


def test_record_tool_child_span_reflects_failure(otel_exporter) -> None:
    with run_span("test_agent") as m:
        m.record_tool("bash", False, 5.0, error="command not found")

    spans = otel_exporter.get_finished_spans()
    child = next(s for s in spans if s.name == "tool_call:bash")
    assert child.attributes["tool.success"] is False
    assert child.attributes["tool.error"] == "command not found"
    assert child.status.status_code.name == "ERROR"


def test_multiple_tool_calls_all_nest_under_the_same_run_span(otel_exporter) -> None:
    with run_span("test_agent") as m:
        m.record_tool("read_file", True, 1.0)
        m.record_tool("search_code", True, 2.0)
        m.record_tool("write_file", False, 3.0, error="permission denied")

    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 4
    parent = next(s for s in spans if s.name == "agent_run:test_agent")
    children = [s for s in spans if s.name.startswith("tool_call:")]
    assert len(children) == 3
    for child in children:
        assert child.parent.span_id == parent.context.span_id


def test_run_span_still_collects_normal_metrics_alongside_otel(otel_exporter) -> None:
    """The OTEL bridge must never replace or break the existing collector —
    RunMetrics/MetricsCollector behaviour is unchanged."""
    collector = get_metrics_collector()
    with run_span("test_agent", task_id="99") as m:
        m.record_tokens(100, 20)
        m.record_tool("read_file", True, 3.0)

    stored = collector.get(m.trace_id)
    assert stored is not None
    assert stored.tokens_in == 100
    assert stored.tokens_out == 20
    assert len(stored.tool_calls) == 1
    assert stored.status == "completed"


def test_run_span_works_with_manual_enter_exit_not_just_with_block(
    otel_exporter,
) -> None:
    """base_graph.py enters/exits run_span() manually across a large
    function body rather than via a lexical `with` block — confirm the
    bridge behaves identically either way."""
    ctx = run_span("test_agent")
    m = ctx.__enter__()
    m.record_tool("read_file", True, 1.0)
    ctx.__exit__(None, None, None)

    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 2
    assert any(s.name == "agent_run:test_agent" for s in spans)
    assert any(s.name == "tool_call:read_file" for s in spans)


def test_no_tracer_provider_never_raises(monkeypatch) -> None:
    """If the OTEL SDK is unavailable/broken, run_span()/record_tool() must
    degrade gracefully — never raise, never break the caller's run."""
    monkeypatch.setattr(metrics_mod, "_get_tracer_provider", lambda: False)
    with run_span("test_agent") as m:
        m.record_tool("read_file", True, 1.0)
    assert m.status == "completed"
    assert len(m.tool_calls) == 1


def test_tracer_provider_is_lazily_cached() -> None:
    metrics_mod.reset_tracer_provider_for_testing()
    first = metrics_mod._get_tracer_provider()
    second = metrics_mod._get_tracer_provider()
    assert first is second
    metrics_mod.reset_tracer_provider_for_testing()

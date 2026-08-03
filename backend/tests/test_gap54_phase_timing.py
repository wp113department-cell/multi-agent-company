"""Stage 2 Day 54 — performance/latency instrumentation (answers.md Q8
"Planning speed"/"Orchestration speed"/"File scanning speed"/"Memory
retrieval speed": all NO — record_tool() times individual tool calls, but
nothing isolates a graph node's own time, and repo_tools/app.memory have
zero timing instrumentation at all).

Covers: RunMetrics.record_phase()/PhaseTimingRecord (kept separate from
tool_calls so tool_accuracy — a real benchmark_manager.py scoring input —
is never polluted by synthetic phase entries); record_phase_timing()'s
non-fatal trace_id lookup; orchestration_analytics.py (mirrors
memory/analytics.py's Day 43 pattern exactly); and real wiring proofs for
planner_node/memory_hook_node/run_manager()'s two call sites.
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import patch

import pytest

from app.agents.base_graph import _make_memory_hook_node, _make_planner_node
from app.fleet.metrics import (
    PhaseTimingRecord,
    get_metrics_collector,
    record_phase_timing,
)
from app.fleet.orchestration_analytics import (
    get_orchestration_time_stats,
    record_orchestration_time,
    reset_orchestration_time_stats,
)

# ---------------------------------------------------------------------------
# RunMetrics.record_phase() / PhaseTimingRecord
# ---------------------------------------------------------------------------


class TestRecordPhase:
    def test_record_phase_appends_to_phase_timings(self) -> None:
        m = get_metrics_collector().start_run("td_gap54_agent", trace_id="td-gap54-1")
        m.record_phase("planner_node", 12.5)
        assert len(m.phase_timings) == 1
        assert m.phase_timings[0] == PhaseTimingRecord(
            phase_name="planner_node", duration_ms=12.5, success=True, error=None
        )

    def test_record_phase_never_touches_tool_calls_or_tool_accuracy(self) -> None:
        """Regression guard: benchmark_manager.py's real regression-gate
        scoring reads tool_accuracy (derived from tool_calls) — a synthetic
        phase entry must never leak into that list or skew that score."""
        m = get_metrics_collector().start_run("td_gap54_agent2", trace_id="td-gap54-2")
        m.record_tool("real_tool", success=False, duration_ms=5.0)  # one real failure
        assert m.tool_accuracy == 0.0

        m.record_phase("memory_retrieval", 999.0, success=True)
        m.record_phase("file_scanning", 1.0, success=False, error="boom")

        assert m.tool_accuracy == 0.0  # unchanged by phase_timings
        assert len(m.tool_calls) == 1
        assert len(m.phase_timings) == 2

    def test_to_dict_includes_phase_timings(self) -> None:
        m = get_metrics_collector().start_run("td_gap54_agent3", trace_id="td-gap54-3")
        m.record_phase("planner_node", 7.0)
        d = m.to_dict()
        assert d["phase_timings"] == [
            {
                "phase": "planner_node",
                "success": True,
                "duration_ms": 7.0,
                "error": None,
            }
        ]


class TestRecordPhaseTiming:
    def test_records_onto_the_real_run_metrics_for_trace_id(self) -> None:
        collector = get_metrics_collector()
        m = collector.start_run("td_gap54_agent4", trace_id="td-gap54-4")
        record_phase_timing("td-gap54-4", "planner_node", 42.0)
        assert m.phase_timings[0].phase_name == "planner_node"
        assert m.phase_timings[0].duration_ms == 42.0

    def test_no_op_when_trace_id_has_no_live_run_metrics(self) -> None:
        """Mirrors the existing non-fatal record_tool() call-site pattern in
        base_graph.py: a trace_id that never had start_run()/run_span()
        called for it must never raise — it's a normal, expected case."""
        record_phase_timing(
            "td-gap54-nonexistent-trace-id", "planner_node", 1.0
        )  # no raise

    def test_no_op_when_trace_id_is_empty_string(self) -> None:
        record_phase_timing("", "planner_node", 1.0)  # no raise


# ---------------------------------------------------------------------------
# orchestration_analytics.py — mirrors test_gap43_memory_analytics.py's
# window/reset test pattern for memory/analytics.py exactly.
# ---------------------------------------------------------------------------


class TestOrchestrationAnalytics:
    def test_record_and_get_orchestration_time_stats(self) -> None:
        reset_orchestration_time_stats()
        try:
            record_orchestration_time("run_manager", 100.0)
            record_orchestration_time("run_manager", 200.0)

            stats = get_orchestration_time_stats()
            assert stats["run_manager"]["count"] == 2
            assert stats["run_manager"]["avg_ms"] == 150.0
            assert stats["run_manager"]["min_ms"] == 100.0
            assert stats["run_manager"]["max_ms"] == 200.0
        finally:
            reset_orchestration_time_stats()

    def test_window_respects_configured_max_samples(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.config import reset_settings_cache

        monkeypatch.setenv("ORCHESTRATION_TIMING_WINDOW", "3")
        reset_settings_cache()
        reset_orchestration_time_stats()
        try:
            for i in range(10):
                record_orchestration_time("run_manager", float(i))
            stats = get_orchestration_time_stats()
            assert stats["run_manager"]["count"] == 3
            assert stats["run_manager"]["avg_ms"] == 8.0  # samples 7, 8, 9
        finally:
            reset_orchestration_time_stats()
            reset_settings_cache()

    def test_reset_clears_all(self) -> None:
        record_orchestration_time("run_manager", 1.0)
        reset_orchestration_time_stats()
        assert get_orchestration_time_stats() == {}


# ---------------------------------------------------------------------------
# Real wiring — planner_node / memory_hook_node actually call
# record_phase_timing() with the run's real trace_id.
# ---------------------------------------------------------------------------


class TestPlannerNodeRecordsPhaseTiming:
    def test_planner_node_records_a_real_phase_timing(self) -> None:
        collector = get_metrics_collector()
        trace_id = "td-gap54-planner"
        m = collector.start_run("td_gap54_planner_agent", trace_id=trace_id)

        node = _make_planner_node("haiku-model", "do the thing")
        state: dict[str, Any] = {"messages": [], "trace_id": trace_id}

        with patch(
            "app.agents.base_graph._gather_facts_and_plan",
            return_value=("facts", '{"confidence": 0.9}', 0.9),
        ):
            result = node(state)  # type: ignore[arg-type]

        assert result["confidence"] == 0.9
        assert len(m.phase_timings) == 1
        assert m.phase_timings[0].phase_name == "planner_node"
        assert m.phase_timings[0].duration_ms >= 0.0


class TestMemoryHookNodeRecordsPhaseTiming:
    def test_memory_hook_node_records_memory_and_scan_phase_timings(
        self, tmp_path: Any
    ) -> None:
        collector = get_metrics_collector()
        trace_id = "td-gap54-memhook"
        m = collector.start_run("td_gap54_memhook_agent", trace_id=trace_id)

        (tmp_path / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")

        node = _make_memory_hook_node("do the thing", str(tmp_path))
        state: dict[str, Any] = {"messages": [], "trace_id": trace_id}

        empty_mem: dict[str, list[Any]] = {
            "tasks": [],
            "failures": [],
            "learnings": [],
            "procedures": [],
        }
        with patch(
            "app.memory.store.query_memory_context_sync", return_value=empty_mem
        ):
            node(state)  # type: ignore[arg-type]

        phase_names = {p.phase_name for p in m.phase_timings}
        assert "memory_retrieval" in phase_names
        assert "file_scanning" in phase_names


class TestOrchestrationSpeedRealCallers:
    """Verify-real-callers guard: run_manager()'s two real call sites
    (manager.py's epic-manager graph, api/agents.py's direct-dispatch path)
    must actually call record_orchestration_time — not just have the
    function exist somewhere unreferenced."""

    def test_coding_node_calls_record_orchestration_time(self) -> None:
        import app.agents.manager as manager_module

        source = inspect.getsource(manager_module._coding_node)
        assert "record_orchestration_time" in source
        assert "run_manager(" in source

    def test_agents_api_dispatch_calls_record_orchestration_time(self) -> None:
        import app.api.agents as agents_module

        source = inspect.getsource(agents_module)
        assert "record_orchestration_time" in source

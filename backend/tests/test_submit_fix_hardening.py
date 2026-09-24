"""submit_fix tool #214 — tool_enhance.md productionization pass
(2026-09-16).

No security vulnerability and no functional bug found — the real
finding here is DUPLICATION, not a defect. All 4 real implementations
(one each in agent_performance_reviewer.py, knowledge_curator.py,
agent_debugger.py, quality_auditor.py) were already 100% functionally
identical: `def submit_h(inp): return "done"`, byte-for-byte the same
in every file, and all 4 schemas share the identical
`{summary: string}` shape — differing only in cosmetic `description`
text. Unified purely for consistency, matching the precedent already
established for tool #85's `submit_docs`.

Not a dead-accumulator finding — there is no local dict to go stale
here. The real result-capture mechanism is base_graph.py's generic
submit_* handling, confirmed by each of the 4 real callers'
`raw = final_state.get("result", {})` line.
"""

from __future__ import annotations

import importlib
from unittest.mock import patch

from app.tools.agents.submit_fix import SUBMIT_FIX_TOOL, submit_fix_handler


def test_submit_fix_tool_schema() -> None:
    assert SUBMIT_FIX_TOOL["name"] == "submit_fix"
    assert SUBMIT_FIX_TOOL["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_direct_handler_always_returns_done() -> None:
    assert submit_fix_handler({}) == "done"
    assert submit_fix_handler({"summary": "fixed the bug"}) == "done"


# ---------------------------------------------------------------------------
# All 4 real consumers declare the identical shared schema object
# ---------------------------------------------------------------------------


def test_all_4_agents_declare_the_same_shared_submit_fix_schema() -> None:
    modules = [
        "app.agents.agent_performance_reviewer",
        "app.agents.knowledge_curator",
        "app.agents.agent_debugger",
        "app.agents.quality_auditor",
    ]
    for module_name in modules:
        mod = importlib.import_module(module_name)
        matches = [t for t in mod.APPLY_TOOLS if t["name"] == "submit_fix"]
        assert len(matches) == 1, f"{module_name} must declare submit_fix exactly once"
        # Must be the literal same shared object (identity, not just
        # equal-by-value) — proves real de-duplication, not 4
        # independently-maintained dicts that merely look alike today.
        assert matches[0] is SUBMIT_FIX_TOOL


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real apply-phase functions wire the one
# shared handler function (verified via the tool_handlers actually
# passed to run_agent_graph, matching this test suite's established
# mocking convention in tests/test_day9_fleet_agents.py)
# ---------------------------------------------------------------------------


def _fake_state() -> dict[str, object]:
    return {
        "result": {"summary": "done"},
        "verification": {"committed": True, "tests_run": True},
        "tokens_in": 10,
        "tokens_out": 5,
        "submitted": True,
    }


def test_agent_performance_reviewer_apply_wires_shared_submit_fix_handler() -> None:
    from app.agents import agent_performance_reviewer as mod

    with patch.object(mod, "run_agent_graph", return_value=_fake_state()) as mock_run:
        mod.run_agent_performance_reviewer_apply(request_id=1, description="x")
    assert (
        mock_run.call_args.kwargs["tool_handlers"]["submit_fix"] is submit_fix_handler
    )


def test_knowledge_curator_apply_wires_shared_submit_fix_handler() -> None:
    from app.agents import knowledge_curator as mod

    with patch.object(mod, "run_agent_graph", return_value=_fake_state()) as mock_run:
        mod.run_knowledge_curator_apply(request_id=1, description="x")
    assert (
        mock_run.call_args.kwargs["tool_handlers"]["submit_fix"] is submit_fix_handler
    )


def test_agent_debugger_apply_wires_shared_submit_fix_handler() -> None:
    from app.agents import agent_debugger as mod

    with patch.object(mod, "run_agent_graph", return_value=_fake_state()) as mock_run:
        mod.run_agent_debugger_apply(request_id=1, description="x")
    assert (
        mock_run.call_args.kwargs["tool_handlers"]["submit_fix"] is submit_fix_handler
    )


def test_quality_auditor_apply_wires_shared_submit_fix_handler() -> None:
    from app.agents import quality_auditor as mod

    with patch.object(mod, "run_agent_graph", return_value=_fake_state()) as mock_run:
        mod.run_quality_auditor_apply(request_id=1, description="x")
    assert (
        mock_run.call_args.kwargs["tool_handlers"]["submit_fix"] is submit_fix_handler
    )

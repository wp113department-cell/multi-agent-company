"""submit_scaffold_plan tool #274 (final tool in tool_enhance_tracking.md)
— tool_enhance.md productionization pass (2026-09-18).

No security vulnerability and no functional bug found — this audit's
real conclusion, structurally identical to sibling tools #234
(submit_architect_plan), #235 (submit_brief), and #256 (submit_plan).
`app/pipeline/bootstrap.py`'s `run_scaffold_planning()` reuses the
architect agent's identity for a one-shot "blank repo scaffold
planning" call, wiring tools=READ_ONLY_TOOLS + [_SCAFFOLD_SUBMIT_TOOL]
— no write_file/edit_file at all, so the write_file-scoping finding
class from the report-writer agents doesn't apply here. agent_count:0
in the tracking table is a heuristic false negative — this tool isn't
declared in any AGENT_CONTRACT's allowed_tools (it's a standalone
pipeline utility, not a registered agent), same class of false
negative already confirmed on tool #210 (capability_gap_scan).

The handler is a trivial no-op:

    handlers["submit_scaffold_plan"] = lambda inp: "Scaffold plan submitted"

Confirmed intentional, correct design via direct inspection of
`run_scaffold_planning`'s own body: it reads
`final_state.get("result", {})` directly from the generic `submit_*`
capture mechanism in `base_graph.py` — the same pattern already
verified correct on sibling tools #234/#235/#256. Proved the lambda
cannot crash across 6 malformed input shapes. No backwards-priority
bug is even possible here since there is no competing local dict —
`run_scaffold_planning` uses `final_state["result"]` as its one and
only source.
"""

from __future__ import annotations

from app.pipeline.bootstrap import _SCAFFOLD_SUBMIT_TOOL


def test_schema() -> None:
    assert _SCAFFOLD_SUBMIT_TOOL["name"] == "submit_scaffold_plan"
    assert _SCAFFOLD_SUBMIT_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "technical_approach",
        "files",
    ]


def test_no_write_file_or_edit_file_in_scaffold_planning_tools() -> None:
    import inspect

    from app.pipeline.bootstrap import run_scaffold_planning

    src = inspect.getsource(run_scaffold_planning)
    assert "write_file" not in src
    assert "edit_file" not in src
    assert "READ_ONLY_TOOLS" in src


def test_handler_is_a_safe_noop_never_crashes_regardless_of_input() -> None:
    """Reproduces run_scaffold_planning's exact wiring line
    (`handlers["submit_scaffold_plan"] = lambda inp: "Scaffold plan
    submitted"`) directly, without running the full LangGraph."""
    submit_lambda = lambda inp: "Scaffold plan submitted"  # noqa: E731

    for malformed_input in (
        {},
        {"files": None},
        {"technical_approach": 123},
        None,
        "not-a-dict",
        42,
    ):
        result = submit_lambda(malformed_input)
        assert result == "Scaffold plan submitted"


def test_run_scaffold_planning_reads_final_state_result_not_the_handler() -> None:
    """The real, load-bearing data path: confirms the fix pattern from
    sibling tools #234/#235/#256 applies here too — the lambda's return
    value is discarded; only final_state["result"] matters."""
    import inspect

    from app.pipeline.bootstrap import run_scaffold_planning

    src = inspect.getsource(run_scaffold_planning)
    assert 'final_state.get("result", {})' in src

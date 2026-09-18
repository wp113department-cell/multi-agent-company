"""submit_subtasks tool #265 — tool_enhance.md productionization pass
(2026-09-18).

decomposer.py is a pipeline-only agent (like siblings #234/#235/#256)
— decomposer_node runs through app/pipeline/graph.py, not interactive
chat. Deliberately NOT in CHAT_TOOLS. No write_file/edit_file anywhere
in this agent's tool list (permissions=["read_repo"] only,
side_effects=[]) — the write_file-scoping finding class from the
report-writer agents doesn't apply here at all.

Real finding: unlike the pure no-op lambdas on siblings #234/#235/#256
(which ignore their input entirely and can never crash), decomposer's
own `handlers["submit_subtasks"]` lambda actually touches its input —
`len(inp.get('subtasks', []))` — and genuinely crashed with TypeError
on a malformed/schema-violating submission (subtasks=None or a
non-list value; the LLM's tool-use args aren't runtime-enforced
against the declared array-typed input_schema). Proved live using the
real decomposer.py code (not a reconstructed copy).

Confirmed via direct inspection of base_graph.py's
_run_tool_with_retry chokepoint that this crash was ALREADY gracefully
contained fleet-wide (converted to a clean "[ERROR] ... raised: ..."
string, never propagating to crash the pipeline), and that
decomposer_node's own real subtasks data comes from
final_state["result"] — captured independently at the submit_*
chokepoint from the raw tool input, unaffected by whether the
confirmation-string lambda itself crashed. So this was never a
pipeline-breaking bug, only a confusing/incorrect confirmation message
shown back to the LLM. Fixed anyway to match this codebase's
established malformed-submit-data hardening pattern (tools
#236/#242/#247): coerce non-list `subtasks` values to a safe length of
0 rather than letting len() raise.
"""

from __future__ import annotations

from unittest.mock import patch

import app.agents.decomposer as decomposer_module
from app.agents.decomposer import AGENT_CONTRACT, _SUBMIT_TOOL
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT_TOOL["name"] == "submit_subtasks"
    assert _SUBMIT_TOOL["input_schema"]["required"] == ["subtasks"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_subtasks" not in {t["name"] for t in CHAT_TOOLS}


def test_no_write_file_in_this_agents_tools() -> None:
    assert "write_file" not in AGENT_CONTRACT["allowed_tools"]
    assert "edit_file" not in AGENT_CONTRACT["allowed_tools"]
    assert AGENT_CONTRACT["permissions"] == ["read_repo"]


def _extract_submit_subtasks_handler():
    """Runs decomposer_node with run_agent_graph stubbed to raise
    immediately (so we never make a real LLM call), capturing the real
    submit_subtasks handler exactly as wired in production code."""
    fake_handlers: dict = {}
    with (
        patch.object(
            decomposer_module, "make_read_only_handlers", return_value=fake_handlers
        ),
        patch.object(
            decomposer_module,
            "make_record_learning_handler",
            return_value=lambda inp: "ok",
        ),
        patch.object(
            decomposer_module, "run_agent_graph", side_effect=RuntimeError("stop")
        ),
    ):
        decomposer_module.decomposer_node(
            {"task_id": 1, "task_title": "t", "repo_path": "/tmp"}
        )
    return fake_handlers["submit_subtasks"]


def test_submit_subtasks_handler_never_crashes_on_malformed_input() -> None:
    handler = _extract_submit_subtasks_handler()
    for malformed_input in (
        {},
        {"subtasks": None},
        {"subtasks": 5},
        {"subtasks": "notalist"},
    ):
        result = handler(malformed_input)
        assert result == "Submitted 0 subtasks"


def test_submit_subtasks_handler_counts_real_list() -> None:
    handler = _extract_submit_subtasks_handler()
    result = handler({"subtasks": [{"type": "backend", "title": "t", "description": "d"}]})
    assert result == "Submitted 1 subtasks"

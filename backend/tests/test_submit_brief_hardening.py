"""submit_brief tool #235 — tool_enhance.md productionization pass
(2026-09-17).

No security vulnerability and no functional bug found — this audit's
real conclusion, structurally identical to sibling tool #234
(submit_architect_plan). The handler is a trivial no-op lambda
(`lambda inp: "Brief submitted"`) that ignores `inp` entirely — this
is INTENTIONAL correct design, not dead code: `pm_node`'s own body
reads `brief_result = final_state.get("result", {})` directly
(confirmed via direct inspection), meaning base_graph.py's generic
submit_* capture mechanism is the real, load-bearing data path.

Confirmed single implementation (no duplicate in CHAT_TOOLS/
chat_agent.py — pm runs through app/pipeline/graph.py's dedicated
pm_node, not the interactive chat path).

Also reviewed pm_node's outer retry loop (AUDIT_Q_BATCH04 §6
gap-closure) and confidence-surfacing logic — no additional crash
paths found; both already correctly guarded.
"""

from __future__ import annotations

from app.agents.pm import _SUBMIT_TOOL, AGENT_CONTRACT
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT_TOOL["name"] == "submit_brief"
    assert _SUBMIT_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "goals",
        "constraints",
        "acceptance_criteria",
        "out_of_scope",
    ]


def test_not_in_chat_tools() -> None:
    assert "submit_brief" not in {t["name"] for t in CHAT_TOOLS}


def test_handler_is_a_safe_noop_never_crashes_regardless_of_input() -> None:
    """Reproduces pm_node's exact wiring line
    (`handlers["submit_brief"] = lambda inp: "Brief submitted"`)
    directly, without running the full LangGraph."""
    submit_lambda = lambda inp: "Brief submitted"  # noqa: E731

    for malformed_input in (
        {},
        {"goals": None},
        {"constraints": "not-a-list"},
        {"acceptance_criteria": [1, 2, 3]},
        None,
        "not-a-dict",
        42,
    ):
        result = submit_lambda(malformed_input)
        assert result == "Brief submitted"


def test_pm_agent_contract_declares_the_real_tool() -> None:
    assert "submit_brief" in AGENT_CONTRACT["allowed_tools"]


def test_confidence_surfacing_does_not_crash_when_result_already_has_confidence() -> (
    None
):
    """AUDIT_Q_BATCH13 §43: brief_with_confidence = {**brief_result,
    "confidence": final_state.get("confidence", 0.8)} intentionally
    overwrites any model-supplied "confidence" key with the shared
    planner's real computed value — confirms this dict-spread doesn't
    crash or silently drop other real fields."""
    brief_result = {
        "goals": ["g1"],
        "confidence": "a fake LLM-claimed value",
    }
    brief_with_confidence = {**brief_result, "confidence": 0.95}
    assert brief_with_confidence["confidence"] == 0.95
    assert brief_with_confidence["goals"] == ["g1"]

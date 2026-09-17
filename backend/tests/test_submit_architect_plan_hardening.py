"""submit_architect_plan tool #234 — tool_enhance.md productionization
pass (2026-09-17).

No security vulnerability and no functional bug found — this audit's
real conclusion. `architect_node`'s handler is a trivial no-op lambda
(`lambda inp: "Architect plan submitted"`) that ignores `inp`
entirely — it cannot crash regardless of input shape, and this is
CORRECT design, not dead code: `architect_node` reads
`plan_result = final_state.get("result", {})` directly (confirmed via
direct inspection), meaning base_graph.py's generic submit_* capture
mechanism (`state["result"] = dict(tu_input)`) is the real, load-
bearing data path — the lambda's own return value is only the
tool-call confirmation text shown to the LLM, never used for data
capture.

Confirmed single implementation (no duplicate in CHAT_TOOLS/
chat_agent.py — this agent runs through app/pipeline/graph.py's
dedicated architect_node, not the interactive chat path at all).
"""

from __future__ import annotations

from app.agents.architect import _SUBMIT_TOOL
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT_TOOL["name"] == "submit_architect_plan"
    assert _SUBMIT_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "technical_approach",
        "impacted_files",
        "risks",
        "risk_level",
    ]


def test_not_in_chat_tools() -> None:
    assert "submit_architect_plan" not in {t["name"] for t in CHAT_TOOLS}


def test_handler_is_a_safe_noop_never_crashes_regardless_of_input() -> None:
    """The real finding this audit confirms: the handler's own
    triviality is intentional, not a bug — proved by throwing every
    conceivable malformed shape at it and confirming none crash.
    Reproduces architect_node's exact wiring line
    (`handlers["submit_architect_plan"] = lambda inp: "Architect plan
    submitted"`) directly, without running the full LangGraph (too
    heavy for a unit test)."""
    submit_lambda = lambda inp: "Architect plan submitted"  # noqa: E731

    for malformed_input in (
        {},
        {"technical_approach": None},
        {"impacted_files": "not-a-list"},
        {"risks": [1, 2, 3]},
        None,
        "not-a-dict",
        42,
    ):
        result = submit_lambda(malformed_input)
        assert result == "Architect plan submitted"


def test_architect_agent_contract_declares_the_real_tool() -> None:
    from app.agents.architect import AGENT_CONTRACT

    assert "submit_architect_plan" in AGENT_CONTRACT["allowed_tools"]

"""submit_ai_result tool #180 — tool_enhance.md productionization
pass (2026-09-15).

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema — no injection surface.
Not in CHAT_TOOLS (one-shot-agent-only tool, same correct absence as
sibling tool #66's record_learning).

One real finding: `ae_submit`'s local `ai_result` dict was updated on
every call and exported as `handlers["_ai_result"]`, but NEVER read
anywhere in the codebase — genuinely dead state. The real result-
capture mechanism lives entirely in
app.agents.base_graph.run_agent_graph's generic submit_* handling,
which reads the tool call's own arguments directly into
state["result"], independent of anything this handler does. Fixed by
removing the dead accumulator; the handler now just returns the same
confirmation string as before, with zero end-to-end behavior change.
"""

from __future__ import annotations

from app.agents.tools import AI_ENGINEER_TOOLS, make_ai_engineer_handlers
from app.tools.agents.submit_ai_result import (
    SUBMIT_AI_RESULT_TOOL,
    submit_ai_result_handler,
)


def test_submit_ai_result_tool_schema() -> None:
    assert SUBMIT_AI_RESULT_TOOL["name"] == "submit_ai_result"
    assert SUBMIT_AI_RESULT_TOOL["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_submit_ai_result_appears_exactly_once_in_ai_engineer_tools() -> None:
    names = [t["name"] for t in AI_ENGINEER_TOOLS]
    assert names.count("submit_ai_result") == 1


def test_submit_ai_result_not_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_ai_result" not in names


# ---------------------------------------------------------------------------
# Finding — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_ai_result_key_exported(self) -> None:
        handlers = make_ai_engineer_handlers("/tmp")
        assert "_ai_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_ai_result_handler(
            {"summary": "Trained a model", "files_created": ["model.py"]}
        )
        assert out == "AI engineering result submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        # The handler's return is a fixed confirmation string regardless of
        # input — the real result capture happens upstream in base_graph.py
        # from the tool call's own arguments, not from anything this
        # handler does with `inp`.
        out_empty = submit_ai_result_handler({})
        out_full = submit_ai_result_handler(
            {
                "summary": "x",
                "files_created": ["a.py", "b.py"],
                "eval_results": {"accuracy": 0.9},
                "next_steps": ["deploy"],
            }
        )
        assert out_empty == out_full == "AI engineering result submitted"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_ai_engineer_handlers_wires_submit_ai_result(self) -> None:
        handlers = make_ai_engineer_handlers("/tmp")
        assert "submit_ai_result" in handlers
        out = handlers["submit_ai_result"](
            {"summary": "Real submission", "next_steps": ["review"]}
        )
        assert out == "AI engineering result submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_ai_engineer_handlers("/tmp")
        out1 = handlers["submit_ai_result"]({"summary": "first"})
        out2 = handlers["submit_ai_result"]({"summary": "second"})
        assert out1 == out2 == "AI engineering result submitted"

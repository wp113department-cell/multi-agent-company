"""submit_cleanup tool #184 — tool_enhance.md productionization pass
(2026-09-16).

Same class and shape as sibling tools #180/#181/#182/#183. No
injection surface. Not in CHAT_TOOLS (one-shot cleanup_agent-only
tool, correct absence).

One real finding: `cu_submit`'s local `cleanup_result` dict was
updated on every call and exported as `handlers["_cleanup_result"]`,
but NEVER read anywhere in the codebase — genuinely dead state. The
real result-capture mechanism lives entirely in
app.agents.base_graph.run_agent_graph's generic submit_* handling,
confirmed by cleanup_agent.py's own `raw = final_state["result"]`
line, which is what real production code actually consumes. Fixed by
removing the dead accumulator; the handler now just returns the same
confirmation string as before, with zero end-to-end behavior change.
"""

from __future__ import annotations

from app.agents.tools import (
    CHAT_TOOLS,
    CLEANUP_AGENT_TOOLS,
    make_cleanup_agent_handlers,
)
from app.tools.agents.submit_cleanup import (
    SUBMIT_CLEANUP_TOOL,
    submit_cleanup_handler,
)


def test_submit_cleanup_tool_schema() -> None:
    assert SUBMIT_CLEANUP_TOOL["name"] == "submit_cleanup"
    assert SUBMIT_CLEANUP_TOOL["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_submit_cleanup_appears_exactly_once_in_cleanup_agent_tools() -> None:
    names = [t["name"] for t in CLEANUP_AGENT_TOOLS]
    assert names.count("submit_cleanup") == 1


def test_submit_cleanup_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_cleanup" not in names


# ---------------------------------------------------------------------------
# Finding — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_cleanup_result_key_exported(self) -> None:
        handlers = make_cleanup_agent_handlers("/tmp")
        assert "_cleanup_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_cleanup_handler({"summary": "removed dead helpers"})
        assert out == "Cleanup submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        out_minimal = submit_cleanup_handler({})
        out_full = submit_cleanup_handler(
            {
                "summary": "x",
                "dead_code_removed": ["old_helper()"],
                "files_deleted": ["legacy.py"],
                "imports_cleaned": ["unused_module"],
            }
        )
        assert out_minimal == out_full == "Cleanup submitted"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_cleanup_agent_handlers_wires_submit_cleanup(self) -> None:
        handlers = make_cleanup_agent_handlers("/tmp")
        assert "submit_cleanup" in handlers
        out = handlers["submit_cleanup"]({"summary": "Real submission"})
        assert out == "Cleanup submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_cleanup_agent_handlers("/tmp")
        out1 = handlers["submit_cleanup"]({"summary": "first"})
        out2 = handlers["submit_cleanup"]({"summary": "second"})
        assert out1 == out2 == "Cleanup submitted"

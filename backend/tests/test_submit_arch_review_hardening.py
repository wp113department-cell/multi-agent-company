"""submit_arch_review tool #181 — tool_enhance.md productionization
pass (2026-09-15).

Same class and shape as sibling tool #180's submit_ai_result. No
injection surface. Not in CHAT_TOOLS (one-shot architecture_reviewer-
only tool, correct absence).

One real finding: `ar_submit`'s local `arch_result` dict was updated
on every call and exported as `handlers["_arch_result"]`, but NEVER
read anywhere in the codebase — genuinely dead state. The real
result-capture mechanism lives entirely in
app.agents.base_graph.run_agent_graph's generic submit_* handling,
confirmed by `run_arch_review()`'s own `raw = final_state["result"]`
line, which is what real production code actually consumes. Fixed by
removing the dead accumulator; the handler now just returns the same
confirmation string as before, with zero end-to-end behavior change.

Also re-confirms the pre-existing (unrelated, already-fixed)
Gap-closure Day 48 finding still holds: `import_graph_ran` is never
trusted from the model's own claim — `run_arch_review()` reads the
real VerificationConfig graph-execution state instead.
"""

from __future__ import annotations

from app.agents.tools import (
    ARCH_REVIEWER_TOOLS,
    CHAT_TOOLS,
    make_arch_reviewer_handlers,
)
from app.tools.agents.submit_arch_review import (
    SUBMIT_ARCH_REVIEW_TOOL,
    submit_arch_review_handler,
)


def test_submit_arch_review_tool_schema() -> None:
    assert SUBMIT_ARCH_REVIEW_TOOL["name"] == "submit_arch_review"
    assert SUBMIT_ARCH_REVIEW_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "structure_summary",
        "risks",
        "recommendations",
        "import_graph_ran",
    ]


def test_submit_arch_review_appears_exactly_once_in_arch_reviewer_tools() -> None:
    names = [t["name"] for t in ARCH_REVIEWER_TOOLS]
    assert names.count("submit_arch_review") == 1


def test_submit_arch_review_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_arch_review" not in names


# ---------------------------------------------------------------------------
# Finding — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_arch_result_key_exported(self) -> None:
        handlers = make_arch_reviewer_handlers("/tmp")
        assert "_arch_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_arch_review_handler(
            {
                "structure_summary": "1 module, no cycles",
                "risks": [],
                "recommendations": [],
                "blast_radius": None,
                "import_graph_ran": True,
            }
        )
        assert out == "Architecture review submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        out_minimal = submit_arch_review_handler({})
        out_full = submit_arch_review_handler(
            {
                "structure_summary": "x",
                "risks": [{"severity": "high", "description": "d", "evidence": []}],
                "recommendations": ["r1"],
                "blast_radius": ["a.py"],
                "import_graph_ran": True,
            }
        )
        assert out_minimal == out_full == "Architecture review submitted"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_arch_reviewer_handlers_wires_submit_arch_review(self) -> None:
        handlers = make_arch_reviewer_handlers("/tmp")
        assert "submit_arch_review" in handlers
        out = handlers["submit_arch_review"](
            {
                "structure_summary": "Real submission",
                "risks": [],
                "recommendations": [],
                "import_graph_ran": False,
            }
        )
        assert out == "Architecture review submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_arch_reviewer_handlers("/tmp")
        out1 = handlers["submit_arch_review"](
            {
                "structure_summary": "first",
                "risks": [],
                "recommendations": [],
                "import_graph_ran": True,
            }
        )
        out2 = handlers["submit_arch_review"](
            {
                "structure_summary": "second",
                "risks": [],
                "recommendations": [],
                "import_graph_ran": True,
            }
        )
        assert out1 == out2 == "Architecture review submitted"

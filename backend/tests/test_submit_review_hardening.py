"""submit_review tool #195 — tool_enhance.md productionization pass
(2026-09-16).

Same class as tools #187 (submit_health_report), #191
(submit_qa_result), and #193 (submit_research) — NOT a dead
accumulator. `app/agents/reviewer.py::run_reviewer` reads
`handlers.get("_review_result", {})` directly, confirmed by reading
the full function body. No functional bug found. Modularized purely
for consistency with the already-established
`make_submit_docs_handler`/`make_submit_health_report_handler`/
`make_submit_qa_result_handler`/`make_submit_research_handler` pattern
(tools #85/#187/#191/#193).

Not in CHAT_TOOLS — confirmed intentional (reviewer is a batch agent,
never exposed to interactive chat).
"""

from __future__ import annotations

from app.agents.tools import CHAT_TOOLS, REVIEWER_TOOLS, make_reviewer_handlers
from app.tools.agents.submit_review import (
    SUBMIT_REVIEW_TOOL,
    make_submit_review_handler,
)


def test_submit_review_tool_schema() -> None:
    assert SUBMIT_REVIEW_TOOL["name"] == "submit_review"
    assert SUBMIT_REVIEW_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "findings",
        "verdict",
        "summary",
    ]


def test_submit_review_appears_exactly_once_in_reviewer_tools() -> None:
    names = [t["name"] for t in REVIEWER_TOOLS]
    assert names.count("submit_review") == 1


def test_submit_review_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_review" not in names


# ---------------------------------------------------------------------------
# Real, live accumulator — genuinely read by run_reviewer(), not dead code
# ---------------------------------------------------------------------------


class TestRealResultSink:
    def test_make_submit_review_handler_stores_into_the_given_dict(self) -> None:
        review_result: dict = {}
        handler = make_submit_review_handler(review_result)
        result = handler(
            {
                "findings": [
                    {
                        "severity": "blocking",
                        "file": "a.py",
                        "line": 10,
                        "finding": "SQL injection",
                        "recommendation": "use parameterized queries",
                    }
                ],
                "verdict": "changes_required",
                "summary": "1 blocking issue",
            }
        )
        assert result == "Review submitted"
        assert review_result["verdict"] == "changes_required"

    def test_make_submit_review_handler_uses_the_dict_it_was_given_not_a_copy(
        self,
    ) -> None:
        """run_reviewer() reads handlers["_review_result"] after the
        graph run finishes — the handler must mutate that exact object,
        not an internal copy, or the real result would never reach the
        caller."""
        review_result: dict = {}
        handler = make_submit_review_handler(review_result)
        handler({"findings": [], "verdict": "approved", "summary": "clean"})
        assert review_result["verdict"] == "approved"

    def test_make_reviewer_handlers_exports_the_same_object_handler_writes_to(
        self,
    ) -> None:
        handlers = make_reviewer_handlers("/tmp")
        handlers["submit_review"](
            {"findings": [], "verdict": "approved", "summary": "clean"}
        )
        assert handlers["_review_result"]["verdict"] == "approved"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_reviewer_handlers_wires_submit_review(self) -> None:
        handlers = make_reviewer_handlers("/tmp")
        assert "submit_review" in handlers

    def test_repeated_calls_accumulate_into_the_same_dict(self) -> None:
        """Matches update()-based semantics of the original implementation:
        a later call's fields overwrite earlier ones in the same dict,
        exactly as before this modularization."""
        handlers = make_reviewer_handlers("/tmp")
        handlers["submit_review"](
            {"findings": [], "verdict": "changes_required", "summary": "first"}
        )
        handlers["submit_review"](
            {"findings": [], "verdict": "approved", "summary": "second"}
        )
        assert handlers["_review_result"]["verdict"] == "approved"
        assert handlers["_review_result"]["summary"] == "second"

    def test_independent_handler_instances_do_not_share_state(self) -> None:
        h1 = make_reviewer_handlers("/tmp")
        h2 = make_reviewer_handlers("/tmp")
        h1["submit_review"](
            {"findings": [], "verdict": "approved", "summary": "h1"}
        )
        assert "verdict" not in h2["_review_result"]

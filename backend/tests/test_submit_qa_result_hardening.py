"""submit_qa_result tool #191 — tool_enhance.md productionization pass
(2026-09-16).

Same class as tool #187's submit_health_report — NOT a dead
accumulator. `app/agents/qa.py::run_qa` reads
`handlers.get("_qa_result", {})` directly on both its normal success
path and its turn-limit-exhausted retry-giveup path, confirmed by
reading the full function body. No functional bug found. Modularized
purely for consistency with the already-established
`make_submit_docs_handler`/`make_submit_health_report_handler` pattern
(tools #85/#187) — the shared `bash` closure in the same factory
function (`make_qa_handlers`) is untouched, out of scope for this
turn.

Not in CHAT_TOOLS — confirmed intentional (QA is a batch agent, never
exposed to interactive chat).
"""

from __future__ import annotations

from app.agents.tools import CHAT_TOOLS, QA_TOOLS, make_qa_handlers
from app.tools.agents.submit_qa_result import (
    SUBMIT_QA_RESULT_TOOL,
    make_submit_qa_result_handler,
)


def test_submit_qa_result_tool_schema() -> None:
    assert SUBMIT_QA_RESULT_TOOL["name"] == "submit_qa_result"
    assert SUBMIT_QA_RESULT_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "status",
        "tests_run",
        "tests_passed",
        "tests_failed",
        "typecheck_clean",
        "lint_clean",
        "errors",
        "summary",
    ]


def test_submit_qa_result_appears_exactly_once_in_qa_tools() -> None:
    names = [t["name"] for t in QA_TOOLS]
    assert names.count("submit_qa_result") == 1


def test_submit_qa_result_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_qa_result" not in names


# ---------------------------------------------------------------------------
# Real, live accumulator — genuinely read by run_qa(), not dead code
# ---------------------------------------------------------------------------


class TestRealResultSink:
    def test_make_submit_qa_result_handler_stores_into_the_given_dict(self) -> None:
        qa_result: dict = {}
        handler = make_submit_qa_result_handler(qa_result)
        result = handler(
            {
                "status": "passed",
                "tests_run": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "typecheck_clean": True,
                "lint_clean": True,
                "errors": [],
                "summary": "all green",
            }
        )
        assert result == "QA result submitted"
        assert qa_result["status"] == "passed"
        assert qa_result["summary"] == "all green"

    def test_make_submit_qa_result_handler_uses_the_dict_it_was_given_not_a_copy(
        self,
    ) -> None:
        """run_qa() reads handlers["_qa_result"] after the graph run
        finishes (on both its success and retry-giveup paths) — the
        handler must mutate that exact object, not an internal copy."""
        qa_result: dict = {}
        handler = make_submit_qa_result_handler(qa_result)
        handler(
            {
                "status": "failed",
                "tests_run": 5,
                "tests_passed": 3,
                "tests_failed": 2,
                "typecheck_clean": False,
                "lint_clean": True,
                "errors": ["test_foo failed"],
                "summary": "2 failures",
            }
        )
        assert qa_result["status"] == "failed"

    def test_make_qa_handlers_exports_the_same_object_handler_writes_to(self) -> None:
        handlers = make_qa_handlers("/tmp", "/tmp")
        handlers["submit_qa_result"](
            {
                "status": "passed",
                "tests_run": 1,
                "tests_passed": 1,
                "tests_failed": 0,
                "typecheck_clean": True,
                "lint_clean": True,
                "errors": [],
                "summary": "ok",
            }
        )
        assert handlers["_qa_result"]["status"] == "passed"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_qa_handlers_wires_submit_qa_result(self) -> None:
        handlers = make_qa_handlers("/tmp", "/tmp")
        assert "submit_qa_result" in handlers
        assert "bash" in handlers

    def test_repeated_calls_accumulate_into_the_same_dict(self) -> None:
        """Matches update()-based semantics of the original implementation:
        a later call's fields overwrite earlier ones in the same dict,
        exactly as before this modularization."""
        handlers = make_qa_handlers("/tmp", "/tmp")
        handlers["submit_qa_result"](
            {
                "status": "failed",
                "tests_run": 1,
                "tests_passed": 0,
                "tests_failed": 1,
                "typecheck_clean": False,
                "lint_clean": False,
                "errors": ["x"],
                "summary": "first",
            }
        )
        handlers["submit_qa_result"](
            {
                "status": "passed",
                "tests_run": 1,
                "tests_passed": 1,
                "tests_failed": 0,
                "typecheck_clean": True,
                "lint_clean": True,
                "errors": [],
                "summary": "second",
            }
        )
        assert handlers["_qa_result"]["status"] == "passed"
        assert handlers["_qa_result"]["summary"] == "second"

    def test_independent_handler_instances_do_not_share_state(self) -> None:
        h1 = make_qa_handlers("/tmp", "/tmp")
        h2 = make_qa_handlers("/tmp", "/tmp")
        h1["submit_qa_result"](
            {
                "status": "passed",
                "tests_run": 1,
                "tests_passed": 1,
                "tests_failed": 0,
                "typecheck_clean": True,
                "lint_clean": True,
                "errors": [],
                "summary": "h1",
            }
        )
        assert "status" not in h2["_qa_result"]

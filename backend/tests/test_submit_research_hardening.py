"""submit_research tool #193 — tool_enhance.md productionization pass
(2026-09-16).

Same class as tools #187 (submit_health_report) and #191
(submit_qa_result) — NOT a dead accumulator. `app/agents/research.py::
run_research` reads `handlers.get("_research_result", {})` directly,
confirmed by reading the full function body including its explicit
"Research agent did not call submit_research" fallback when the dict
is empty. No functional bug found. Modularized purely for consistency
with the already-established `make_submit_docs_handler`/
`make_submit_health_report_handler`/`make_submit_qa_result_handler`
pattern (tools #85/#187/#191) — the shared `web_search` entry in the
same factory function (`make_research_handlers`) is untouched, already
productionized separately as tool #88.

Not in CHAT_TOOLS — confirmed intentional (research is a batch agent,
never exposed to interactive chat).
"""

from __future__ import annotations

from app.agents.tools import CHAT_TOOLS, RESEARCH_TOOLS, make_research_handlers
from app.tools.agents.submit_research import (
    SUBMIT_RESEARCH_TOOL,
    make_submit_research_handler,
)


def test_submit_research_tool_schema() -> None:
    assert SUBMIT_RESEARCH_TOOL["name"] == "submit_research"
    assert SUBMIT_RESEARCH_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "findings",
        "relevantLibraries",
        "recommendedApproach",
        "risks",
    ]


def test_submit_research_appears_exactly_once_in_research_tools() -> None:
    names = [t["name"] for t in RESEARCH_TOOLS]
    assert names.count("submit_research") == 1


def test_submit_research_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_research" not in names


# ---------------------------------------------------------------------------
# Real, live accumulator — genuinely read by run_research(), not dead code
# ---------------------------------------------------------------------------


class TestRealResultSink:
    def test_make_submit_research_handler_stores_into_the_given_dict(self) -> None:
        research_result: dict = {}
        handler = make_submit_research_handler(research_result)
        result = handler(
            {
                "findings": ["libfoo is well-maintained"],
                "relevantLibraries": [{"name": "libfoo", "rationale": "fits use case"}],
                "recommendedApproach": "use libfoo",
                "risks": [],
            }
        )
        assert result == "Research report submitted"
        assert research_result["recommendedApproach"] == "use libfoo"

    def test_make_submit_research_handler_uses_the_dict_it_was_given_not_a_copy(
        self,
    ) -> None:
        """run_research() reads handlers["_research_result"] after the
        graph run finishes — the handler must mutate that exact object,
        not an internal copy, or the real result would never reach the
        caller."""
        research_result: dict = {}
        handler = make_submit_research_handler(research_result)
        handler(
            {
                "findings": ["x"],
                "relevantLibraries": [],
                "recommendedApproach": "y",
                "risks": [],
            }
        )
        assert research_result["recommendedApproach"] == "y"

    def test_make_research_handlers_exports_the_same_object_handler_writes_to(
        self,
    ) -> None:
        handlers = make_research_handlers("/tmp")
        handlers["submit_research"](
            {
                "findings": ["a"],
                "relevantLibraries": [],
                "recommendedApproach": "b",
                "risks": [],
            }
        )
        assert handlers["_research_result"]["recommendedApproach"] == "b"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_research_handlers_wires_submit_research(self) -> None:
        handlers = make_research_handlers("/tmp")
        assert "submit_research" in handlers
        assert "web_search" in handlers

    def test_repeated_calls_accumulate_into_the_same_dict(self) -> None:
        """Matches update()-based semantics of the original implementation:
        a later call's fields overwrite earlier ones in the same dict,
        exactly as before this modularization."""
        handlers = make_research_handlers("/tmp")
        handlers["submit_research"](
            {
                "findings": ["first"],
                "relevantLibraries": [],
                "recommendedApproach": "first",
                "risks": [],
            }
        )
        handlers["submit_research"](
            {
                "findings": ["second"],
                "relevantLibraries": [],
                "recommendedApproach": "second",
                "risks": [],
            }
        )
        assert handlers["_research_result"]["recommendedApproach"] == "second"

    def test_independent_handler_instances_do_not_share_state(self) -> None:
        h1 = make_research_handlers("/tmp")
        h2 = make_research_handlers("/tmp")
        h1["submit_research"](
            {
                "findings": ["h1"],
                "relevantLibraries": [],
                "recommendedApproach": "h1",
                "risks": [],
            }
        )
        assert "recommendedApproach" not in h2["_research_result"]

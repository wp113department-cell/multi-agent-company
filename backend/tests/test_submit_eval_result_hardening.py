"""submit_eval_result tool #247 — tool_enhance.md productionization
pass (2026-09-17).

No write_file in this agent's tools at all — the write_file-scoping
finding class from recent sibling tools (#231/#232/etc.) doesn't apply
here.

Three real, separate uncaught-crash paths, all from the same root
cause — `overall_score`/`cases` are never schema-validated at runtime
(the LLM's own submit call, or the generic submit_* capture, can send
anything despite the schema declaring specific types):

1. `submit_eval_h`'s own `f"score={score:.2f}"` raised an uncaught
   ValueError when `overall_score` was a non-numeric string.
2. `run_evaluation_agent()`'s near-identical post-processing raised
   the same ValueError for the same reason.
3. `run_evaluation_agent()`'s findings-building list comprehension
   (`c.get("name", "?")` etc.) raised an uncaught AttributeError for a
   non-dict entry mixed into `cases`.

All 3 proved live before any fix. Fixed with a shared `_safe_float()`
helper (used in both submit_eval_h and run_evaluation_agent) and
inline isinstance filtering for `cases` (matching the pattern already
established for tool #242's database_architect) — non-numeric values
coerce to a safe default, non-dict entries are dropped rather than
crashing the whole result.
"""

from __future__ import annotations

from unittest.mock import patch

from app.agents.evaluation_agent import (
    _SUBMIT_EVAL_TOOL,
    make_evaluation_handlers,
    run_evaluation_agent,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT_EVAL_TOOL["name"] == "submit_eval_result"
    assert _SUBMIT_EVAL_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "overall_score",
        "pass_count",
        "fail_count",
        "summary",
    ]


def test_not_in_chat_tools() -> None:
    assert "submit_eval_result" not in {t["name"] for t in CHAT_TOOLS}


def test_no_write_file_in_this_agents_tools() -> None:
    """Confirms the write_file-scoping finding class from recent
    sibling tools genuinely doesn't apply — this agent never
    advertises write_file at all."""
    from app.agents.evaluation_agent import AGENT_CONTRACT

    assert "write_file" not in AGENT_CONTRACT["allowed_tools"]


# ---------------------------------------------------------------------------
# The real findings: malformed overall_score/cases no longer crash
# ---------------------------------------------------------------------------


def test_submit_non_numeric_score_does_not_crash() -> None:
    handlers = make_evaluation_handlers("/tmp")
    result = handlers["submit_eval_result"](
        {
            "overall_score": "not-a-number",
            "pass_count": 1,
            "fail_count": 0,
            "summary": "x",
        }
    )
    assert "score=0.00" in result


def _fake_run(result: dict) -> dict:
    return {
        "result": result,
        "verification": {"eval_run": True},
        "tokens_in": 1,
        "tokens_out": 1,
        "submitted": True,
    }


def test_agent_result_non_numeric_score_does_not_crash() -> None:
    with patch(
        "app.agents.evaluation_agent.run_agent_graph",
        return_value=_fake_run(
            {
                "overall_score": "not-a-number",
                "pass_count": 1,
                "fail_count": 0,
                "summary": "x",
            }
        ),
    ):
        result = run_evaluation_agent(task_id=1, description="x", repo_path="/tmp")
    assert "score=0.00" in result.summary


def test_agent_result_non_dict_case_entry_does_not_crash() -> None:
    with patch(
        "app.agents.evaluation_agent.run_agent_graph",
        return_value=_fake_run(
            {
                "overall_score": 0.5,
                "pass_count": 1,
                "fail_count": 1,
                "summary": "x",
                "cases": ["not-a-dict"],
            }
        ),
    ):
        result = run_evaluation_agent(task_id=1, description="x", repo_path="/tmp")
    assert result.findings == []


def test_agent_result_non_numeric_pass_fail_counts_do_not_crash() -> None:
    with patch(
        "app.agents.evaluation_agent.run_agent_graph",
        return_value=_fake_run(
            {
                "overall_score": 0.5,
                "pass_count": "x",
                "fail_count": None,
                "summary": "x",
            }
        ),
    ):
        result = run_evaluation_agent(task_id=1, description="x", repo_path="/tmp")
    assert "0/0 passed" in result.summary


# ---------------------------------------------------------------------------
# Legitimate-usage regression — matches the pre-existing behavior exactly
# ---------------------------------------------------------------------------


def test_submit_well_formed_score_still_works() -> None:
    handlers = make_evaluation_handlers("/tmp")
    result = handlers["submit_eval_result"](
        {"overall_score": 0.8, "pass_count": 4, "fail_count": 1, "summary": "x"}
    )
    assert "score=0.80 pass=4 fail=1" in result


def test_agent_result_well_formed_case_still_built_correctly() -> None:
    with patch(
        "app.agents.evaluation_agent.run_agent_graph",
        return_value=_fake_run(
            {
                "overall_score": 0.75,
                "pass_count": 3,
                "fail_count": 1,
                "summary": "ok",
                "cases": [{"name": "c1", "passed": True, "reason": "r"}],
            }
        ),
    ):
        result = run_evaluation_agent(task_id=1, description="x", repo_path="/tmp")
    assert "score=0.75 (3/4 passed)" in result.summary
    assert len(result.findings) == 1
    assert result.findings[0]["case"] == "c1"

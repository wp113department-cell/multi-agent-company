"""submit_user_stories tool #270 — tool_enhance.md productionization
pass (2026-09-18).

Checked and correctly RULED OUT the write_file-scoping finding class
from 22 sibling agents: AGENT_CONTRACT declares
permissions=["read_repo","write_repo"] (not write_docs), and
roles/user_story_generator.md has no "read-only on code" claim or
Non-Responsibility against writing code — same "correctly ruled out"
pattern as sibling tool #259 (release_notes_agent). Confirmed live
that write_file to a real .feature file succeeds, matching the
declared contract.

Real finding, IDENTICAL class to sibling tools #258/#259/#269:
run_user_story_generator's own
`raw = submitted if submitted else final_state["result"]` had the
priority BACKWARDS relative to the correct, established pattern used
by every other submit_* agent in this codebase. base_graph.py's
execute_tools() builds final_state["result"] starting from the same
dict the LLM passed to submit_user_stories, then extends it with
graph-enforced diagnostics (_quality_gate, _citation_check,
_validation_warning) at the one real submit_* chokepoint. Preferring
the local `submitted` dict silently dropped that diagnostic trail
(including a FAILING quality gate) from AgentResult.raw, proved live.
"""

from __future__ import annotations

from unittest.mock import patch

from app.agents.user_story_generator import (
    _SUBMIT_STORIES_TOOL,
    AGENT_CONTRACT,
    make_user_story_handlers,
    run_user_story_generator,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT_STORIES_TOOL["name"] == "submit_user_stories"
    assert set(_SUBMIT_STORIES_TOOL["input_schema"]["required"]) == {  # type: ignore[index]
        "feature",
        "stories",
        "summary",
    }


def test_not_in_chat_tools() -> None:
    assert "submit_user_stories" not in {t["name"] for t in CHAT_TOOLS}


def test_agent_contract_declares_real_write_repo_need() -> None:
    assert AGENT_CONTRACT["permissions"] == ["read_repo", "write_repo"]


def test_write_file_unrestricted_matches_declared_contract() -> None:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_user_story_handlers(tmp)
        result = handlers["write_file"](
            {"path": "features/login.feature", "content": "Feature: Login\n"}
        )
        assert result.startswith("Written")
        assert (
            Path(tmp) / "features" / "login.feature"
        ).read_text() == "Feature: Login\n"


def _final_state_with_result(result: dict) -> dict:
    return {
        "result": result,
        "verification": {"codebase_read": True},
        "tokens_in": 10,
        "tokens_out": 10,
        "submitted": True,
    }


def _make_handlers_that_submit(inp: dict):
    def fake_make_handlers(repo: str) -> dict:
        h = make_user_story_handlers(repo)
        h["submit_user_stories"](inp)
        return h

    return fake_make_handlers


_VALID_SUBMISSION = {
    "feature": "login",
    "stories": [
        {
            "title": "user logs in",
            "as_a": "registered user",
            "i_want": "to log in with my credentials",
            "so_that": "I can access my account",
            "acceptance_criteria": ["valid credentials succeed"],
        }
    ],
    "summary": "test",
}


def test_graph_enforced_result_takes_priority_over_local_dict() -> None:
    """The real bug: this line was backwards. final_state['result'] (the
    graph-enforced, diagnostics-carrying dict) must win over the local
    `submitted` closure dict whenever it is non-empty."""
    final_state = _final_state_with_result(
        {
            **_VALID_SUBMISSION,
            "_quality_gate": {
                "passed": False,
                "checks": {},
                "warnings": ["low confidence"],
                "confidence": 0.1,
            },
            "_citation_check": {"unverified": ["app/fake.py:999"]},
        }
    )
    with (
        patch(
            "app.agents.user_story_generator.make_user_story_handlers",
            side_effect=_make_handlers_that_submit(_VALID_SUBMISSION),
        ),
        patch(
            "app.agents.user_story_generator.run_agent_graph",
            return_value=final_state,
        ),
    ):
        result = run_user_story_generator(1, "generate stories", repo_path="/tmp")

    assert "_quality_gate" in result.raw
    assert result.raw["_quality_gate"]["passed"] is False
    assert "_citation_check" in result.raw


def test_local_dict_fallback_still_works_when_graph_result_empty() -> None:
    """The local `submitted` dict remains a legitimate fallback for the
    edge case where final_state['result'] is genuinely empty."""
    final_state = _final_state_with_result({})
    with (
        patch(
            "app.agents.user_story_generator.make_user_story_handlers",
            side_effect=_make_handlers_that_submit(_VALID_SUBMISSION),
        ),
        patch(
            "app.agents.user_story_generator.run_agent_graph",
            return_value=final_state,
        ),
    ):
        result = run_user_story_generator(2, "generate stories", repo_path="/tmp")

    assert "login" in result.summary


def test_normal_content_fields_unaffected_by_the_fix() -> None:
    """Both dicts share the same source content — the fix must not
    change what a normal (no-diagnostics) submission produces."""
    final_state = _final_state_with_result(dict(_VALID_SUBMISSION))
    with (
        patch(
            "app.agents.user_story_generator.make_user_story_handlers",
            side_effect=_make_handlers_that_submit(_VALID_SUBMISSION),
        ),
        patch(
            "app.agents.user_story_generator.run_agent_graph",
            return_value=final_state,
        ),
    ):
        result = run_user_story_generator(3, "generate stories", repo_path="/tmp")

    assert result.raw["feature"] == "login"
    assert len(result.raw["stories"]) == 1

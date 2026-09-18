"""submit_release_notes tool #259 — tool_enhance.md productionization pass
(2026-09-18).

Same real, proven defect already found and fixed on sibling tool #258
(submit_rag_design): run_release_notes_agent's own
`raw = submitted if submitted else final_state["result"]` had the
priority BACKWARDS relative to the correct, established pattern used
by every other submit_* agent in this codebase (`final_state["result"]
if final_state["result"] else <local fallback>`). base_graph.py's
execute_tools() builds final_state["result"] starting from the exact
same dict the LLM passed to submit_release_notes, then extends it with
graph-enforced diagnostics (_quality_gate, _citation_check,
_validation_warning) at the one real submit_* chokepoint. Preferring
the local `submitted` dict silently dropped that diagnostic trail
(including a FAILING quality gate) from AgentResult.raw, proved live.

Also audited the write_file-scoping finding class from 15 sibling
"read-only report writer" agents and correctly RULED IT OUT: unlike
those agents (which declare permissions=["read_repo","write_docs"] and
explicitly forbid code changes), release_notes_agent's own
AGENT_CONTRACT declares permissions=["read_repo","write_repo"] with no
contradicting role-file restriction — roles/release_notes_agent.md has
no "read-only on code" claim and no Non-Responsibility against writing
code. Confirmed live: write_file to a real .py file succeeds, matching
the agent's own declared write_repo permission — not a contradiction,
so no scoping fix applies here.
"""

from __future__ import annotations

from unittest.mock import patch

from app.agents.release_notes_agent import (
    _SUBMIT_RELEASE_NOTES_TOOL,
    AGENT_CONTRACT,
    make_release_notes_handlers,
    run_release_notes_agent,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT_RELEASE_NOTES_TOOL["name"] == "submit_release_notes"
    assert set(_SUBMIT_RELEASE_NOTES_TOOL["input_schema"]["required"]) == {  # type: ignore[index]
        "version",
        "content",
        "highlights",
    }


def test_not_in_chat_tools() -> None:
    assert "submit_release_notes" not in {t["name"] for t in CHAT_TOOLS}


def test_agent_contract_declares_real_write_repo_need() -> None:
    """This agent's own contract explains why the write_file-scoping fix
    from sibling report-writer agents doesn't apply here."""
    assert AGENT_CONTRACT["permissions"] == ["read_repo", "write_repo"]


def test_write_file_unrestricted_matches_declared_contract() -> None:
    """write_file-scoping finding class correctly RULED OUT: no
    contradiction between the code and this agent's own contract."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_release_notes_handlers(tmp)
        result = handlers["write_file"](
            {"path": "RELEASE_NOTES.md", "content": "# v1.2.0\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "RELEASE_NOTES.md").read_text() == "# v1.2.0\n"


def _final_state_with_result(result: dict) -> dict:
    return {
        "result": result,
        "verification": {"git_log_read": True},
        "tokens_in": 10,
        "tokens_out": 10,
        "submitted": True,
    }


def _make_handlers_that_submit(inp: dict):
    def fake_make_handlers(repo: str) -> dict:
        h = make_release_notes_handlers(repo)
        h["submit_release_notes"](inp)
        return h

    return fake_make_handlers


_VALID_SUBMISSION = {
    "version": "v1.2.0",
    "content": "# v1.2.0\n\n- thing 1\n",
    "highlights": ["thing 1"],
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
            "app.agents.release_notes_agent.make_release_notes_handlers",
            side_effect=_make_handlers_that_submit(_VALID_SUBMISSION),
        ),
        patch(
            "app.agents.release_notes_agent.run_agent_graph",
            return_value=final_state,
        ),
    ):
        result = run_release_notes_agent(1, "write release notes", repo_path="/tmp")

    assert "_quality_gate" in result.raw
    assert result.raw["_quality_gate"]["passed"] is False
    assert "_citation_check" in result.raw


def test_local_dict_fallback_still_works_when_graph_result_empty() -> None:
    """The local `submitted` dict remains a legitimate fallback for the
    edge case where final_state['result'] is genuinely empty."""
    final_state = _final_state_with_result({})
    with (
        patch(
            "app.agents.release_notes_agent.make_release_notes_handlers",
            side_effect=_make_handlers_that_submit(_VALID_SUBMISSION),
        ),
        patch(
            "app.agents.release_notes_agent.run_agent_graph",
            return_value=final_state,
        ),
    ):
        result = run_release_notes_agent(2, "write release notes", repo_path="/tmp")

    assert "v1.2.0" in result.summary


def test_normal_content_fields_unaffected_by_the_fix() -> None:
    """Both dicts share the same source content — the fix must not
    change what a normal (no-diagnostics) submission produces."""
    final_state = _final_state_with_result(dict(_VALID_SUBMISSION))
    with (
        patch(
            "app.agents.release_notes_agent.make_release_notes_handlers",
            side_effect=_make_handlers_that_submit(_VALID_SUBMISSION),
        ),
        patch(
            "app.agents.release_notes_agent.run_agent_graph",
            return_value=final_state,
        ),
    ):
        result = run_release_notes_agent(3, "write release notes", repo_path="/tmp")

    assert result.raw["version"] == "v1.2.0"
    assert result.raw["highlights"] == ["thing 1"]

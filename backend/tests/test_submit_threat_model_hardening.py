"""submit_threat_model tool #269 — tool_enhance.md productionization
pass (2026-09-18).

security_architect.py is fully read-only (permissions=["read_repo"]
only, side_effects=[], no write_file anywhere in its tool list) — the
write_file-scoping finding class from the report-writer agents doesn't
apply here at all.

Real finding: same backwards result-priority defect already found and
fixed on sibling tools #258 (submit_rag_design) and #259
(submit_release_notes). run_security_architect's own
`raw = submitted if submitted else final_state["result"]` had the
priority BACKWARDS relative to the correct, established pattern used
by every other submit_* agent in this codebase. base_graph.py's
execute_tools() builds final_state["result"] starting from the same
dict the LLM passed to submit_threat_model, then extends it with
graph-enforced diagnostics (_quality_gate, _citation_check,
_validation_warning) at the one real submit_* chokepoint. Preferring
the local `submitted` dict silently dropped that diagnostic trail
(including a FAILING quality gate) from AgentResult.raw, proved live.
"""

from __future__ import annotations

from unittest.mock import patch

from app.agents.security_architect import (
    _SUBMIT_THREAT_MODEL_TOOL,
    AGENT_CONTRACT,
    make_security_architect_handlers,
    run_security_architect,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT_THREAT_MODEL_TOOL["name"] == "submit_threat_model"
    assert set(_SUBMIT_THREAT_MODEL_TOOL["input_schema"]["required"]) == {  # type: ignore[index]
        "summary",
        "threats",
        "overall_risk",
    }


def test_not_in_chat_tools() -> None:
    assert "submit_threat_model" not in {t["name"] for t in CHAT_TOOLS}


def test_no_write_file_in_this_agents_tools() -> None:
    assert "write_file" not in AGENT_CONTRACT["allowed_tools"]
    assert AGENT_CONTRACT["permissions"] == ["read_repo"]


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
        h = make_security_architect_handlers(repo)
        h["submit_threat_model"](inp)
        return h

    return fake_make_handlers


_VALID_SUBMISSION = {
    "summary": "test",
    "threats": [
        {
            "category": "Tampering",
            "description": "unauthenticated write endpoint",
            "severity": "high",
            "mitigation": "require auth",
        }
    ],
    "overall_risk": "high",
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
            "app.agents.security_architect.make_security_architect_handlers",
            side_effect=_make_handlers_that_submit(_VALID_SUBMISSION),
        ),
        patch(
            "app.agents.security_architect.run_agent_graph",
            return_value=final_state,
        ),
    ):
        result = run_security_architect(1, "review security", repo_path="/tmp")

    assert "_quality_gate" in result.raw
    assert result.raw["_quality_gate"]["passed"] is False
    assert "_citation_check" in result.raw


def test_local_dict_fallback_still_works_when_graph_result_empty() -> None:
    """The local `submitted` dict remains a legitimate fallback for the
    edge case where final_state['result'] is genuinely empty."""
    final_state = _final_state_with_result({})
    with (
        patch(
            "app.agents.security_architect.make_security_architect_handlers",
            side_effect=_make_handlers_that_submit(_VALID_SUBMISSION),
        ),
        patch(
            "app.agents.security_architect.run_agent_graph",
            return_value=final_state,
        ),
    ):
        result = run_security_architect(2, "review security", repo_path="/tmp")

    assert "high" in result.summary


def test_normal_content_fields_unaffected_by_the_fix() -> None:
    """Both dicts share the same source content — the fix must not
    change what a normal (no-diagnostics) submission produces."""
    final_state = _final_state_with_result(dict(_VALID_SUBMISSION))
    with (
        patch(
            "app.agents.security_architect.make_security_architect_handlers",
            side_effect=_make_handlers_that_submit(_VALID_SUBMISSION),
        ),
        patch(
            "app.agents.security_architect.run_agent_graph",
            return_value=final_state,
        ),
    ):
        result = run_security_architect(3, "review security", repo_path="/tmp")

    assert result.raw["overall_risk"] == "high"
    assert len(result.raw["threats"]) == 1
    assert result.requires_human_approval is True

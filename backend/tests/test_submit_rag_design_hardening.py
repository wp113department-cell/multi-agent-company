"""submit_rag_design tool #258 — tool_enhance.md productionization pass
(2026-09-18).

AGENT_CONTRACT explicitly declares permissions=["read_repo","write_repo",
"execute_code"] and side_effects=["may write pipeline implementation
files"] — rag_engineer_agent genuinely needs unrestricted write_file
(it writes real retrieval/embedding pipeline code). Checked and
correctly RULED OUT of the write_file-scoping finding class already
fixed on 15 sibling "read-only report writer" agents this run, same
discernment as tools #233/#241/#251/#253: confirmed live that writing
a real .py pipeline file succeeds — correct, intended behavior.

The real finding here: run_rag_engineer_agent's own
`raw = submitted if submitted else final_state["result"]` had the
priority BACKWARDS relative to the correct, established pattern used
by every other submit_* agent in this codebase
(`final_state["result"] if final_state["result"] else <fallback>`).
base_graph.py's execute_tools() builds final_state["result"] from the
same dict the LLM passed to submit_rag_design, then extends it with
graph-enforced diagnostics (_quality_gate, _citation_check,
_validation_warning) at the one real submit_* chokepoint (see
base_graph.py's _run_quality_gate and the citation-check call
immediately after the submit_* schema-validation block). Preferring
the local `submitted` dict silently dropped that diagnostic trail —
including a FAILING quality gate (_quality_gate.passed=False) — from
AgentResult.raw, proved live via a direct run_rag_engineer_agent()
call with run_agent_graph mocked to return a final_state whose result
carries a failed quality gate.
"""

from __future__ import annotations

from unittest.mock import patch

from app.agents.rag_engineer_agent import (
    _SUBMIT_RAG_TOOL,
    AGENT_CONTRACT,
    make_rag_engineer_handlers,
    run_rag_engineer_agent,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT_RAG_TOOL["name"] == "submit_rag_design"
    assert set(_SUBMIT_RAG_TOOL["input_schema"]["required"]) == {  # type: ignore[index]
        "summary",
        "chunking_strategy",
        "embedding_model",
        "vector_store",
        "retrieval_strategy",
    }


def test_not_in_chat_tools() -> None:
    assert "submit_rag_design" not in {t["name"] for t in CHAT_TOOLS}


def test_agent_contract_declares_real_write_repo_need() -> None:
    """This agent's own contract explains why the write_file-scoping fix
    from sibling agents doesn't apply here."""
    assert AGENT_CONTRACT["permissions"] == ["read_repo", "write_repo", "execute_code"]
    assert "write_repo" in AGENT_CONTRACT["permissions"]


def test_write_file_allows_real_pipeline_code() -> None:
    """The write_file-scoping finding class correctly RULED OUT: this
    agent's real, intended output includes real .py pipeline code."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_rag_engineer_handlers(tmp)
        result = handlers["write_file"](
            {"path": "app/retrieval.py", "content": "def retrieve(): pass\n"}
        )
        assert result.startswith("Written")
        assert (
            Path(tmp) / "app" / "retrieval.py"
        ).read_text() == "def retrieve(): pass\n"


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
        h = make_rag_engineer_handlers(repo)
        h["submit_rag_design"](inp)
        return h

    return fake_make_handlers


_VALID_SUBMISSION = {
    "summary": "test",
    "chunking_strategy": "recursive",
    "embedding_model": "voyage-code-2",
    "vector_store": "pgvector",
    "retrieval_strategy": "top-k",
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
            "app.agents.rag_engineer_agent.make_rag_engineer_handlers",
            side_effect=_make_handlers_that_submit(_VALID_SUBMISSION),
        ),
        patch(
            "app.agents.rag_engineer_agent.run_agent_graph",
            return_value=final_state,
        ),
    ):
        result = run_rag_engineer_agent(1, "design a RAG pipeline", repo_path="/tmp")

    assert "_quality_gate" in result.raw
    assert result.raw["_quality_gate"]["passed"] is False
    assert "_citation_check" in result.raw


def test_local_dict_fallback_still_works_when_graph_result_empty() -> None:
    """The local `submitted` dict remains a legitimate fallback for the
    edge case where final_state['result'] is genuinely empty."""
    final_state = _final_state_with_result({})
    with (
        patch(
            "app.agents.rag_engineer_agent.make_rag_engineer_handlers",
            side_effect=_make_handlers_that_submit(_VALID_SUBMISSION),
        ),
        patch(
            "app.agents.rag_engineer_agent.run_agent_graph",
            return_value=final_state,
        ),
    ):
        result = run_rag_engineer_agent(2, "design a RAG pipeline", repo_path="/tmp")

    assert "pgvector" in result.summary
    assert "voyage-code-2" in result.summary


def test_normal_content_fields_unaffected_by_the_fix() -> None:
    """Both dicts share the same source content — the fix must not
    change what a normal (no-diagnostics) submission produces."""
    final_state = _final_state_with_result(dict(_VALID_SUBMISSION))
    with (
        patch(
            "app.agents.rag_engineer_agent.make_rag_engineer_handlers",
            side_effect=_make_handlers_that_submit(_VALID_SUBMISSION),
        ),
        patch(
            "app.agents.rag_engineer_agent.run_agent_graph",
            return_value=final_state,
        ),
    ):
        result = run_rag_engineer_agent(3, "design a RAG pipeline", repo_path="/tmp")

    assert result.raw["vector_store"] == "pgvector"
    assert result.raw["embedding_model"] == "voyage-code-2"
    assert result.raw["retrieval_strategy"] == "top-k"

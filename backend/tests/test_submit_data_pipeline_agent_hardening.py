"""submit_data_pipeline_agent tool #241 — tool_enhance.md
productionization pass (2026-09-17).

No security vulnerability and no functional bug found — this audit's
real conclusion. Investigated and RULED OUT the same "unrestricted
write_file contradicts a docs-only role promise" finding class just
fixed on 5 sibling agents (accessibility_agent #231,
agentic_ai_architect #232, code_explainer_agent #237,
code_quality_agent #238, compliance_agent #239, cost_estimator_agent
#240): unlike those, roles/data_pipeline_agent.md does NOT claim
"read-only on code" or "zero repo files modified" anywhere — its own
Non-Responsibilities section explicitly frames the scope boundary as
"Implementing full production pipelines (workers implement; you
design + stub)", and its Output Contract lists a "stubs":
"implementation stub paths" field, confirming this agent is meant to
write real code stub files, not just docs. Confirmed live that
writing a .py stub file succeeds — correct, intended behavior;
applying the sibling agents' restriction here would have been a real
regression, matching the same discernment already applied to sibling
tool #233 (submit_api_designer_agent).

submit_data_pipeline_agent itself audited and found correct: same
"raw = final_state["result"] if final_state["result"] else result"
pattern already confirmed live/not-dead on sibling agents.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.data_pipeline_agent import (
    _SUBMIT,
    make_data_pipeline_agent_handlers,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_data_pipeline_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_data_pipeline_agent" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# write_file legitimately needs a broader scope than .md/docs/** here —
# confirmed via the role file, not assumed
# ---------------------------------------------------------------------------


def test_write_file_allows_implementation_stub_file() -> None:
    """Unlike accessibility_agent/agentic_ai_architect/etc., this
    agent's own role file explicitly expects real .py stub output
    ("stubs": implementation stub paths) — applying that same
    restriction here would break a real, intended use case."""
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_data_pipeline_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "pipelines/etl_stub.py", "content": "def transform(): pass\n"}
        )
        assert result.startswith("Written")
        assert (
            Path(tmp) / "pipelines" / "etl_stub.py"
        ).read_text() == "def transform(): pass\n"


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_data_pipeline_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "../../../../etc/evil.py", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


# ---------------------------------------------------------------------------
# submit_data_pipeline_agent itself — legitimate-usage regression
# ---------------------------------------------------------------------------


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_data_pipeline_agent_handlers("/tmp")
    out = handlers["submit_data_pipeline_agent"](
        {"summary": "Designed an ETL pipeline for order events", "findings": []}
    )
    assert out == "Submitted."
    assert (
        handlers["_result"]["summary"] == "Designed an ETL pipeline for order events"
    )

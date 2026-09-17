"""submit_api_designer_agent tool #233 — tool_enhance.md
productionization pass (2026-09-17).

No security vulnerability and no functional bug found — this audit's
real conclusion. Investigated and RULED OUT the same "unrestricted
write_file contradicts a docs-only role promise" finding just fixed on
sibling agents accessibility_agent (#231) and agentic_ai_architect
(#232): unlike those two, roles/api_designer_agent.md does NOT claim
"read-only on code" or "zero repo files modified" anywhere — its
Process step 3 explicitly says "Use write_file to save any output
files (reports, specs, scripts, docs)", and its Non-Responsibilities
section only excludes IMPLEMENTING the API (backend_dev's job), not
writing files generally. AGENT_CONTRACT's own
side_effects=["writes OpenAPI spec or contract .yaml/.md files"]
confirms .yaml is a legitimate, intended output — confirmed live that
writing openapi.yaml (a non-.md, non-docs/ path) succeeds, which is
correct, expected behavior for this specific agent, not a gap.

Also confirmed: AGENT_CONTRACT["permissions"] is never read/enforced
anywhere in the codebase (grepped app/fleet/*.py and base_graph.py) —
"write_docs" here is descriptive metadata shared by many agents, not a
broken, code-enforced promise specific to this one.

submit_api_designer_agent itself audited and found correct: same
"raw = final_state["result"] if final_state["result"] else result"
pattern already confirmed live/not-dead on sibling agents' turns.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.api_designer_agent import _SUBMIT, make_api_designer_agent_handlers
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_api_designer_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_api_designer_agent" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# write_file legitimately needs a broader scope than .md/docs/** here —
# confirmed via the role file, not assumed
# ---------------------------------------------------------------------------


def test_write_file_allows_openapi_yaml_at_repo_root() -> None:
    """Unlike accessibility_agent/agentic_ai_architect, this agent's own
    role file and AGENT_CONTRACT explicitly expect .yaml spec output,
    not just .md/docs/** — applying that same restriction here would
    break a real, intended use case."""
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_api_designer_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "openapi.yaml", "content": "openapi: 3.0.0\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "openapi.yaml").read_text() == "openapi: 3.0.0\n"


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_api_designer_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "../../../../etc/evil.yaml", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


# ---------------------------------------------------------------------------
# submit_api_designer_agent itself — legitimate-usage regression
# ---------------------------------------------------------------------------


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_api_designer_agent_handlers("/tmp")
    out = handlers["submit_api_designer_agent"](
        {"summary": "Designed a REST API for widgets", "findings": []}
    )
    assert out == "Submitted."
    assert handlers["_result"]["summary"] == "Designed a REST API for widgets"


def test_submit_accepts_extra_output_contract_fields_without_crashing() -> None:
    """The role file's own Output Contract mentions spec/conflict_check/
    decisions/status fields not present in _SUBMIT's schema properties
    — confirms this mismatch doesn't cause a crash or data loss since
    submit_h accepts and stores whatever it's given."""
    handlers = make_api_designer_agent_handlers("/tmp")
    out = handlers["submit_api_designer_agent"](
        {
            "summary": "x",
            "spec": "openapi.yaml",
            "conflict_check": "none found",
            "decisions": ["used cursor pagination"],
            "status": "done",
        }
    )
    assert out == "Submitted."
    assert handlers["_result"]["spec"] == "openapi.yaml"

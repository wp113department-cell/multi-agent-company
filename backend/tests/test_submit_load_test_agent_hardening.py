"""submit_load_test_agent tool #251 — tool_enhance.md
productionization pass (2026-09-17).

No security vulnerability and no functional bug found — this audit's
real conclusion. Investigated and RULED OUT the same "unrestricted
write_file contradicts a docs-only role promise" finding class just
fixed on 12 sibling agents: unlike those, roles/load_test_agent.md
does NOT claim "read-only on code" or "zero repo files modified"
anywhere — this agent's whole job is writing runnable k6/Locust load
test SCRIPTS (real code), not docs. Its own Failure Conditions instead
scope writes to "Editing any file that was not read in this run" and
"Writing outside the assigned worktree/scope" — a different, narrower
kind of restriction than a blanket read-only-on-code lockout. Confirmed
live that writing a real .js load test script succeeds — correct,
intended behavior; applying the sibling agents' restriction here would
have been a real regression, matching the same discernment already
applied to sibling tools #233 (submit_api_designer_agent) and #241
(submit_data_pipeline_agent).

`bash` was already correctly scoped to the dedicated
make_load_test_bash_handler (k6/locust-only, rejects arbitrary shell
commands) — verified, not touched.

submit_load_test_agent itself audited and found correct: same
"raw = final_state["result"] if final_state["result"] else result"
pattern already confirmed live/not-dead on sibling agents.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.load_test_agent import _SUBMIT, make_load_test_agent_handlers
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_load_test_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_load_test_agent" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# write_file legitimately needs a broader scope than .md/docs/** here —
# confirmed via the role file, not assumed
# ---------------------------------------------------------------------------


def test_write_file_allows_real_load_test_script() -> None:
    """Unlike accessibility_agent/agentic_ai_architect/etc., this
    agent's own role file explicitly expects a real, runnable k6/
    Locust script as output — applying that same .md/docs/**
    restriction here would break a real, intended use case."""
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_load_test_agent_handlers(tmp)
        result = handlers["write_file"](
            {
                "path": "loadtest/k6_script.js",
                "content": "export default function() {}\n",
            }
        )
        assert result.startswith("Written")
        assert (
            Path(tmp) / "loadtest" / "k6_script.js"
        ).read_text() == "export default function() {}\n"


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_load_test_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "../../../../etc/evil.js", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


def test_bash_still_scoped_to_load_test_only_handler() -> None:
    """Regression guard: bash must remain the dedicated k6/locust-only
    handler, not the unrestricted chat-agent bash."""
    handlers = make_load_test_agent_handlers("/tmp")
    result = handlers["bash"]({"command": "rm -rf /"})
    assert result.startswith("[POLICY DENIED]") or result.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# submit_load_test_agent itself — legitimate-usage regression
# ---------------------------------------------------------------------------


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_load_test_agent_handlers("/tmp")
    out = handlers["submit_load_test_agent"](
        {"summary": "Generated a k6 script for /api/orders", "findings": []}
    )
    assert out == "Submitted."
    assert handlers["_result"]["summary"] == "Generated a k6 script for /api/orders"

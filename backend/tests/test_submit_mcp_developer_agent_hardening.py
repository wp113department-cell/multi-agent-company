"""submit_mcp_developer_agent tool #253 — tool_enhance.md
productionization pass (2026-09-18).

No security vulnerability and no functional bug found — this audit's
real conclusion. Investigated and RULED OUT the "unrestricted
write_file/bash contradicts a docs-only/dry-run-only role promise"
finding class just fixed on the recent run of sibling "read-only"
report-writing agents (#231/#232/#237-#240/#243-#246/#248-#250/#252):
unlike those, roles/mcp_developer_agent.md does NOT claim "read-only
on code" anywhere — this agent's whole job is writing real MCP
server/client CODE and running it via bash to prove it works.
AGENT_CONTRACT itself explicitly declares
permissions=["read_repo", "write_repo", "execute_bash"] (not
"write_docs") and side_effects=["writes MCP server/client code",
"executes bash to test it"] — the broad access is intentional and
documented, not an oversight. Confirmed live that both write_file and
bash work as genuinely intended (writing real code, running real
shell commands) — applying the sibling agents' restriction here would
have broken this agent's entire purpose.

submit_mcp_developer_agent itself audited and found correct: same
"raw = final_state["result"] if final_state["result"] else result"
pattern already confirmed live/not-dead on sibling agents.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.mcp_developer_agent import (
    AGENT_CONTRACT,
    _SUBMIT,
    make_mcp_developer_agent_handlers,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_mcp_developer_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_mcp_developer_agent" not in {t["name"] for t in CHAT_TOOLS}


def test_contract_explicitly_declares_broad_write_access() -> None:
    """Confirms the broad write_repo/execute_bash permission is a
    documented, intentional design choice — not an oversight to be
    reconciled with a "read-only" claim that doesn't exist here."""
    assert "write_repo" in AGENT_CONTRACT["permissions"]
    assert "execute_bash" in AGENT_CONTRACT["permissions"]
    assert "write_docs" not in AGENT_CONTRACT["permissions"]


# ---------------------------------------------------------------------------
# write_file/bash legitimately need broad scope here — confirmed via the
# role file and AGENT_CONTRACT, not assumed
# ---------------------------------------------------------------------------


def test_write_file_allows_real_server_code() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_mcp_developer_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "mcp_server.py", "content": "import sys\nprint('ready')\n"}
        )
        assert result.startswith("Written")
        assert (
            Path(tmp) / "mcp_server.py"
        ).read_text() == "import sys\nprint('ready')\n"


def test_bash_can_run_a_real_command() -> None:
    handlers = make_mcp_developer_agent_handlers("/tmp")
    result = handlers["bash"]({"command": "echo verified"})
    assert "verified" in result


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_mcp_developer_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "../../../../etc/evil.py", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


def test_bash_dangerous_command_still_blocked() -> None:
    """Even with intentionally broad bash access, the underlying real
    safety measures must still catch genuinely dangerous commands —
    confirmed live: the real response is a [BLOCKED] (irreversible/
    catastrophic, no confirmation possible), not merely [POLICY
    DENIED] or [ERROR]."""
    handlers = make_mcp_developer_agent_handlers("/tmp")
    result = handlers["bash"]({"command": "rm -rf /"})
    assert result.startswith("[BLOCKED]")


# ---------------------------------------------------------------------------
# submit_mcp_developer_agent itself — legitimate-usage regression
# ---------------------------------------------------------------------------


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_mcp_developer_agent_handlers("/tmp")
    out = handlers["submit_mcp_developer_agent"](
        {
            "summary": "Built a stdio MCP server exposing 2 tools",
            "files_written": ["mcp_server.py"],
        }
    )
    assert out == "Submitted."
    assert (
        handlers["_result"]["summary"] == "Built a stdio MCP server exposing 2 tools"
    )

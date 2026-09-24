"""submit_version_manager_agent tool #272 — tool_enhance.md
productionization pass (2026-09-18).

Same real, severe finding class already found and fixed on 25 sibling
agents, the strongest form: roles/version_manager_agent.md's own
Failure Conditions state "Modifying, creating, or deleting any repo
file (this role is read-only on code)" and its Quality Gates require
"Zero repo files were modified" (matching localization_agent's/
test_coverage_agent's exact phrasing). AGENT_CONTRACT claims
permissions=["read_repo","write_docs"] and side_effects=["writes
version upgrade reports"]. But make_version_manager_agent_handlers()
gave this agent the FULL, UNRESTRICTED write_file, able to write real
application code too. Proved live: a direct write_file({"path":
"app/main.py", ...}) call genuinely overwrote a real .py file. Fixed
with the same .md/docs/** scoping already established for the sibling
agents.

This agent's real git_tag/semver_bump tools were already independently
productionized in earlier turns (tools #22/#25, own dedicated reports
and hardening suites) — this fix is scoped to write_file only;
git_tag/semver_bump are re-confirmed unaffected below.

submit_version_manager_agent itself audited and found correct: this
file already has the correct final_state["result"]-first priority,
with its own dated comment from a prior audit pass — no change needed
here.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.version_manager_agent import (
    _SUBMIT,
    AGENT_CONTRACT,
    make_version_manager_agent_handlers,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_version_manager_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_version_manager_agent" not in {t["name"] for t in CHAT_TOOLS}


def test_agent_contract_claims_write_docs_only() -> None:
    assert AGENT_CONTRACT["permissions"] == ["read_repo", "write_docs"]


def test_write_file_blocks_real_code_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "app").mkdir()
        (Path(tmp) / "app" / "main.py").write_text("print(1)\n")
        handlers = make_version_manager_agent_handlers(tmp)

        result = handlers["write_file"](
            {"path": "app/main.py", "content": "print(2)\n"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert (Path(tmp) / "app" / "main.py").read_text() == "print(1)\n"


def test_write_file_blocks_requirements_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "requirements.txt").write_text("flask==1.0\n")
        handlers = make_version_manager_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "requirements.txt", "content": "flask==2.0\n"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert (Path(tmp) / "requirements.txt").read_text() == "flask==1.0\n"


def test_write_file_allows_upgrade_report_md() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_version_manager_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "UPGRADE_REPORT.md", "content": "# Upgrades\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "UPGRADE_REPORT.md").read_text() == "# Upgrades\n"


def test_write_file_allows_docs_subpath() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_version_manager_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/upgrade_report.md", "content": "# Upgrades\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "docs" / "upgrade_report.md").read_text() == "# Upgrades\n"


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_version_manager_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/../../../etc/evil.md", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


def test_git_tag_unaffected_by_write_file_scoping() -> None:
    """git_tag (tool #22, already independently productionized) must
    keep working exactly as before — this fix only touches write_file."""
    handlers = make_version_manager_agent_handlers(".")
    result = handlers["git_tag"]({"action": "list"})
    assert not result.startswith("[POLICY DENIED]")


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_version_manager_agent_handlers("/tmp")
    out = handlers["submit_version_manager_agent"](
        {
            "summary": "Recommend bumping requests to 2.31.0 for CVE-2023-32681",
            "findings": [],
        }
    )
    assert out == "Submitted."
    assert "CVE-2023-32681" in handlers["_result"]["summary"]

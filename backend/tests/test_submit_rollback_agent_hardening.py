"""submit_rollback_agent tool #261 — tool_enhance.md productionization
pass (2026-09-18).

Same real, severe finding class already found and fixed on 17 sibling
agents: roles/rollback_agent.md's "Use write_file to save any output
files (reports, specs, scripts, docs)" line is shared boilerplate
across 15 role files (including several already correctly scoped down
this run, e.g. pair_programmer_agent, localization_agent) — not a
genuine, agent-specific need. This agent's own Non-Responsibilities
instead say "Executing rollbacks — plans only, humans/ops execute",
and AGENT_CONTRACT claims permissions=["read_repo","write_docs"]
(never "write_repo") with side_effects=["writes rollback plan
documents"] — the real, intended output is a rollback PLAN document,
not code. But make_rollback_agent_handlers() gave this agent the FULL,
UNRESTRICTED write_file, able to write real application code too.
Proved live: a direct write_file({"path": "app/main.py", ...}) call
genuinely overwrote a real .py file. Fixed with the same .md/docs/**
scoping already established for the sibling agents.

submit_rollback_agent itself audited and found correct: this file
already has the correct final_state["result"]-first priority (with its
own dated comment from a prior audit pass) — no change needed here.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.rollback_agent import (
    _SUBMIT,
    AGENT_CONTRACT,
    make_rollback_agent_handlers,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_rollback_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_rollback_agent" not in {t["name"] for t in CHAT_TOOLS}


def test_agent_contract_claims_write_docs_only() -> None:
    assert AGENT_CONTRACT["permissions"] == ["read_repo", "write_docs"]


def test_write_file_blocks_real_code_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "app").mkdir()
        (Path(tmp) / "app" / "main.py").write_text("print(1)\n")
        handlers = make_rollback_agent_handlers(tmp)

        result = handlers["write_file"](
            {"path": "app/main.py", "content": "print(2)\n"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert (Path(tmp) / "app" / "main.py").read_text() == "print(1)\n"


def test_write_file_blocks_non_md_non_docs_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_rollback_agent_handlers(tmp)
        result = handlers["write_file"]({"path": "rollback.sh", "content": "#!/bin/sh"})
        assert result.startswith("[POLICY DENIED]")
        assert not (Path(tmp) / "rollback.sh").exists()


def test_write_file_allows_rollback_plan_md() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_rollback_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "ROLLBACK_PLAN.md", "content": "# Plan\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "ROLLBACK_PLAN.md").read_text() == "# Plan\n"


def test_write_file_allows_docs_subpath() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_rollback_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/rollback_plan.md", "content": "# Plan\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "docs" / "rollback_plan.md").read_text() == "# Plan\n"


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_rollback_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/../../../etc/evil.md", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_rollback_agent_handlers("/tmp")
    out = handlers["submit_rollback_agent"](
        {"summary": "Rollback plan for migration 0042", "findings": []}
    )
    assert out == "Submitted."
    assert handlers["_result"]["summary"] == "Rollback plan for migration 0042"

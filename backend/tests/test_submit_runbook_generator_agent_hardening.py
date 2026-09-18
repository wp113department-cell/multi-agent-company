"""submit_runbook_generator_agent tool #262 — tool_enhance.md
productionization pass (2026-09-18).

Same real, severe finding class already found and fixed on 18 sibling
agents, adapted for this agent's dual write_file+edit_file tool set
(same shape as tool #254's onboarding_agent fix — both are "Editor
tier" per test_editor_tier.py). roles/runbook_generator_agent.md's own
Process says "Write the runbook with write_file, or edit_file if
updating an existing one" and its Non-Responsibilities say "Executing
operations — runbooks only". AGENT_CONTRACT claims
permissions=["read_repo","write_docs"] (never "write_repo") and
side_effects=["writes operational runbooks", "edits existing
runbooks", "validates embedded YAML for syntax"] — every real output
is a runbook document. But make_runbook_generator_agent_handlers()
gave this agent BOTH the FULL, UNRESTRICTED write_file AND edit_file,
able to modify real application code too. Proved live: direct
write_file and edit_file calls against "app/main.py" both genuinely
modified a real .py file. Fixed with the same .md/docs/** scoping
already established for the sibling agents, applied to both tools.

submit_runbook_generator_agent itself audited and found correct: this
file already has the correct final_state["result"]-first priority,
with its own dated comment from a prior audit pass — no change needed
here.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.runbook_generator_agent import (
    _SUBMIT,
    AGENT_CONTRACT,
    make_runbook_generator_agent_handlers,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_runbook_generator_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_runbook_generator_agent" not in {t["name"] for t in CHAT_TOOLS}


def test_agent_contract_claims_write_docs_only() -> None:
    assert AGENT_CONTRACT["permissions"] == ["read_repo", "write_docs"]


def test_write_file_blocks_real_code_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "app").mkdir()
        (Path(tmp) / "app" / "main.py").write_text("print(1)\n")
        handlers = make_runbook_generator_agent_handlers(tmp)

        result = handlers["write_file"](
            {"path": "app/main.py", "content": "print(2)\n"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert (Path(tmp) / "app" / "main.py").read_text() == "print(1)\n"


def test_edit_file_blocks_real_code_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "app").mkdir()
        (Path(tmp) / "app" / "main.py").write_text("print(1)\n")
        handlers = make_runbook_generator_agent_handlers(tmp)

        result = handlers["edit_file"](
            {
                "path": "app/main.py",
                "old_string": "print(1)",
                "new_string": "print(999)",
            }
        )
        assert result.startswith("[POLICY DENIED]")
        assert (Path(tmp) / "app" / "main.py").read_text() == "print(1)\n"


def test_write_file_allows_docs_runbook() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_runbook_generator_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/runbooks/deploy.md", "content": "# Deploy Runbook\n"}
        )
        assert result.startswith("Written")
        assert (
            Path(tmp) / "docs" / "runbooks" / "deploy.md"
        ).read_text() == "# Deploy Runbook\n"


def test_edit_file_allows_existing_runbook_md() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "RUNBOOK_DEPLOY.md").write_text("# Deploy\n")
        handlers = make_runbook_generator_agent_handlers(tmp)
        result = handlers["edit_file"](
            {
                "path": "RUNBOOK_DEPLOY.md",
                "old_string": "# Deploy",
                "new_string": "# Deploy Runbook",
            }
        )
        assert result.startswith("Edited")
        assert (
            Path(tmp) / "RUNBOOK_DEPLOY.md"
        ).read_text() == "# Deploy Runbook\n"


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_runbook_generator_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/../../../etc/evil.md", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_runbook_generator_agent_handlers("/tmp")
    out = handlers["submit_runbook_generator_agent"](
        {"summary": "Wrote deploy and rollback runbooks", "findings": []}
    )
    assert out == "Submitted."
    assert (
        handlers["_result"]["summary"] == "Wrote deploy and rollback runbooks"
    )

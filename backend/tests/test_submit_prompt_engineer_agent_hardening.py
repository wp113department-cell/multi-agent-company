"""submit_prompt_engineer_agent tool #257 — tool_enhance.md
productionization pass (2026-09-18).

Same real, severe finding class already found and fixed on 14 sibling
agents, adapted here for a genuine, legitimate exception: this agent's
whole job includes writing/revising real .md prompt/role files
(roles/*.md), so a blanket "no repo files at all" ban would be wrong.
roles/prompt_engineer_agent.md explicitly lists "Implementing the code
that calls the prompt (that's coder/backend_dev's scope)" as a
Non-Responsibility, and its own Quality Gate says "Zero UNRELATED repo
files modified" (narrower than the other agents' absolute "Zero repo
files modified"). AGENT_CONTRACT claims
permissions=["read_repo", "write_docs"] (never "write_repo") — but
make_prompt_engineer_agent_handlers() gave this agent the FULL,
UNRESTRICTED write_file, able to write real application code too.
Proved live: a direct write_file({"path": "app/main.py", ...}) call
genuinely overwrote a real .py file.

Fixed with the same .md/docs/** scoping already established for the
sibling agents — this already correctly permits the agent's real,
intended use case (every role file lives at roles/*.md, which ends in
.md) while blocking the code-implementation work this agent's own
Non-Responsibilities explicitly excludes.

submit_prompt_engineer_agent itself audited and found correct: same
"raw = final_state["result"] if final_state["result"] else result"
pattern already confirmed live/not-dead on sibling agents.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.prompt_engineer_agent import (
    _SUBMIT,
    make_prompt_engineer_agent_handlers,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_prompt_engineer_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_prompt_engineer_agent" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The real finding: write_file must be scoped, but must still allow
# this agent's genuinely legitimate role-file use case
# ---------------------------------------------------------------------------


def test_write_file_blocks_real_code_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "app").mkdir()
        (Path(tmp) / "app" / "main.py").write_text("print(1)\n")
        handlers = make_prompt_engineer_agent_handlers(tmp)

        result = handlers["write_file"](
            {"path": "app/main.py", "content": "print(2)\n"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert (Path(tmp) / "app" / "main.py").read_text() == "print(1)\n"


def test_write_file_blocks_non_md_non_docs_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_prompt_engineer_agent_handlers(tmp)
        result = handlers["write_file"]({"path": "config.json", "content": "{}"})
        assert result.startswith("[POLICY DENIED]")
        assert not (Path(tmp) / "config.json").exists()


def test_write_file_allows_revising_a_real_role_file() -> None:
    """The real, legitimate use case this fix must not break: every
    role file lives at roles/*.md, which ends in .md."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "roles").mkdir()
        handlers = make_prompt_engineer_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "roles/some_agent.md", "content": "# Revised prompt\n"}
        )
        assert result.startswith("Written")
        assert (
            Path(tmp) / "roles" / "some_agent.md"
        ).read_text() == "# Revised prompt\n"


def test_write_file_allows_docs_subpath() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_prompt_engineer_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/prompt_audit.md", "content": "# Audit\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "docs" / "prompt_audit.md").read_text() == "# Audit\n"


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_prompt_engineer_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/../../../etc/evil.md", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


# ---------------------------------------------------------------------------
# submit_prompt_engineer_agent itself — legitimate-usage regression
# ---------------------------------------------------------------------------


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_prompt_engineer_agent_handlers("/tmp")
    out = handlers["submit_prompt_engineer_agent"](
        {"summary": "Tightened the output contract in coder.md", "findings": []}
    )
    assert out == "Submitted."
    assert (
        handlers["_result"]["summary"] == "Tightened the output contract in coder.md"
    )

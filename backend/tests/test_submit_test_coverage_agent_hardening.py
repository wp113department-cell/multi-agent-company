"""submit_test_coverage_agent tool #267 — tool_enhance.md
productionization pass (2026-09-18).

Same real, severe finding class already found and fixed on 22 sibling
agents, the strongest form of the pattern: roles/test_coverage_agent.md's
own Failure Conditions state "Modifying, creating, or deleting any repo
file (this role is read-only on code)" and its Quality Gates require
"Zero repo files were modified" (the exact phrasing already confirmed
on localization_agent). AGENT_CONTRACT claims
permissions=["read_repo","write_docs","execute_tests"] and its own
side_effects explicitly say "runs coverage tooling ... — never writes
code". But make_test_coverage_agent_handlers() gave this agent the
FULL, UNRESTRICTED write_file, able to write real application code
too. Proved live: a direct write_file({"path": "app/main.py", ...})
call genuinely overwrote a real .py file. Fixed with the same
.md/docs/** scoping already established for the sibling agents. bash
is already correctly scoped to make_test_runner_bash_handler
(coverage-tooling-only) — verified, not touched.

submit_test_coverage_agent itself audited and found correct: this file
already has the correct final_state["result"]-first priority, with its
own dated comment from a prior audit pass — no change needed here.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.test_coverage_agent import (
    _SUBMIT,
    AGENT_CONTRACT,
    make_test_coverage_agent_handlers,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_test_coverage_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_test_coverage_agent" not in {t["name"] for t in CHAT_TOOLS}


def test_agent_contract_declares_never_writes_code() -> None:
    assert "never writes code" in AGENT_CONTRACT["side_effects"][1]


def test_write_file_blocks_real_code_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "app").mkdir()
        (Path(tmp) / "app" / "main.py").write_text("print(1)\n")
        handlers = make_test_coverage_agent_handlers(tmp)

        result = handlers["write_file"](
            {"path": "app/main.py", "content": "print(2)\n"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert (Path(tmp) / "app" / "main.py").read_text() == "print(1)\n"


def test_write_file_blocks_non_md_non_docs_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_test_coverage_agent_handlers(tmp)
        result = handlers["write_file"]({"path": "test_new.py", "content": "x"})
        assert result.startswith("[POLICY DENIED]")
        assert not (Path(tmp) / "test_new.py").exists()


def test_write_file_allows_coverage_gaps_md() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_test_coverage_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "COVERAGE_GAPS.md", "content": "# Gaps\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "COVERAGE_GAPS.md").read_text() == "# Gaps\n"


def test_write_file_allows_docs_subpath() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_test_coverage_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/coverage_gaps.md", "content": "# Gaps\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "docs" / "coverage_gaps.md").read_text() == "# Gaps\n"


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_test_coverage_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/../../../etc/evil.md", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


def test_bash_still_scoped_to_test_runner_only() -> None:
    """bash is already correctly scoped (make_test_runner_bash_handler) —
    this fix must not disturb that."""
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_test_coverage_agent_handlers(tmp)
        result = handlers["bash"]({"command": "rm -rf /"})
        assert not result.startswith("Written")
        assert "pytest" in result or "denied" in result.lower() or "[" in result


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_test_coverage_agent_handlers("/tmp")
    out = handlers["submit_test_coverage_agent"](
        {"summary": "Found 3 untested error paths", "coverage_pct": 82.5}
    )
    assert out == "Submitted."
    assert handlers["_result"]["coverage_pct"] == 82.5

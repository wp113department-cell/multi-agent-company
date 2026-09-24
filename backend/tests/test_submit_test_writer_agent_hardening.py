"""submit_test_writer_agent tool #268 — tool_enhance.md
productionization pass (2026-09-18).

A distinct variant of the write_file finding class already fixed on 22
sibling agents: unlike those write_docs-only agents, test_writer_agent's
own AGENT_CONTRACT genuinely needs
permissions=["read_repo","write_code","execute_tests"] — writing NEW
test files IS its job — so the .md/docs/** scope used elsewhere would
be wrong here (it's an Executor-tier agent, confirmed via bash already
scoped to make_test_runner_bash_handler). But
roles/test_writer_agent.md's own Non-Responsibilities explicitly
forbid "Changing application code to make it testable — report
testability blockers instead", and nothing enforced that: proved live
that write_file({"path": "app/main.py", ...}) genuinely overwrote real,
non-test application source. Fixed by scoping write_file to actual
test-file paths, grounded in this repo's own real pytest/Jest/Vitest
conventions (backend/pytest.ini's testpaths=tests with pytest's default
test_*.py/*_test.py discovery; apps/web/vitest.config.ts's own
`**/*.test.{ts,tsx}` include glob, plus Jest's well-known default
testMatch which also covers *.spec.*) — not an invented rule.

submit_test_writer_agent itself audited and found correct: this file
already has the correct final_state["result"]-first priority, with its
own dated comment from a prior audit pass — no change needed here.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.test_writer_agent import (
    _SUBMIT,
    AGENT_CONTRACT,
    make_test_writer_agent_handlers,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_test_writer_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_test_writer_agent" not in {t["name"] for t in CHAT_TOOLS}


def test_agent_contract_declares_real_write_code_need() -> None:
    """This agent's own contract explains why the blanket .md/docs/**
    scoping fix from the write_docs-only siblings doesn't apply here."""
    assert AGENT_CONTRACT["permissions"] == ["read_repo", "write_code", "execute_tests"]


def test_write_file_blocks_application_code() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "app").mkdir()
        (Path(tmp) / "app" / "main.py").write_text("def add(a, b): return a + b\n")
        handlers = make_test_writer_agent_handlers(tmp)

        result = handlers["write_file"](
            {"path": "app/main.py", "content": "def add(a, b): return 999\n"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert (
            Path(tmp) / "app" / "main.py"
        ).read_text() == "def add(a, b): return a + b\n"


def test_write_file_blocks_random_non_test_python_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_test_writer_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "random_helper.py", "content": "x = 1"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert not (Path(tmp) / "random_helper.py").exists()


def test_write_file_allows_tests_directory() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_test_writer_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "tests/test_main.py", "content": "def test_add(): pass\n"}
        )
        assert result.startswith("Written")


def test_write_file_allows_python_test_prefix() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_test_writer_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "test_something.py", "content": "def test_x(): pass\n"}
        )
        assert result.startswith("Written")


def test_write_file_allows_python_test_suffix() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_test_writer_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "something_test.py", "content": "def test_x(): pass\n"}
        )
        assert result.startswith("Written")


def test_write_file_allows_vitest_test_extension() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_test_writer_agent_handlers(tmp)
        result = handlers["write_file"](
            {
                "path": "apps/web/components/Button.test.tsx",
                "content": "test('x', () => {})",
            }
        )
        assert result.startswith("Written")


def test_write_file_allows_jest_spec_extension() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_test_writer_agent_handlers(tmp)
        result = handlers["write_file"](
            {
                "path": "apps/web/components/Button.spec.ts",
                "content": "test('x', () => {})",
            }
        )
        assert result.startswith("Written")


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_test_writer_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "tests/../../../etc/test_evil.py", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


def test_bash_still_scoped_to_test_runner_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_test_writer_agent_handlers(tmp)
        result = handlers["bash"]({"command": "rm -rf /"})
        assert not result.startswith("Written")


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_test_writer_agent_handlers("/tmp")
    out = handlers["submit_test_writer_agent"](
        {"summary": "Wrote 5 tests for the add() function", "findings": []}
    )
    assert out == "Submitted."
    assert handlers["_result"]["summary"] == "Wrote 5 tests for the add() function"

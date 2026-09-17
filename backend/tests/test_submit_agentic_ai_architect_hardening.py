"""submit_agentic_ai_architect tool #232 — tool_enhance.md
productionization pass (2026-09-17).

Same real, severe finding already found and fixed on sibling agent
accessibility_agent (tool #231): roles/agentic_ai_architect.md states
"Zero repo files modified (design-only role)" as a Quality Gate, and
AGENT_CONTRACT claims permissions=["read_repo", "write_docs"] — but
make_agentic_ai_architect_handlers() gave this agent the FULL,
UNRESTRICTED write_file from make_chat_handlers() (any path, including
real code files). Proved live: a direct
write_file({"path": "app/main.py", ...}) call genuinely overwrote a
real .py file, with no policy denial at all.

Fixed by scoping write_file to .md/docs/** only, matching the pattern
already established for the Day-53 doc-generator agents and just
applied to accessibility_agent.

submit_agentic_ai_architect itself audited and found correct: same
"raw = final_state["result"] if final_state["result"] else result"
pattern already confirmed live/not-dead on the sibling agent.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.agentic_ai_architect import (
    _SUBMIT,
    make_agentic_ai_architect_handlers,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_agentic_ai_architect"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_agentic_ai_architect" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The real finding: write_file must be scoped to .md/docs/** only
# ---------------------------------------------------------------------------


def test_write_file_blocks_real_code_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "app").mkdir()
        (Path(tmp) / "app" / "main.py").write_text("print(1)\n")
        handlers = make_agentic_ai_architect_handlers(tmp)

        result = handlers["write_file"](
            {"path": "app/main.py", "content": "print(2)\n"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert (Path(tmp) / "app" / "main.py").read_text() == "print(1)\n"


def test_write_file_blocks_non_md_non_docs_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_agentic_ai_architect_handlers(tmp)
        result = handlers["write_file"]({"path": "config.json", "content": "{}"})
        assert result.startswith("[POLICY DENIED]")
        assert not (Path(tmp) / "config.json").exists()


def test_write_file_allows_top_level_md() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_agentic_ai_architect_handlers(tmp)
        result = handlers["write_file"](
            {"path": "DESIGN.md", "content": "# Agentic Design\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "DESIGN.md").read_text() == "# Agentic Design\n"


def test_write_file_allows_docs_subpath() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_agentic_ai_architect_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/agentic_design.md", "content": "# Design\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "docs" / "agentic_design.md").read_text() == "# Design\n"


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_agentic_ai_architect_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/../../../etc/evil.md", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


# ---------------------------------------------------------------------------
# submit_agentic_ai_architect itself — legitimate-usage regression
# ---------------------------------------------------------------------------


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_agentic_ai_architect_handlers("/tmp")
    out = handlers["submit_agentic_ai_architect"](
        {"summary": "Proposed a 3-node graph", "graph_design": "A -> B -> C"}
    )
    assert out == "Submitted."
    assert handlers["_result"]["summary"] == "Proposed a 3-node graph"

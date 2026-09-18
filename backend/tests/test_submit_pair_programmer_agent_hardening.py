"""submit_pair_programmer_agent tool #255 — tool_enhance.md
productionization pass (2026-09-18).

Same real, severe finding class already found and fixed on 14 sibling
agents (#231, #232, #237-#240, #243-#246, #248-#250, #252, #254). This
agent doesn't use the exact phrase "read-only on code" in its own role
file, but tests/test_analyzer_tier_confirmed.py — this codebase's own
authoritative, locked-in classification test — lists
pair_programmer_agent among the "Analyzer tier" agents: those whose
role explicitly excludes editing/fixing/modifying real code (confirmed
by that test's own real assertion that these agents carry no
edit_file/bash tool at all). AGENT_CONTRACT matches that intent:
permissions=["read_repo", "write_docs"] and
side_effects=["writes code suggestions and implementation guides"] —
an output artifact, not a direct edit of the driver's real files (this
agent doesn't even have edit_file, only a single-shot write_file). But
make_pair_programmer_agent_handlers() gave this agent the FULL,
UNRESTRICTED write_file (any path, including real code files). Proved
live: a direct write_file({"path": "app/main.py", ...}) call genuinely
overwrote a real .py file, with no policy denial at all.

Fixed by scoping write_file to .md/docs/** only, matching the pattern
already established for the sibling agents above.

submit_pair_programmer_agent itself audited and found correct: same
"raw = final_state["result"] if final_state["result"] else result"
pattern already confirmed live/not-dead on sibling agents.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.pair_programmer_agent import (
    _SUBMIT,
    make_pair_programmer_agent_handlers,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_pair_programmer_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_pair_programmer_agent" not in {t["name"] for t in CHAT_TOOLS}


def test_confirmed_analyzer_tier_no_edit_file_or_bash() -> None:
    """Re-confirms the authoritative classification this fix relies
    on: this agent's real tool list has no edit_file/bash, matching
    tests/test_analyzer_tier_confirmed.py's own locked-in assertion."""
    from app.agents.pair_programmer_agent import _TOOLS

    real_tool_names = {t["name"] for t in _TOOLS}
    assert "edit_file" not in real_tool_names
    assert "bash" not in real_tool_names


# ---------------------------------------------------------------------------
# The real finding: write_file must be scoped to .md/docs/** only
# ---------------------------------------------------------------------------


def test_write_file_blocks_real_code_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "app").mkdir()
        (Path(tmp) / "app" / "main.py").write_text("print(1)\n")
        handlers = make_pair_programmer_agent_handlers(tmp)

        result = handlers["write_file"](
            {"path": "app/main.py", "content": "print(2)\n"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert (Path(tmp) / "app" / "main.py").read_text() == "print(1)\n"


def test_write_file_blocks_non_md_non_docs_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_pair_programmer_agent_handlers(tmp)
        result = handlers["write_file"]({"path": "config.json", "content": "{}"})
        assert result.startswith("[POLICY DENIED]")
        assert not (Path(tmp) / "config.json").exists()


def test_write_file_allows_top_level_md() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_pair_programmer_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "SUGGESTIONS.md", "content": "# Suggestions\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "SUGGESTIONS.md").read_text() == "# Suggestions\n"


def test_write_file_allows_docs_subpath() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_pair_programmer_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/suggestions.md", "content": "# Guide\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "docs" / "suggestions.md").read_text() == "# Guide\n"


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_pair_programmer_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/../../../etc/evil.md", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


# ---------------------------------------------------------------------------
# submit_pair_programmer_agent itself — legitimate-usage regression
# ---------------------------------------------------------------------------


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_pair_programmer_agent_handlers("/tmp")
    out = handlers["submit_pair_programmer_agent"](
        {"summary": "Guided implementation of the retry loop", "findings": []}
    )
    assert out == "Submitted."
    assert (
        handlers["_result"]["summary"] == "Guided implementation of the retry loop"
    )

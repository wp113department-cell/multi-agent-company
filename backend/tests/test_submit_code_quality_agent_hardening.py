"""submit_code_quality_agent tool #238 — tool_enhance.md
productionization pass (2026-09-17).

Same real, severe finding already found and fixed on sibling agents
accessibility_agent (tool #231), agentic_ai_architect (tool #232), and
code_explainer_agent (tool #237): roles/code_quality_agent.md states
"this role is read-only on code" and lists "Modifying, creating, or
deleting any repo file" as an automatic Failure Condition, and
AGENT_CONTRACT claims permissions=["read_repo", "write_docs"] — but
make_code_quality_agent_handlers() gave this agent the FULL,
UNRESTRICTED write_file from make_chat_handlers() (any path, including
real code files). Proved live: a direct
write_file({"path": "app/main.py", ...}) call genuinely overwrote a
real .py file, with no policy denial at all.

Fixed by scoping write_file to .md/docs/** only, matching the pattern
already established for the Day-53 doc-generator agents and the
sibling agents above.

submit_code_quality_agent itself audited and found correct: same
"raw = final_state["result"] if final_state["result"] else result"
pattern already confirmed live/not-dead on sibling agents.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.code_quality_agent import _SUBMIT, make_code_quality_agent_handlers
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_code_quality_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_code_quality_agent" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The real finding: write_file must be scoped to .md/docs/** only
# ---------------------------------------------------------------------------


def test_write_file_blocks_real_code_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "app").mkdir()
        (Path(tmp) / "app" / "main.py").write_text("print(1)\n")
        handlers = make_code_quality_agent_handlers(tmp)

        result = handlers["write_file"](
            {"path": "app/main.py", "content": "print(2)\n"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert (Path(tmp) / "app" / "main.py").read_text() == "print(1)\n"


def test_write_file_blocks_non_md_non_docs_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_code_quality_agent_handlers(tmp)
        result = handlers["write_file"]({"path": "config.json", "content": "{}"})
        assert result.startswith("[POLICY DENIED]")
        assert not (Path(tmp) / "config.json").exists()


def test_write_file_allows_top_level_md() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_code_quality_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "QUALITY_REPORT.md", "content": "# Quality Report\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "QUALITY_REPORT.md").read_text() == "# Quality Report\n"


def test_write_file_allows_docs_subpath() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_code_quality_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/quality_report.md", "content": "# Report\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "docs" / "quality_report.md").read_text() == "# Report\n"


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_code_quality_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/../../../etc/evil.md", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


# ---------------------------------------------------------------------------
# submit_code_quality_agent itself — legitimate-usage regression
# ---------------------------------------------------------------------------


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_code_quality_agent_handlers("/tmp")
    out = handlers["submit_code_quality_agent"](
        {"summary": "Reviewed the billing module", "findings": []}
    )
    assert out == "Submitted."
    assert handlers["_result"]["summary"] == "Reviewed the billing module"

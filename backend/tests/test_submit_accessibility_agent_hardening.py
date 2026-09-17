"""submit_accessibility_agent tool #231 — tool_enhance.md
productionization pass (2026-09-17).

Real, severe finding discovered while auditing this agent's tool
wiring: roles/accessibility_agent.md explicitly states "this role is
read-only on code" and lists "Modifying, creating, or deleting any
repo file" as an automatic Failure Condition; AGENT_CONTRACT itself
claims `side_effects=["writes accessibility audit .md files"]` and
`permissions=["read_repo", "write_docs"]` — but
`make_accessibility_agent_handlers()` gave this agent the FULL,
UNRESTRICTED `write_file` from `make_chat_handlers()` (any path,
including real code files). Proved live: a direct
`write_file({"path": "app/main.py", ...})` call genuinely overwrote a
real .py file, with no policy denial at all.

Fixed by scoping `write_file` to `.md`/`docs/**` only, matching the
established pattern already used by the Day-53 doc-generator agents
(`make_doc_generator_handlers`'s `dg_write_file`).

`submit_accessibility_agent` itself (the tool this turn is nominally
about) was audited and found correct: `result.update(inp)` accumulates
into a closure-local dict, but `run_accessibility_agent()`'s own
`raw = final_state["result"] if final_state["result"] else result`
line (confirmed via direct inspection) already prioritizes the real,
graph-enforced `final_state["result"]` — not a dead-accumulator case.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.accessibility_agent import (
    _SUBMIT,
    make_accessibility_agent_handlers,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_accessibility_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_accessibility_agent" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The real finding: write_file must be scoped to .md/docs/** only
# ---------------------------------------------------------------------------


def test_write_file_blocks_real_code_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "app").mkdir()
        (Path(tmp) / "app" / "main.py").write_text("print(1)\n")
        handlers = make_accessibility_agent_handlers(tmp)

        result = handlers["write_file"](
            {"path": "app/main.py", "content": "print(2)\n"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert (Path(tmp) / "app" / "main.py").read_text() == "print(1)\n"


def test_write_file_blocks_non_md_non_docs_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_accessibility_agent_handlers(tmp)
        result = handlers["write_file"]({"path": "config.json", "content": "{}"})
        assert result.startswith("[POLICY DENIED]")
        assert not (Path(tmp) / "config.json").exists()


def test_write_file_allows_top_level_md() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_accessibility_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "AUDIT.md", "content": "# Accessibility Audit\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "AUDIT.md").read_text() == "# Accessibility Audit\n"


def test_write_file_allows_docs_subpath() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_accessibility_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/a11y_report.md", "content": "# Report\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "docs" / "a11y_report.md").read_text() == "# Report\n"


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_accessibility_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/../../../etc/evil.md", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


# ---------------------------------------------------------------------------
# submit_accessibility_agent itself — legitimate-usage regression
# ---------------------------------------------------------------------------


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_accessibility_agent_handlers("/tmp")
    out = handlers["submit_accessibility_agent"](
        {"summary": "Audited login form", "findings": ["missing alt text"]}
    )
    assert out == "Submitted."
    assert handlers["_result"]["summary"] == "Audited login form"

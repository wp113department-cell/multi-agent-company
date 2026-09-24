"""submit_onboarding_agent tool #254 — tool_enhance.md
productionization pass (2026-09-18).

A real, genuine variant of the finding already found and fixed on 13
sibling agents (#231, #232, #237-#240, #243-#246, #248-#250, #252):
unlike those, roles/onboarding_agent.md doesn't use the exact phrase
"read-only on code", but AGENT_CONTRACT still explicitly claims
permissions=["read_repo", "write_docs"] (never "write_repo") and
side_effects scoped to exactly one artifact — "writes onboarding
documentation" / "edits an existing onboarding guide". This agent's
entire declared purpose is a single doc artifact, with no legitimate
reason to ever touch source code. But make_onboarding_agent_handlers()
gave this agent BOTH the FULL, UNRESTRICTED write_file AND edit_file
(any path, including real code files). Proved live: a direct
write_file({"path": "app/main.py", ...}) call genuinely overwrote a
real .py file, and edit_file on the same path genuinely edited it too.

Fixed by scoping BOTH write_file and edit_file to .md/docs/** — the
first tool in this initiative to need edit_file scoped alongside
write_file.

submit_onboarding_agent itself audited and found correct: same
"raw = final_state["result"] if final_state["result"] else result"
pattern already confirmed live/not-dead on sibling agents.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.onboarding_agent import _SUBMIT, make_onboarding_agent_handlers
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_onboarding_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_onboarding_agent" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The real finding: write_file AND edit_file must be scoped to .md/docs/**
# ---------------------------------------------------------------------------


def test_write_file_blocks_real_code_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "app").mkdir()
        (Path(tmp) / "app" / "main.py").write_text("print(1)\n")
        handlers = make_onboarding_agent_handlers(tmp)

        result = handlers["write_file"](
            {"path": "app/main.py", "content": "print(2)\n"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert (Path(tmp) / "app" / "main.py").read_text() == "print(1)\n"


def test_edit_file_blocks_real_code_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "app").mkdir()
        (Path(tmp) / "app" / "main.py").write_text("print(1)\n")
        handlers = make_onboarding_agent_handlers(tmp)

        result = handlers["edit_file"](
            {
                "path": "app/main.py",
                "old_string": "print(1)",
                "new_string": "print(999)",
            }
        )
        assert result.startswith("[POLICY DENIED]")
        assert (Path(tmp) / "app" / "main.py").read_text() == "print(1)\n"


def test_write_file_blocks_non_md_non_docs_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_onboarding_agent_handlers(tmp)
        result = handlers["write_file"]({"path": "config.json", "content": "{}"})
        assert result.startswith("[POLICY DENIED]")
        assert not (Path(tmp) / "config.json").exists()


def test_write_file_allows_top_level_md() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_onboarding_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "ONBOARDING.md", "content": "# Onboarding\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "ONBOARDING.md").read_text() == "# Onboarding\n"


def test_edit_file_allows_editing_the_onboarding_guide() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "ONBOARDING.md").write_text("# Onboarding\n")
        handlers = make_onboarding_agent_handlers(tmp)
        result = handlers["edit_file"](
            {
                "path": "ONBOARDING.md",
                "old_string": "Onboarding",
                "new_string": "Getting Started",
            }
        )
        assert result.startswith("Edited")
        assert (Path(tmp) / "ONBOARDING.md").read_text() == "# Getting Started\n"


def test_write_file_allows_docs_subpath() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_onboarding_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/onboarding.md", "content": "# Guide\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "docs" / "onboarding.md").read_text() == "# Guide\n"


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_onboarding_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/../../../etc/evil.md", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


# ---------------------------------------------------------------------------
# submit_onboarding_agent itself — legitimate-usage regression
# ---------------------------------------------------------------------------


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_onboarding_agent_handlers("/tmp")
    out = handlers["submit_onboarding_agent"](
        {"summary": "Wrote a minimal getting-started guide", "findings": []}
    )
    assert out == "Submitted."
    assert handlers["_result"]["summary"] == "Wrote a minimal getting-started guide"

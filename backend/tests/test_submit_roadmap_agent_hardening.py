"""submit_roadmap_agent tool #260 — tool_enhance.md productionization pass
(2026-09-18).

Same real, severe finding class already found and fixed on 16 sibling
agents: roles/roadmap_agent.md's own Quality Gate says "Zero repo
files modified (design-only role)", and AGENT_CONTRACT claims
permissions=["read_repo","write_docs"] (never "write_repo") and
side_effects=["writes roadmap documents"] — but
make_roadmap_agent_handlers() gave this agent the FULL, UNRESTRICTED
write_file, able to write real application code too. Proved live: a
direct write_file({"path": "app/main.py", ...}) call genuinely
overwrote a real .py file. Fixed with the same .md/docs/** scoping
already established for the sibling agents.

submit_roadmap_agent itself audited and found correct: same
"raw = final_state["result"] if final_state["result"] else result"
pattern already confirmed live/not-dead on sibling agents (unlike the
backwards-priority bug just fixed on tools #258/#259 — this agent's
line was already correct).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.roadmap_agent import (
    _SUBMIT,
    AGENT_CONTRACT,
    make_roadmap_agent_handlers,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_roadmap_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_roadmap_agent" not in {t["name"] for t in CHAT_TOOLS}


def test_agent_contract_claims_write_docs_only() -> None:
    assert AGENT_CONTRACT["permissions"] == ["read_repo", "write_docs"]


def test_write_file_blocks_real_code_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "app").mkdir()
        (Path(tmp) / "app" / "main.py").write_text("print(1)\n")
        handlers = make_roadmap_agent_handlers(tmp)

        result = handlers["write_file"](
            {"path": "app/main.py", "content": "print(2)\n"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert (Path(tmp) / "app" / "main.py").read_text() == "print(1)\n"


def test_write_file_blocks_non_md_non_docs_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_roadmap_agent_handlers(tmp)
        result = handlers["write_file"]({"path": "config.json", "content": "{}"})
        assert result.startswith("[POLICY DENIED]")
        assert not (Path(tmp) / "config.json").exists()


def test_write_file_allows_roadmap_md() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_roadmap_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "ROADMAP.md", "content": "# Roadmap\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "ROADMAP.md").read_text() == "# Roadmap\n"


def test_write_file_allows_docs_subpath() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_roadmap_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/roadmap.md", "content": "# Roadmap\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "docs" / "roadmap.md").read_text() == "# Roadmap\n"


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_roadmap_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/../../../etc/evil.md", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_roadmap_agent_handlers("/tmp")
    out = handlers["submit_roadmap_agent"](
        {"summary": "Phased roadmap for Q1-Q3", "roadmap": []}
    )
    assert out == "Submitted."
    assert handlers["_result"]["summary"] == "Phased roadmap for Q1-Q3"

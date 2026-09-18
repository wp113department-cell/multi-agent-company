"""submit_tech_advisor_agent tool #266 — tool_enhance.md
productionization pass (2026-09-18).

Same real, severe finding class already found and fixed on 21 sibling
agents: roles/tech_advisor_agent.md's own Non-Responsibilities say
"Implementing the chosen technology (the relevant coder/dev agent's
scope)", and AGENT_CONTRACT claims permissions=["read_repo",
"write_docs"] (never "write_repo") with side_effects=["writes
technology-comparison reports"] — the real, intended output is a
comparison report. But make_tech_advisor_agent_handlers() gave this
agent the FULL, UNRESTRICTED write_file, able to write real
application code too. Proved live: a direct write_file({"path":
"app/main.py", ...}) call genuinely overwrote a real .py file. Fixed
with the same .md/docs/** scoping already established for the sibling
agents.

score_tech_options (tool #230, fixed in an earlier turn — real
deterministic weighted-sum arithmetic, blocking_until-gated before
submit) is untouched by and unaffected by this fix — re-confirmed live
below. submit_tech_advisor_agent itself audited and found correct:
this file already has the correct final_state["result"]-first priority
plus the "trust the code, not the model's claim" override for
ranked_options/scoring_criteria/normalized_weights — no change needed
here.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.tech_advisor_agent import (
    _SUBMIT,
    AGENT_CONTRACT,
    make_tech_advisor_agent_handlers,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_tech_advisor_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_tech_advisor_agent" not in {t["name"] for t in CHAT_TOOLS}


def test_agent_contract_claims_write_docs_only() -> None:
    assert AGENT_CONTRACT["permissions"] == ["read_repo", "write_docs"]


def test_write_file_blocks_real_code_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "app").mkdir()
        (Path(tmp) / "app" / "main.py").write_text("print(1)\n")
        handlers = make_tech_advisor_agent_handlers(tmp)

        result = handlers["write_file"](
            {"path": "app/main.py", "content": "print(2)\n"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert (Path(tmp) / "app" / "main.py").read_text() == "print(1)\n"


def test_write_file_blocks_non_md_non_docs_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_tech_advisor_agent_handlers(tmp)
        result = handlers["write_file"]({"path": "config.json", "content": "{}"})
        assert result.startswith("[POLICY DENIED]")
        assert not (Path(tmp) / "config.json").exists()


def test_write_file_allows_comparison_report_md() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_tech_advisor_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "TECH_COMPARISON.md", "content": "# Comparison\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "TECH_COMPARISON.md").read_text() == "# Comparison\n"


def test_write_file_allows_docs_subpath() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_tech_advisor_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/tech_comparison.md", "content": "# Comparison\n"}
        )
        assert result.startswith("Written")
        assert (
            Path(tmp) / "docs" / "tech_comparison.md"
        ).read_text() == "# Comparison\n"


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_tech_advisor_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/../../../etc/evil.md", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


def test_score_tech_options_unaffected_by_write_file_scoping() -> None:
    """score_tech_options (tool #230) must keep working exactly as
    before — this fix only touches write_file."""
    handlers = make_tech_advisor_agent_handlers("/tmp")
    result = handlers["score_tech_options"](
        {
            "options": [
                {"name": "A", "criteria_scores": {"x": 5}},
                {"name": "B", "criteria_scores": {"x": 2}},
            ]
        }
    )
    assert "A" in result
    assert "weighted score 5.000" in result


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_tech_advisor_agent_handlers("/tmp")
    out = handlers["submit_tech_advisor_agent"](
        {"summary": "Recommend PostgreSQL over MongoDB", "findings": []}
    )
    assert out == "Submitted."
    assert (
        handlers["_result"]["summary"] == "Recommend PostgreSQL over MongoDB"
    )

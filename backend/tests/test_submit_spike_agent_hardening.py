"""submit_spike_agent tool #264 — tool_enhance.md productionization pass
(2026-09-18).

Same real, severe finding class already found and fixed on 20 sibling
agents: roles/spike_agent.md's "reports, specs, scripts, docs"
write_file phrasing is shared boilerplate across 15 role files (see
tool #261's rollback_agent for the same discernment) — not decisive on
its own. This agent's own Non-Responsibilities instead say "Producing
production code — spike output is findings, not features", and
AGENT_CONTRACT claims permissions=["read_repo","write_docs"] (never
"write_repo") with side_effects=["writes spike research reports"] —
the real, intended output is a research report. But
make_spike_agent_handlers() gave this agent the FULL, UNRESTRICTED
write_file, able to write real application code too. Proved live: a
direct write_file({"path": "app/main.py", ...}) call genuinely
overwrote a real .py file. Fixed with the same .md/docs/** scoping
already established for the sibling agents.

submit_spike_agent itself audited and found correct: this file already
has the correct final_state["result"]-first priority, with its own
dated comment from a prior audit pass — no change needed here. This
agent is also the config-driven confidence-gated-control-flow pilot
(quality_gate_min_confidence_by_agent) — untouched by this fix.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.spike_agent import (
    _SUBMIT,
    AGENT_CONTRACT,
    make_spike_agent_handlers,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_spike_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_spike_agent" not in {t["name"] for t in CHAT_TOOLS}


def test_agent_contract_claims_write_docs_only() -> None:
    assert AGENT_CONTRACT["permissions"] == ["read_repo", "write_docs"]


def test_write_file_blocks_real_code_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "app").mkdir()
        (Path(tmp) / "app" / "main.py").write_text("print(1)\n")
        handlers = make_spike_agent_handlers(tmp)

        result = handlers["write_file"](
            {"path": "app/main.py", "content": "print(2)\n"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert (Path(tmp) / "app" / "main.py").read_text() == "print(1)\n"


def test_write_file_blocks_non_md_non_docs_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_spike_agent_handlers(tmp)
        result = handlers["write_file"]({"path": "prototype.py", "content": "x = 1"})
        assert result.startswith("[POLICY DENIED]")
        assert not (Path(tmp) / "prototype.py").exists()


def test_write_file_allows_spike_report_md() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_spike_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "SPIKE_REPORT.md", "content": "# Spike\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "SPIKE_REPORT.md").read_text() == "# Spike\n"


def test_write_file_allows_docs_subpath() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_spike_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/spike_report.md", "content": "# Spike\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "docs" / "spike_report.md").read_text() == "# Spike\n"


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_spike_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/../../../etc/evil.md", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_spike_agent_handlers("/tmp")
    out = handlers["submit_spike_agent"](
        {"summary": "Recommend library X over Y", "findings": []}
    )
    assert out == "Submitted."
    assert handlers["_result"]["summary"] == "Recommend library X over Y"

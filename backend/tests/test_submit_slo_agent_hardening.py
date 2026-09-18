"""submit_slo_agent tool #263 — tool_enhance.md productionization pass
(2026-09-18).

Same real, severe finding class already found and fixed on 19 sibling
agents: roles/slo_agent.md's "reports, specs, scripts, docs"
write_file phrasing is shared boilerplate across 15 role files (see
tool #261's rollback_agent for the same discernment) — not decisive on
its own. This agent's own Non-Responsibilities instead say "Modifying
monitoring config" is out of scope, and AGENT_CONTRACT claims
permissions=["read_repo","write_docs"] (never "write_repo") with
side_effects=["writes SLO specification documents"] — the real,
intended output is a spec document. But make_slo_agent_handlers() gave
this agent the FULL, UNRESTRICTED write_file, able to write real
application code too. Proved live: a direct write_file({"path":
"app/main.py", ...}) call genuinely overwrote a real .py file. Fixed
with the same .md/docs/** scoping already established for the sibling
agents.

submit_slo_agent itself audited and found correct: this file already
has the correct final_state["result"]-first priority, with its own
dated comment from a prior audit pass — no change needed here.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.slo_agent import (
    _SUBMIT,
    AGENT_CONTRACT,
    make_slo_agent_handlers,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT["name"] == "submit_slo_agent"
    assert _SUBMIT["input_schema"]["required"] == ["summary"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "submit_slo_agent" not in {t["name"] for t in CHAT_TOOLS}


def test_agent_contract_claims_write_docs_only() -> None:
    assert AGENT_CONTRACT["permissions"] == ["read_repo", "write_docs"]


def test_write_file_blocks_real_code_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "app").mkdir()
        (Path(tmp) / "app" / "main.py").write_text("print(1)\n")
        handlers = make_slo_agent_handlers(tmp)

        result = handlers["write_file"](
            {"path": "app/main.py", "content": "print(2)\n"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert (Path(tmp) / "app" / "main.py").read_text() == "print(1)\n"


def test_write_file_blocks_monitoring_config() -> None:
    """Non-Responsibilities explicitly forbid modifying monitoring
    config — proving the scoping fix correctly blocks that path too."""
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_slo_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "prometheus.yml", "content": "global: {}"}
        )
        assert result.startswith("[POLICY DENIED]")
        assert not (Path(tmp) / "prometheus.yml").exists()


def test_write_file_allows_slo_spec_md() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_slo_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "SLO_SPEC.md", "content": "# SLOs\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "SLO_SPEC.md").read_text() == "# SLOs\n"


def test_write_file_allows_docs_subpath() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_slo_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/slo_spec.md", "content": "# SLOs\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "docs" / "slo_spec.md").read_text() == "# SLOs\n"


def test_write_file_worktree_escape_still_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_slo_agent_handlers(tmp)
        result = handlers["write_file"](
            {"path": "docs/../../../etc/evil.md", "content": "x"}
        )
        assert result.startswith("[POLICY DENIED]")


def test_submit_accumulates_into_result_dict() -> None:
    handlers = make_slo_agent_handlers("/tmp")
    out = handlers["submit_slo_agent"](
        {"summary": "Defined availability and latency SLOs", "findings": []}
    )
    assert out == "Submitted."
    assert (
        handlers["_result"]["summary"] == "Defined availability and latency SLOs"
    )

"""list_registered_agents tool #222 — tool_enhance.md productionization
pass (2026-09-17).

No security vulnerability and no functional bug found — this audit's
real conclusion. Takes no meaningful input at all (schema declares
zero properties).

Unlike tool #219's list_all_tool_specs (found to only scan one
module, missing real agent-local tool schemas), this tool's
completeness is already correct: it calls
ensure_all_agents_registered() first — a genuine full-codebase scan of
every module under app/agents/ — before reading the capability
registry, confirmed by direct comparison against a real, independent
count of agent modules.

Already has thorough coverage in
tests/test_gap53_doc_generators.py::TestListRegisteredAgents
(including a fleet-wide duplicate-capability-tag regression guard) —
re-read and re-verified as still passing.
"""

from __future__ import annotations

import json

from app.agents.tools import CHAT_TOOLS, list_registered_agents
from app.tools.agents.list_registered_agents import (
    LIST_REGISTERED_AGENTS_TOOL,
    list_registered_agents_handler,
)


def test_schema() -> None:
    assert LIST_REGISTERED_AGENTS_TOOL["name"] == "list_registered_agents"
    assert LIST_REGISTERED_AGENTS_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "list_registered_agents" not in {t["name"] for t in CHAT_TOOLS}


def test_returns_real_agents_with_full_contract_fields() -> None:
    data = json.loads(list_registered_agents_handler({}))
    assert len(data) > 50  # 85 real agents at time of writing
    names = {a["name"] for a in data}
    assert "readme_agent" in names
    assert "agent_roster_doc_agent" in names
    for entry in data:
        assert entry["name"]
        assert isinstance(entry["tools"], list)
        assert entry["risk_level"] in ("low", "medium", "high")


def test_idempotent_across_repeated_calls() -> None:
    """Registration is write-once-per-name/update-in-place — repeated
    calls in the same process must not duplicate or grow entries."""
    data1 = json.loads(list_registered_agents_handler({}))
    data2 = json.loads(list_registered_agents_handler({}))
    assert len(data1) == len(data2)
    assert {a["name"] for a in data1} == {a["name"] for a in data2}


def test_tools_module_reexports_same_handler_by_identity() -> None:
    from app.agents.tools import _LIST_REGISTERED_AGENTS_TOOL

    assert list_registered_agents is list_registered_agents_handler
    assert _LIST_REGISTERED_AGENTS_TOOL is LIST_REGISTERED_AGENTS_TOOL


def test_agent_roster_doc_agent_wires_the_shared_handler() -> None:
    from app.agents.agent_roster_doc_agent import make_agent_roster_doc_handlers

    handlers = make_agent_roster_doc_handlers("/tmp")
    assert handlers["list_registered_agents"] is list_registered_agents_handler

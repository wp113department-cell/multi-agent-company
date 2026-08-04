"""Stage 4 Tier 3 (2026-08-05, answers.md Q20) — "the dedicated research.py
agent's tool handler dict DOES wire web_search, but its tool-schema list
(RESEARCH_TOOLS, what's actually sent to the model) never includes it — so
the one agent whose entire job is web research cannot actually call
web_search."

Confirmed live before fixing: `make_research_handlers()` (tools.py:1772)
wires a real `handlers["web_search"] = web_search`, but the old
`RESEARCH_TOOLS` schema array (tools.py:1729) never listed `_WEB_SEARCH_TOOL`
— Anthropic's tool-use API only allows calling tools present in the
request's own `tools` array, so the handler was unreachable regardless of
what the model tried. `research.py::AGENT_CONTRACT["allowed_tools"]` had the
same omission while its own `capabilities` list already claimed
`"web_search"` — a real contract/reality mismatch.

Not the same thing as a Q6-style "should this be widened fleet-wide"
scope decision — this is the fleet's own single dedicated research agent
missing a tool that is already central to its stated job.
"""

from __future__ import annotations

from app.agents.research import AGENT_CONTRACT
from app.agents.tools import RESEARCH_TOOLS, make_research_handlers


def test_research_tools_schema_now_includes_web_search() -> None:
    names = {t["name"] for t in RESEARCH_TOOLS}
    assert "web_search" in names


def test_research_agent_contract_allowed_tools_includes_web_search() -> None:
    assert "web_search" in AGENT_CONTRACT["allowed_tools"]


def test_research_capability_registry_entry_tools_include_web_search() -> None:
    """_register() (research.py) already claimed capabilities=[..., "web_search",
    ...] in the fleet capability registry before this fix -- assert the
    claim is now backed by a real reachable tool in the same entry's
    `tools` list, not just a label."""
    from app.fleet.capability_registry import get_capability_registry

    entry = get_capability_registry().get("research")
    assert entry is not None
    assert "web_search" in entry.capabilities
    assert "web_search" in entry.tools


def test_research_handlers_still_wire_the_real_web_search_function() -> None:
    """The handler-dict side was already correct -- this fix must not have
    broken it while fixing the schema side."""
    handlers = make_research_handlers("/tmp")
    assert "web_search" in handlers
    assert callable(handlers["web_search"])


def test_research_agent_still_cannot_write() -> None:
    """Regression guard: adding web_search must not have widened the agent's
    write/bash surface."""
    names = {t["name"] for t in RESEARCH_TOOLS}
    assert "write_file" not in names
    assert "submit_patch" not in names
    assert "bash" not in names

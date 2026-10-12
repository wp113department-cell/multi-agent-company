"""Every tool in TOOL_MANIFEST is declared by at least one registered agent.

Cross-audit check (2026-10-02, prompted by the Antigravity audit's suggestion
to test tool reachability): two manifest entries were reachable by no agent —
a phantom "type" tool from Day 0 with no handler anywhere, and
capability_gap_scan, which agent_advisor really uses but did not declare in
AGENT_CONTRACT["allowed_tools"]. The phantom was removed; capability_gap_scan
is deliberately outside the general contract (only agent_advisor's scan loop
uses it — see tests/test_capability_gap_scan_hardening.py), so it is the one
documented exception below.
"""

from __future__ import annotations

import importlib
import pkgutil

import app.agents as agents_pkg
from app.fleet.capability_registry import get_capability_registry
from app.fleet.tool_manifest import TOOL_MANIFEST

# Tools used only through an agent's own scan path, by design (documented).
_SCAN_ONLY = {"capability_gap_scan"}


def test_every_manifest_tool_is_declared_by_some_agent() -> None:
    for m in pkgutil.iter_modules(agents_pkg.__path__):
        try:
            importlib.import_module(f"app.agents.{m.name}")
        except Exception:
            pass
    declared: set[str] = set()
    for contract in get_capability_registry().all():
        declared |= set(getattr(contract, "tools", []) or [])
    # UPDATED (2026-10-12): Sol A22 gave manifest entries to tools agents
    # define in their own tool lists (scan/apply phases, local tools), and
    # C6 stopped offering the chat its write tools — those stay in the
    # CHAT_TOOLS catalogue. A tool counts as reachable when an agent
    # declares it, defines it, or the catalogue holds it.
    from app.agents.tools import CHAT_TOOLS

    declared |= {t["name"] for t in CHAT_TOOLS}
    declared |= _defined_in_agent_tool_lists()
    orphans = sorted(set(TOOL_MANIFEST) - declared - _SCAN_ONLY)
    assert not orphans, f"manifest tools no agent declares: {orphans}"


def _defined_in_agent_tool_lists() -> set[str]:
    found: set[str] = set()

    def visit(obj: object) -> None:
        if isinstance(obj, (list, tuple)):
            for item in obj:
                visit(item)
        elif isinstance(obj, dict) and isinstance(obj.get("name"), str):
            if "input_schema" in obj:
                found.add(obj["name"])

    for m in pkgutil.iter_modules(agents_pkg.__path__):
        module = importlib.import_module(f"app.agents.{m.name}")
        for value in vars(module).values():
            if isinstance(value, (list, tuple, dict)):
                visit(value)
    return found

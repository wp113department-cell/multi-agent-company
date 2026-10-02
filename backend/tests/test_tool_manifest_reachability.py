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
    orphans = sorted(set(TOOL_MANIFEST) - declared - _SCAN_ONLY)
    assert not orphans, f"manifest tools no agent declares: {orphans}"

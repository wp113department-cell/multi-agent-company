"""list_registered_agents tool — tool_enhance.md productionization
pass, tool #222 (2026-09-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: list_registered_agents
Old path: app/agents/tools.py (`_LIST_REGISTERED_AGENTS_TOOL` schema
    dict, module-level `list_registered_agents()` function).
New path: app/tools/agents/list_registered_agents.py (this file) —
    `LIST_REGISTERED_AGENTS_TOOL`, `list_registered_agents_handler`.
Affected agents: exactly 1 real agent, confirmed via direct grep —
    `agent_roster_doc_agent` — matching `tool_inventory.json`'s
    `agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` —
    confirmed via membership check.
Affected modules: app/agents/tools.py re-exports both names under
    their old locations — the real consumer file continues
    `from app.agents.tools import list_registered_agents` unchanged.
Affected tests: `tests/test_gap53_doc_generators.py::TestListRegisteredAgents`
    (3 tests, including a fleet-wide duplicate-capability-tag
    regression guard) already exercises this tool thoroughly against
    the real capability_registry — re-run and confirmed passing
    unchanged. New tests added: see
    tests/test_list_registered_agents_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/list_registered_agents.md.
---------------------------------------------------------------------------

No security vulnerability and no functional bug found — this audit's
real conclusion. Takes no meaningful input at all (schema declares
zero properties, `inp` is unused).

Unlike tool #219's `list_all_tool_specs` (which was found to only scan
one module, missing real agent-local tool schemas), this tool's
completeness is already correct: it calls
`ensure_all_agents_registered()` first — which imports EVERY real
agent module under `app/agents/` (scanning the directory at runtime,
not a hardcoded name list, so new agents are picked up automatically)
so each one's `_register()` hook fires — before reading
`get_capability_registry().all()`. Confirmed this is a genuine,
full-codebase scan, not a partial one.

Investigated and confirmed safe:
  - `ensure_all_agents_registered()` never raises by its own contract
    and implementation (a `try`/`except Exception` around each
    individual module import) — one broken agent module cannot break
    this tool for every other agent.
  - `CapabilityRegistry.all()` is a simple, lock-protected read of an
    in-memory dict — no injection surface, no external I/O.
  - Registration is write-once-per-name/update-in-place (a dict keyed
    by agent name), so repeated calls (e.g. multiple doc-generation
    runs in the same process) are idempotent, not duplicate-accumulating.
"""

from __future__ import annotations

from typing import Any

LIST_REGISTERED_AGENTS_TOOL: dict[str, Any] = {
    "name": "list_registered_agents",
    "description": "Real introspection of every registered agent's capability contract (name, description, tools, capabilities, risk_level, dependencies) from the actual fleet capability_registry — not a guess from file names.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


def list_registered_agents_handler(inp: dict[str, Any]) -> str:
    """Core list_registered_agents logic — real, read-only fleet
    capability_registry introspection, no injection surface (empty
    schema, inp unused)."""
    import json as _json

    from app.fleet.capability_registry import (
        ensure_all_agents_registered,
        get_capability_registry,
    )

    ensure_all_agents_registered()
    entries = get_capability_registry().all()
    data = [
        {
            "name": e.name,
            "description": e.description,
            "tools": e.tools,
            "input_types": e.input_types,
            "output_types": e.output_types,
            "capabilities": e.capabilities,
            "risk_level": e.risk_level,
            "dependencies": e.dependencies,
        }
        for e in sorted(entries, key=lambda e: e.name)
    ]
    return _json.dumps(data, indent=2)

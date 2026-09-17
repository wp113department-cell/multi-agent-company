"""audit_log_read tool — tool_enhance.md productionization pass,
tool #216 (2026-09-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: audit_log_read
Old path: app/agents/tools.py (`_AUDIT_LOG_READ_TOOL` schema dict,
    module-level `audit_log_read()` function — the one real
    implementation).
New path: app/tools/agents/audit_log_read.py (this file) —
    `AUDIT_LOG_READ_TOOL`, `audit_log_read_handler`.
Affected agents: exactly 2 real agents, confirmed via direct grep —
    `agent_advisor`, `agent_debugger` — matching
    `tool_inventory.json`'s `agent_count: 2` exactly. Deliberately NOT
    in `CHAT_TOOLS` — confirmed via membership check.
Affected modules: app/agents/tools.py re-exports the schema and
    function under their old names — both real consumer files
    continue `from app.agents.tools import audit_log_read` unchanged.
Affected tests: `tests/test_day9_fleet_agents.py::test_audit_log_read_filters_by_agent`
    already exercises this tool via a real call (in-process, no DB) —
    re-run and confirmed passing unchanged, doesn't pass a malformed
    `n`, so no fix needed there. New tests added: see
    tests/test_audit_log_read_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/audit_log_read.md.
---------------------------------------------------------------------------

No injection surface: entirely in-process, reading from
`app.fleet.audit_log`'s real in-memory ring buffer (`AuditLog.recent()`)
— no SQL, no subprocess, no filesystem access.

Same real finding class already found and fixed on tool #215
(`fleet_metrics_read`), sibling tool sharing the same
"SCAN phase (autonomous, read-only)" comment block in the old
location: zero `try`/`except` anywhere in the body.
`n = int(inp.get("n", 50))` was a bare coercion with no guard. Proved
live: `audit_log_read({"n": "not-a-number"})` raised a real, completely
uncaught `ValueError`.

Fixed identically to tool #215: wrapped the numeric coercion in its
own `try`/`except (TypeError, ValueError)`, returning a clean
`"[ERROR] audit_log_read: invalid numeric argument for n: ..."` string
instead of raising. All other behavior (agent-name filtering,
most-recent-N-entries windowing, formatted timestamp/action/outcome
lines) preserved verbatim.
"""

from __future__ import annotations

from typing import Any

AUDIT_LOG_READ_TOOL: dict[str, Any] = {
    "name": "audit_log_read",
    "description": "Read the fleet audit trail: what actions ran, for which agent, with what outcome. Use this to diagnose failing agents from real evidence, not speculation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Filter to one agent. Omit for the most recent entries across all agents.",
            },
            "n": {
                "type": "integer",
                "description": "Max entries to return (default 50).",
            },
        },
        "required": [],
    },
}


def audit_log_read_handler(inp: dict[str, Any]) -> str:
    """Core audit_log_read logic — real, in-process, no DB/no injection
    surface. `n` is now coerced inside its own try/except, closing this
    module's own documented uncaught-crash finding (same class as tool
    #215's fleet_metrics_read)."""
    from app.fleet.audit_log import get_audit_log

    agent_name = str(inp.get("agent_name", "")).strip()
    try:
        n = int(inp.get("n", 50))
    except (TypeError, ValueError) as exc:
        return f"[ERROR] audit_log_read: invalid numeric argument for n: {exc}"

    log = get_audit_log()
    entries = log.recent(max(n, 200))
    if agent_name:
        entries = [e for e in entries if e.agent_name == agent_name]
    entries = entries[-n:]
    if not entries:
        return f"(no audit entries{f' for agent {agent_name!r}' if agent_name else ''})"
    lines = [
        f"[{e.timestamp}] {e.agent_name} — {e.action_type} — outcome={e.outcome}"
        + (f" — {e.description}" if e.description else "")
        for e in entries
    ]
    return "\n".join(lines)

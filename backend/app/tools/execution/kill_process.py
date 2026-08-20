"""kill_process tool — tool_enhance.md productionization pass, tool
#49 (2026-08-20).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: kill_process
Old path: app/agents/tools.py (`_KILL_PROCESS_TOOL` schema dict).
New path: app/tools/execution/kill_process.py (this file) —
    `KILL_PROCESS_TOOL`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch and `make_chat_handlers`'s own `kill_process`,
    both real, reachable callers. Both already delegated to the one
    real shared implementation, `app.fleet.process_manager.kill()` —
    that function (not this schema) is where the real fix for this
    tool's turn landed; see its own docstring.
Affected modules: app/agents/tools.py, app/agents/chat_agent.py (schema
    re-export only — dispatch bodies already called the shared
    `process_manager.kill()`, unchanged by this move).
Affected registries: none — app/fleet/tool_manifest.py's
    "kill_process" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes to existing tests. New tests
    added: see tests/test_kill_process_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/kill_process.md.
---------------------------------------------------------------------------

Real, severe finding (the fix itself lives in
app/fleet/process_manager.py::kill(), the single shared implementation
both real call sites already used — see that function's own docstring
for the full account): `kill_process` could kill ANY process on the
host the server's OS user has permission to signal, not just processes
the calling session itself started via `run_background`. Proved live: a
completely unrelated `sleep 300` process, never tracked by the calling
session, was genuinely killed via `os.kill()`. This was a documented,
deliberate decision preserved during a prior de-duplication refactor
("no ownership gate existed before this unification, and none is added
here") — not an accidental oversight, so it was raised to the user
directly (AskUserQuestion) rather than fixed or left unilaterally. User
chose to close it.

This file only carries the schema (unchanged) — the actual behavior fix
is in the shared `process_manager.kill()` function both real
implementations already called, so no dispatch-body duplication was
needed here.
"""

from __future__ import annotations

KILL_PROCESS_TOOL: dict[str, object] = {
    "name": "kill_process",
    "description": "Kill a background process by PID. Use after run_background.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pid": {"type": "integer", "description": "Process ID to kill"},
            "signal": {
                "type": "string",
                "enum": ["TERM", "KILL", "INT"],
                "description": "Signal to send (default: TERM)",
            },
        },
        "required": ["pid"],
    },
}

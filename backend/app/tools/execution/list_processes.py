"""list_processes tool — tool_enhance.md productionization pass,
tool #165 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: list_processes
Old path: app/agents/tools.py (`_LIST_PROCESSES_TOOL` schema dict,
    `list_processes_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/execution/list_processes.py (this file) —
    `LIST_PROCESSES_TOOL`, `list_processes_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `list_processes` in `allowed_tools` (plus interactive chat, newly
    — see the one real finding below).
Affected modules: app/agents/tools.py (`list_processes_h` delegates
    to the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had).
Affected registries: none — app/fleet/tool_manifest.py's
    "list_processes" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_list_processes_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/list_processes.md.
---------------------------------------------------------------------------

`filter` reaches only a pure in-memory Python string `in` containment
check against `ps aux`'s own output lines — never a subprocess or
shell command of any kind. `ps aux` itself is a fixed literal argv
list run via list-args `subprocess.run()`, never `shell=True`. No
worktree-boundary-escape (no path field) or command-injection surface
exists here at all, checked directly.

One real, empirically-verified finding — advertised but never
dispatched on the interactive chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164.
`list_processes` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: list_processes"`.

Fixed via a shared `list_processes_handler()`; a new `chat_agent.py`
dispatch branch delegates to it, making `list_processes` genuinely
reachable from interactive chat for the first time.
"""

from __future__ import annotations

import subprocess
from typing import Any

LIST_PROCESSES_TOOL: dict[str, Any] = {
    "name": "list_processes",
    "description": "List running processes, optionally filtered by name. Returns PID, CPU%, MEM%, command.",
    "input_schema": {
        "type": "object",
        "properties": {
            "filter": {
                "type": "string",
                "description": "Filter by process name (optional)",
            }
        },
        "required": [],
    },
}


def list_processes_handler(inp: dict[str, Any]) -> str:
    """Core list_processes logic — the one real implementation,
    unchanged."""
    name_filter = str(inp.get("filter", ""))
    try:
        r = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=10)
        lines = r.stdout.strip().splitlines()
        if name_filter:
            lines = [
                ln
                for ln in lines
                if name_filter.lower() in ln.lower() or ln.startswith("USER")
            ]
        return "\n".join(lines[:50])
    except Exception as e:
        return f"[ERROR] list_processes: {e}"

"""list_open_ports tool — tool_enhance.md productionization pass,
tool #164 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: list_open_ports
Old path: app/agents/tools.py (`_LIST_OPEN_PORTS_TOOL` schema dict,
    `list_open_ports_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/execution/list_open_ports.py (this file) —
    `LIST_OPEN_PORTS_TOOL`, `list_open_ports_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `list_open_ports` in `allowed_tools` (plus interactive chat, newly
    — see the one real finding below).
Affected modules: app/agents/tools.py (`list_open_ports_h` delegates
    to the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had).
Affected registries: none — app/fleet/tool_manifest.py's
    "list_open_ports" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_list_open_ports_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/list_open_ports.md.
---------------------------------------------------------------------------

The input schema is empty (no properties at all) — no LLM-controlled
input reaches this tool, so the worktree-boundary-escape and
injection classes established repeatedly this initiative do not
apply. Both commands (`ss -tlnp`, falling back to `netstat -tlnp`) are
fixed literal argv lists run via list-args `subprocess.run()`, never
`shell=True` — no command-injection surface exists either, checked
directly.

One real, empirically-verified finding — advertised but never
dispatched on the interactive chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163.
`list_open_ports` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: list_open_ports"`.

Fixed via a shared `list_open_ports_handler()`; a new `chat_agent.py`
dispatch branch delegates to it, making `list_open_ports` genuinely
reachable from interactive chat for the first time.
"""

from __future__ import annotations

import subprocess
from typing import Any

LIST_OPEN_PORTS_TOOL: dict[str, Any] = {
    "name": "list_open_ports",
    "description": "List TCP ports currently listening on this machine.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


def list_open_ports_handler() -> str:
    """Core list_open_ports logic — the one real implementation,
    unchanged."""
    try:
        r = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            r = subprocess.run(
                ["netstat", "-tlnp"], capture_output=True, text=True, timeout=10
            )
        return r.stdout.strip() or "(no open ports found)"
    except Exception as e:
        return f"[ERROR] list_open_ports: {e}"

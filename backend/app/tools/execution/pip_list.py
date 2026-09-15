"""pip_list tool — tool_enhance.md productionization pass, tool #172
(2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: pip_list
Old path: app/agents/tools.py (`_PIP_LIST_TOOL` schema dict,
    `pip_list_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/execution/pip_list.py (this file) —
    `PIP_LIST_TOOL`, `pip_list_handler`.
Affected agents: per tool_inventory.json, agents declaring `pip_list`
    in `allowed_tools` (plus interactive chat, newly — see finding).
Affected modules: app/agents/tools.py (`pip_list_h` delegates to the
    shared handler), app/agents/chat_agent.py (gains a real dispatch
    branch it never had).
Affected registries: none — app/fleet/tool_manifest.py's "pip_list"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes. New tests added: see
    tests/test_pip_list_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/pip_list.md.
---------------------------------------------------------------------------

Audit: `filter` was checked for the same shell/CLI-flag-collision
class already found in sibling tools (e.g. #5/#32/#148/#149/#158) —
CONFIRMED NOT VULNERABLE. `filter` never reaches a subprocess or
shell at all: it is a pure in-memory Python substring check
(`name_filter.lower() in ln.lower()`) applied to the ALREADY-CAPTURED
stdout of a fixed, list-args `subprocess.run([sys.executable, "-m",
"pip", "list", "--format=columns"], ...)` call with no
LLM-controlled arguments whatsoever — same no-injection-surface shape
as sibling tool #165's `list_processes`. Proved live:
`pip_list({"filter": "-n"})` behaved as an ordinary (harmless)
substring filter, matching package names containing "-n" (e.g.
`charset-normalizer`) — no different from any other filter value, no
argv reinterpretation possible since `filter` never reaches argv.

One real finding: **advertised but never dispatched on the
interactive chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168/#169/#170/#171.**
`pip_list` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: pip_list"`.

Fixed via a new `chat_agent.py` dispatch branch delegating to this
shared `pip_list_handler()`. Behavior otherwise unchanged — no
security fix needed on the handler logic itself.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

PIP_LIST_TOOL: dict[str, Any] = {
    "name": "pip_list",
    "description": "List installed Python packages and their versions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "filter": {
                "type": "string",
                "description": "Filter packages by name prefix (optional)",
            },
        },
        "required": [],
    },
}


def pip_list_handler(inp: dict[str, Any]) -> str:
    """Core pip_list logic — the one real implementation, unchanged
    in behavior (no security fix needed; audited and confirmed safe —
    see module docstring)."""
    name_filter = str(inp.get("filter", ""))
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=columns"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        lines = r.stdout.strip().splitlines()
        if name_filter:
            lines = [
                ln
                for ln in lines
                if name_filter.lower() in ln.lower() or ln.startswith("Package")
            ]
        return "\n".join(lines)
    except Exception as e:
        return f"[ERROR] pip_list: {e}"

"""memory_read tool — tool_enhance.md productionization pass, tool
#167 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: memory_read
Old path: app/agents/tools.py (`_MEMORY_READ_TOOL` schema dict,
    `memory_read_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/agents/memory_read.py (this file) —
    `MEMORY_READ_TOOL`, `memory_read_handler`. Reuses
    `app.tools.agents.memory_write.memory_store_path()` (tool #51)
    directly, rather than re-deriving the per-repo memory-store path
    a third time — matching the established DRY precedent from tools
    #159's `json_validate`/`yaml_validate` shared schema helpers and
    #160/#161's shared `known_issues_path()`.
Affected agents: per tool_inventory.json, agents declaring
    `memory_read` in `allowed_tools` (plus interactive chat, newly —
    see the one real finding below).
Affected modules: app/agents/tools.py (`memory_read_h` delegates to
    the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had).
Affected registries: none — app/fleet/tool_manifest.py's
    "memory_read" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_memory_read_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/memory_read.md.
---------------------------------------------------------------------------

`key` reaches only a pure in-memory dict lookup (`store.get(key)`)
against a JSON store loaded from a FIXED, deterministic path (an md5
slug of `repo_path` alone, never influenced by `key`) — no
worktree-boundary-escape or injection surface exists here at all,
checked directly. The read remains unlocked, matching the ORIGINAL
implementation's own behavior exactly (only `memory_write`'s
read-modify-write sequence was ever proven to have a real,
empirically-reproduced lost-update race — tool #51's own finding; a
plain read was never shown to have a comparable issue, so no locking
was added here that wasn't already there).

One real, empirically-verified finding — advertised but never
dispatched on the interactive chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166.
`memory_read` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: memory_read"`.

Fixed via a shared `memory_read_handler()`; a new `chat_agent.py`
dispatch branch delegates to it, making `memory_read` genuinely
reachable from interactive chat for the first time.
"""

from __future__ import annotations

import json
from typing import Any

from app.tools.agents.memory_write import memory_store_path

MEMORY_READ_TOOL: dict[str, Any] = {
    "name": "memory_read",
    "description": "Read a value from the per-repo memory store by key.",
    "input_schema": {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Key to read from memory"}
        },
        "required": ["key"],
    },
}


def memory_read_handler(repo_path: str, inp: dict[str, Any]) -> str:
    """Core memory_read logic — the one real implementation, reused
    unchanged in behavior."""
    key = str(inp["key"])
    store_path = memory_store_path(repo_path)
    if not store_path.exists():
        return f"(key '{key}' not found in memory)"
    try:
        store: dict[str, Any] = dict(json.loads(store_path.read_text(encoding="utf-8")))
    except Exception:
        store = {}
    val = store.get(key)
    return val if val is not None else f"(key '{key}' not found in memory)"

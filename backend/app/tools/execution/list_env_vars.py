"""list_env_vars tool — tool_enhance.md productionization pass,
tool #163 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: list_env_vars
Old path: app/agents/tools.py (`_LIST_ENV_VARS_TOOL` schema dict,
    `list_env_vars_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/execution/list_env_vars.py (this file) —
    `LIST_ENV_VARS_TOOL`, `list_env_vars_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `list_env_vars` in `allowed_tools` (plus interactive chat, newly
    — see the one real finding below).
Affected modules: app/agents/tools.py (`list_env_vars_h` delegates
    to the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had).
Affected registries: none — app/fleet/tool_manifest.py's
    "list_env_vars" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_list_env_vars_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/list_env_vars.md.
---------------------------------------------------------------------------

The input schema is empty (no properties at all) — no LLM-controlled
input reaches this tool, so the worktree-boundary-escape and injection
classes established repeatedly this initiative do not apply. Checked
and CONFIRMED already safe on its own documented safety contract
("List all environment variable NAMES (not values)"): the
implementation genuinely returns only `os.environ.keys()`, never any
value. Proved live: a real environment variable was set to a
deliberately secret-shaped value before calling this tool — its NAME
appeared in the result, its VALUE never did.

One real, empirically-verified finding — advertised but never
dispatched on the interactive chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161.
`list_env_vars` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: list_env_vars"`.

Fixed via a shared `list_env_vars_handler()`; a new `chat_agent.py`
dispatch branch delegates to it, making `list_env_vars` genuinely
reachable from interactive chat for the first time.
"""

from __future__ import annotations

import os
from typing import Any

LIST_ENV_VARS_TOOL: dict[str, Any] = {
    "name": "list_env_vars",
    "description": "List all environment variable NAMES (not values) currently set. Use read_env_var to read a specific value.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


def list_env_vars_handler() -> str:
    """Core list_env_vars logic — the one real implementation,
    unchanged. Returns NAMES only, never values."""
    names = sorted(os.environ.keys())
    return "\n".join(names)

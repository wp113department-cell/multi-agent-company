"""read_env_var tool — tool_enhance.md productionization pass, tool
#173 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: read_env_var
Old path: app/agents/tools.py (`_READ_ENV_VAR_TOOL` schema dict,
    `read_env_var_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/execution/read_env_var.py (this file) —
    `READ_ENV_VAR_TOOL`, `read_env_var_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `read_env_var` in `allowed_tools` (plus interactive chat, newly —
    see finding).
Affected modules: app/agents/tools.py (`read_env_var_h` delegates to
    the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had).
Affected registries: none — app/fleet/tool_manifest.py's
    "read_env_var" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_read_env_var_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/read_env_var.md.
---------------------------------------------------------------------------

Audit: unlike sibling tool #163's `list_env_vars` (names only, never
values), this tool's whole purpose is returning a VALUE by name — so
it was checked specifically for real secret disclosure. CONFIRMED
ALREADY SAFE: the existing implementation already routes every value
through `app.agents.tool_security._mask_secret_value()` before
returning it, which redacts (to a short prefix + `***REDACTED`) any
value whose variable NAME looks secret-shaped (KEY/SECRET/TOKEN/
PASSWORD/PWD/CREDENTIAL/AUTH/PRIVATE) or whose VALUE itself matches a
known secret shape (`sk-...`, `AKIA...`, GitHub/Slack token prefixes)
or a generic long opaque token. Proved live: a real env var named
`TD_READ_ENV_VAR_SECRET` set to a `sk-`-prefixed value was genuinely
redacted (`sk-sup***REDACTED`), while an ordinary plain-text value and
an unset name both returned correctly (`...=[NOT SET]`) — no change
needed to this logic.

One real finding: **advertised but never dispatched on the
interactive chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168/#169/#170/#171/#172.**
`read_env_var` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: read_env_var"`.

Fixed via a new `chat_agent.py` dispatch branch delegating to this
shared `read_env_var_handler()`. Behavior otherwise unchanged — no
security fix needed on the handler logic itself.
"""

from __future__ import annotations

import os
from typing import Any

from app.agents.tool_security import _mask_secret_value

READ_ENV_VAR_TOOL: dict[str, Any] = {
    "name": "read_env_var",
    "description": "Read the value of a specific environment variable from the running process. Returns [NOT SET] if absent.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Environment variable name"}
        },
        "required": ["name"],
    },
}


def read_env_var_handler(inp: dict[str, Any]) -> str:
    """Core read_env_var logic — the one real implementation,
    unchanged in behavior (no security fix needed; already routes
    every value through `_mask_secret_value()` — see module
    docstring)."""
    name = str(inp["name"])
    val = os.environ.get(name)
    if val is None:
        return f"{name}=[NOT SET]"
    return f"{name}={_mask_secret_value(name, val)}"

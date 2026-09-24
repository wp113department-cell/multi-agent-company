"""create_directory tool — tool_enhance.md productionization pass,
tool #131 (2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: create_directory
Old path: app/agents/tools.py (`_CREATE_DIRECTORY_TOOL` schema dict,
    `create_directory_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/create_directory.py (this file) —
    `CREATE_DIRECTORY_TOOL`, `create_directory_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `create_directory` in `allowed_tools` (plus interactive chat,
    newly — see finding below).
Affected modules: app/agents/tools.py (`create_directory_h` delegates
    to the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding below).
Affected registries: none — app/fleet/tool_manifest.py's
    "create_directory" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_create_directory_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/create_directory.md.
---------------------------------------------------------------------------

Worktree-boundary validation was ALREADY correct
(`_is_protected_path(path, repo_path)`, which — given `worktree_path`
— already performs full worktree-containment checking, not just the
filename denylist) — confirmed by direct inspection and re-verified
live below, not assumed.

One real finding — advertised but never dispatched, on the interactive
chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130. `create_directory`
is in `CHAT_TOOLS` and registered in `make_chat_handlers()`'s handlers
dict, but `app/agents/chat_agent.py`'s `_execute_tool()` has NO
dispatch branch for it — every real interactive-chat call fell through
to `"[ERROR] Unknown tool: create_directory"`.

Fixed via a new `chat_agent.py` dispatch branch delegating to the
shared `create_directory_handler()`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.tool_security import _is_protected_path

CREATE_DIRECTORY_TOOL: dict[str, Any] = {
    "name": "create_directory",
    "description": "Create a directory (and any missing parents). Equivalent to mkdir -p.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to create (relative to repo root)",
            },
        },
        "required": ["path"],
    },
}


def create_directory_handler(
    root: Path, worktree_path: str, inp: dict[str, Any]
) -> str:
    """Core create_directory logic — the one real implementation,
    reused unchanged in behavior (worktree validation was already
    correct)."""
    path = str(inp["path"])
    if _is_protected_path(path, worktree_path):
        return f"[POLICY DENIED] Cannot create directory in protected path: {path}"
    target = root / path
    try:
        target.mkdir(parents=True, exist_ok=True)
        return f"Created directory: {path}"
    except Exception as e:
        return f"[ERROR] create_directory: {e}"

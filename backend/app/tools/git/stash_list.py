"""git_stash_list tool — tool_enhance.md productionization pass,
tool #151 (2026-09-14).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_stash_list
Old path: app/agents/tools.py (`_GIT_STASH_LIST_TOOL` schema dict,
    `git_stash_list_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/git/stash_list.py (this file) —
    `GIT_STASH_LIST_TOOL`, `git_stash_list_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `git_stash_list` in `allowed_tools` (plus interactive chat,
    newly — see the one real finding below).
Affected modules: app/agents/tools.py (`git_stash_list_h` delegates
    to the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had).
Affected registries: none — app/fleet/tool_manifest.py's
    "git_stash_list" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_git_stash_list_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_stash_list.md.
---------------------------------------------------------------------------

The input schema is empty (no properties at all), so there is no
LLM-controlled input reaching this tool — the worktree-boundary-escape
and shell-injection classes established repeatedly this initiative do
not apply here, checked directly.

One real, empirically-verified finding — advertised but never
dispatched on the interactive chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150.
`git_stash_list` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
git repo with a real stash on it, called through the real
`chat_agent.py` dispatch, returned `"[ERROR] Unknown tool:
git_stash_list"` instead of listing the stash.

Fixed via a shared `git_stash_list_handler()`; a new `chat_agent.py`
dispatch branch delegates to it, making `git_stash_list` genuinely
reachable from interactive chat for the first time.
"""

from __future__ import annotations

import subprocess
from typing import Any

GIT_STASH_LIST_TOOL: dict[str, Any] = {
    "name": "git_stash_list",
    "description": "List all git stashes with their index and description.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


def git_stash_list_handler(repo_path: str) -> str:
    """Core git_stash_list logic — the one real implementation,
    unchanged."""
    try:
        r = subprocess.run(
            ["git", "stash", "list"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=15,
        )
        return r.stdout.strip() or "(no stashes)"
    except Exception as e:
        return f"[ERROR] git_stash_list: {e}"

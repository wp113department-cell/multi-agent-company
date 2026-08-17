"""git_tag tool — tool_enhance.md productionization pass, tool #22
(2026-08-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_tag
Old path: app/agents/tools.py (`_GIT_TAG_TOOL` schema dict and the
    `git_tag_h` handler inside `make_chat_handlers()` — no chat_agent.py
    dispatch existed at all before this pass)
New path: app/tools/git/tag.py (this file) — `GIT_TAG_TOOL`,
    `git_tag_handler`.
Affected agents: 2 per tool_inventory.json. `git_tag` is advertised in
    `CHAT_TOOLS` (chat_agent's own tool list), so `chat_agent` is one of
    them — but its real dispatch never had a branch for it (see below);
    every real call from the interactive chat agent fell through to the
    generic "[ERROR] Unknown tool: git_tag" response.
Affected modules: app/agents/tools.py (compatibility re-export, handler
    delegates to the shared function), app/agents/chat_agent.py (gains a
    real dispatch branch for the first time).
Affected registries: none — app/fleet/tool_manifest.py's "git_tag"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["git_tag"](...)`. New tests added: see
    tests/test_git_tag_hardening.py, including new coverage of
    chat_agent.py's real dispatch (didn't exist before — there was
    nothing to test).

Runtime verification: PASS — see backend/docs/tool_productionization/git_tag.md.
---------------------------------------------------------------------------

Real finding: `git_tag` is advertised to the interactive chat LLM via
`CHAT_TOOLS`, but `chat_agent.py`'s `_execute_tool()` had no `if
tool_name == "git_tag":` branch at all — the same "advertised but never
dispatched" bug class already found and fixed for `npm_install`/
`pip_install` (tool #4) and `github_create_pr` (tool #6). Verified
directly: a real call returned the generic `"[ERROR] Unknown tool:
git_tag"` fallback.

The existing `make_chat_handlers` implementation itself was already safe
— list-args `subprocess.run`, no `shell=True`, so no injection surface
regardless of `name`/`message` content. Also checked directly (not
assumed) whether a flag-shaped tag name (e.g. `name="--force"`) could
trigger unexpected behavior, mirroring tool #5's real `git_reset` flag-
collision bug: verified against a real repo that git itself refuses a
flag-shaped tag name with a clean usage error (exit 129) — no silent
dangerous behavior, unlike `git_reset --soft --hard`'s real bug. No fix
needed there; the existing `[ERROR] {stderr}` surfacing already handles
this case correctly.
"""

from __future__ import annotations

import subprocess
from typing import Any

GIT_TAG_TOOL: dict[str, Any] = {
    "name": "git_tag",
    "description": "Create, list, or delete git tags. action: 'list' (default), 'create', 'delete'.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create", "delete"],
                "description": "Tag operation",
            },
            "name": {
                "type": "string",
                "description": "Tag name (required for create/delete)",
            },
            "message": {
                "type": "string",
                "description": "Annotated tag message (optional, create only)",
            },
        },
        "required": [],
    },
}


def git_tag_handler(repo_path: str, inp: dict[str, Any]) -> str:
    action = str(inp.get("action", "list"))
    name = str(inp.get("name", ""))
    msg = str(inp.get("message", ""))
    try:
        if action == "list":
            r = subprocess.run(
                ["git", "tag", "--sort=-creatordate"],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=15,
            )
            return r.stdout.strip() or "(no tags)"
        if action == "create":
            cmd = ["git", "tag", "-a", name, "-m", msg] if msg else ["git", "tag", name]
            r = subprocess.run(
                cmd, capture_output=True, text=True, cwd=repo_path, timeout=15
            )
            return (
                r.stdout.strip() or f"Tag '{name}' created"
                if r.returncode == 0
                else f"[ERROR] {r.stderr.strip()}"
            )
        if action == "delete":
            r = subprocess.run(
                ["git", "tag", "-d", name],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=15,
            )
            return (
                r.stdout.strip() or f"Tag '{name}' deleted"
                if r.returncode == 0
                else f"[ERROR] {r.stderr.strip()}"
            )
        return "[ERROR] Unknown action"
    except Exception as e:
        return f"[ERROR] git_tag: {e}"

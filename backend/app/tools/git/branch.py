"""git_branch tool — tool_enhance.md productionization pass, tool
#148 (2026-09-14).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_branch
Old path: app/agents/tools.py (`_GIT_BRANCH_TOOL` schema dict,
    `git_branch` inside `make_chat_handlers()`) + app/agents/
    chat_agent.py (its own separate, near-identical dispatch).
New path: app/tools/git/branch.py (this file) — `GIT_BRANCH_TOOL`,
    `git_branch_handler`. BOTH real call sites now delegate to this
    one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `git_branch` in `allowed_tools` (plus interactive chat, which
    already had a real, correctly-matching dispatch — unlike most
    other tools this initiative, this one was never missing its
    dispatch branch).
Affected modules: app/agents/tools.py (its own closure delegates to
    the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's
    "git_branch" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_git_branch_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_branch.md.
---------------------------------------------------------------------------

One real, empirically-verified finding — a flag-collision bug, the
same class already documented and fixed for sibling tools #5's
`git_reset` and #32's `create_branch`
(app/tools/git/create_branch.py's `validate_create_branch_inputs`).

Both real implementations built `["git", "branch", name]` for the
`create` action with zero validation that `name` isn't itself a
flag-shaped string. Proved live against a real repo: `git_branch({
"action": "create", "name": "--list"})` — intended to create a branch
literally named `--list` — silently ran `git branch --list` instead,
returning the real branch listing with **no error indication at
all**, so the caller has no way to tell "the branch was created" from
"a completely different git-branch subcommand ran instead" (the
handler's own fallback message, `f"Branch '{name}' created"`, is only
used when stdout+stderr are BOTH empty — and a real listing is never
empty, so that fallback never even triggers; the misleading listing
output is returned as-is). Confirmed with a second flag (`name="-a"`)
— same silent-subcommand-switch result.

The `delete` action (`["git", "branch", "-d", name]`) was also tested
with flag-shaped names (`"-D"`, `"--all"`) — git always errored with
`fatal: branch name required` in both cases, since the flag consumes
the position `-d` needs a real branch name in, so `delete` was not
found destructively exploitable. It is still defensively validated
the same way, for defense in depth and consistency with every sibling
tool's fix.

Fixed via a shared `git_branch_handler()`: `name` is rejected outright
(a clear `[ERROR]`, not a silently-different git subcommand) whenever
it starts with `-`, for both `create` and `delete`.
"""

from __future__ import annotations

import subprocess
from typing import Any

GIT_BRANCH_TOOL: dict[str, Any] = {
    "name": "git_branch",
    "description": "List all branches, or create a new branch. To switch branches use git_checkout.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create", "delete"],
                "description": "Action to perform (default: list)",
            },
            "name": {
                "type": "string",
                "description": "Branch name (required for create/delete)",
            },
        },
        "required": [],
    },
}


def _validate_branch_name(name: str) -> str | None:
    """Returns an [ERROR] string if `name` is flag-shaped, else None.
    Rejecting outright (rather than passing it through to git) closes
    the real, live-proved silent-subcommand-switch bug on the `create`
    action — matching the fix already established for sibling tools
    #5's git_reset and #32's create_branch."""
    if name.startswith("-"):
        return (
            f"[ERROR] Invalid branch name {name!r} — branch names may not "
            "start with '-' (this would be interpreted as an additional "
            "git flag, not a name — e.g. name='--list' silently turns "
            "branch creation into a plain branch listing, with no error)."
        )
    return None


def git_branch_handler(repo_path: str, inp: dict[str, Any]) -> str:
    """Core git_branch logic shared by both real call sites."""
    action = str(inp.get("action", "list"))
    name = str(inp.get("name", ""))
    try:
        if action == "list":
            r = subprocess.run(
                ["git", "branch", "-a"],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )
            return r.stdout or "(no branches)"
        elif action == "create":
            if not name:
                return "[ERROR] name required for create"
            name_error = _validate_branch_name(name)
            if name_error:
                return name_error
            r = subprocess.run(
                ["git", "branch", name],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )
            return r.stdout + r.stderr or f"Branch '{name}' created"
        elif action == "delete":
            if not name:
                return "[ERROR] name required for delete"
            name_error = _validate_branch_name(name)
            if name_error:
                return name_error
            r = subprocess.run(
                ["git", "branch", "-d", name],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )
            return r.stdout + r.stderr or f"Branch '{name}' deleted"
        return f"[ERROR] Unknown action: {action}"
    except Exception as e:
        return f"[ERROR] {e}"

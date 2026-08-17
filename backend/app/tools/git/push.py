"""git_push tool — tool_enhance.md productionization pass, tool #4
(2026-08-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_push
Old path: app/agents/tools.py (`_GIT_PUSH_TOOL` schema dict and the
    `git_push` handler inside `make_chat_handlers()`)
New path: app/tools/git/push.py (this file) — `GIT_PUSH_TOOL`,
    `git_push_handler`.

Affected agents: only chat_agent's own AGENT_CONTRACT lists git_push as
    an allowed_tool (confirmed via tool_inventory.json's AST scan). The
    interactive chat agent has its OWN separate, real, working git_push
    dispatch in app/agents/chat_agent.py (a genuine `self._confirm()`
    interrupt()-based gate — see that file for the tool #4 fixes made to
    it: distinguishing force-push confirmations, protected-branch
    handling). It does not call `make_chat_handlers()` at all, so this
    module's `git_push_handler` is not that real implementation — see
    "Real finding" below for what this handler actually is now.
Affected modules: app/agents/tools.py (compatibility re-export).
Affected registries: none — app/fleet/tool_manifest.py's "git_push"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes beyond what tool #4's broader
    dead-code cleanup already touched (see
    docs/tool_productionization/git_push.md) — every real test accesses
    this tool via `handlers["git_push"](...)`.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_push.md.
---------------------------------------------------------------------------

Real finding (not this tool specifically, but discovered while auditing
it — full detail in git_push.md): `session` is never non-None for any
real caller of `make_chat_handlers()` anywhere in the repo. This
handler — like 7 siblings in the same factory (bash-dangerous,
docker_compose, undo_changes, run_migration, seed_database, npm_install,
pip_install) — previously attempted a `session.request_confirmation()`
flow that could never execute in production. Simplified to a single,
honest, unconditional refusal instead of dead async plumbing.
"""

from __future__ import annotations

from typing import Any

GIT_PUSH_TOOL: dict[str, Any] = {
    "name": "git_push",
    "description": (
        "Push commits to the remote repository. "
        "ALWAYS requires explicit user confirmation before executing. "
        "Specify the branch; defaults to current branch."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "description": "Branch to push (defaults to current branch)",
            },
            "remote": {
                "type": "string",
                "description": "Remote name (default: origin)",
            },
            "force": {
                "type": "boolean",
                "description": "Force push (default: false — requires extra confirmation)",
            },
        },
        "required": [],
    },
}


def git_push_handler(inp: dict[str, Any]) -> str:
    """Always refuses — see this module's docstring. Real, working
    git_push execution for a real human happens in
    app/agents/chat_agent.py's own dispatch, which has a genuine
    self._confirm() gate this handler tier cannot replicate (no per-call
    approval channel exists for one-shot batch agents)."""
    return (
        "[BLOCKED] git_push always requires user confirmation. No "
        "interactive confirmation channel is available in this "
        "execution context."
    )

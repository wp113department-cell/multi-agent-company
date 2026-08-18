"""create_branch tool — tool_enhance.md productionization pass, tool #32
(2026-08-18).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: create_branch
Old path: app/agents/tools.py (`_CREATE_BRANCH_TOOL` schema dict and the
    `create_branch` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body)
New path: app/tools/git/create_branch.py (this file) —
    `CREATE_BRANCH_TOOL`, `validate_create_branch_inputs`.
Affected agents: 1 per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, the only real, reachable caller.
    `make_chat_handlers`'s own copy is also reachable by any other agent
    declaring this tool.
Affected modules: app/agents/tools.py (schema re-export;
    `create_branch` now calls the shared validator before building its
    command), app/agents/chat_agent.py (its real dispatch now calls the
    shared validator too).
Affected registries: none — app/fleet/tool_manifest.py's "create_branch"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["create_branch"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_create_branch_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/create_branch.md.
---------------------------------------------------------------------------

Real, empirically-verified finding (severe — same bug class as tool #5's
`git_reset` flag-collision bug): both implementations built
`["git", "branch", name, from_branch]` with zero validation that `name`
isn't itself a flag-shaped string. Proved directly against a real repo,
through the real `chat_agent.py` dispatch: `name="-D"` combined with
`from_branch="important-feature-branch"` (a real, existing branch)
produced `git branch -D important-feature-branch` — **deleting the real
branch** — even though `create_branch` is documented and used as a
purely additive, non-destructive operation with no confirmation gate
anywhere. The subsequent checkout step (`do_checkout` defaults to
`True`) then failed for an unrelated reason (`-D` isn't a valid
`git checkout` flag either), producing a confusing `[ERROR]` message
that gave no indication the branch deletion had already happened for
real in the first step.
"""

from __future__ import annotations

CREATE_BRANCH_TOOL = {
    "name": "create_branch",
    "description": "Create a new git branch and optionally switch to it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Branch name (e.g. 'feat/add-login')",
            },
            "checkout": {
                "type": "boolean",
                "description": "Switch to the new branch after creating it (default: true)",
            },
            "from_branch": {
                "type": "string",
                "description": "Base branch (default: current HEAD)",
            },
        },
        "required": ["name"],
    },
}


def validate_create_branch_inputs(name: str, from_branch: str) -> str | None:
    """Returns an [ERROR] string if `name`/`from_branch` are unsafe, else
    None. Shared by both real call sites so the fix for the real
    branch-deletion-via-flag-shaped-name exploit lives in exactly one
    place."""
    if not name:
        return "[ERROR] name must be non-empty"
    if name.startswith("-"):
        return (
            f"[ERROR] Invalid branch name {name!r} — branch names may not "
            "start with '-' (this would be interpreted as an additional "
            "git flag, not a name — e.g. name='-D' turns branch creation "
            "into branch deletion)."
        )
    if from_branch.startswith("-"):
        return (
            f"[ERROR] Invalid from_branch {from_branch!r} — refs may not "
            "start with '-' (this would be interpreted as an additional "
            "git flag, not a ref)."
        )
    return None

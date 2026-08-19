"""git_stash tool — tool_enhance.md productionization pass, tool
#42 (2026-08-19).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_stash
Old path: app/agents/tools.py (`_GIT_STASH_TOOL` schema dict and the
    `git_stash` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body)
New path: app/tools/git/stash.py (this file) — `GIT_STASH_TOOL`,
    `validate_git_stash_action`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, the only real, reachable caller.
    `make_chat_handlers`'s own copy is also reachable by any other agent
    declaring this tool.
Affected modules: app/agents/tools.py (schema re-export; `git_stash`
    handler now calls the shared validator and returns a clear error
    for an out-of-enum action, instead of silently falling through to
    a plain `git stash` push), app/agents/chat_agent.py (its real
    dispatch now calls the shared validator before building its
    command, instead of trusting `action` unchecked).
Affected registries: none — app/fleet/tool_manifest.py's "git_stash"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["git_stash"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_git_stash_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_stash.md.
---------------------------------------------------------------------------

Real finding (severe — the schema's own `enum` constraint is purely
advisory to the model and was never enforced at runtime by either
implementation): `_GIT_STASH_TOOL`'s schema documents `action` as
`enum: ["push", "pop", "list", "drop"]`, but `chat_agent.py`'s real
dispatch built its command as:

    if action == "push" and msg:
        return _git(["stash", "push", "-m", msg], repo)
    return _git(["stash", action], repo)

— any `action` value other than a message-bearing "push" was passed
straight through as a literal `git stash <action>` subcommand, with
**zero validation that it's one of the 4 documented values**. Proved
live against a real repo with two real, distinct stashed changes:
`action="clear"` (never in the schema's enum) ran `git stash clear`,
**permanently and irrecoverably deleting every stash entry**, with zero
confirmation and zero warning — `git stash list` was empty afterward.
This is the same underlying bug class as tools #5/#32/#35/#36/#38/#39/
#40's flag-collision findings (an out-of-schema value reaching a
destructive git subcommand unchecked), just via an enum bypass rather
than a leading-dash flag.

`make_chat_handlers`'s own `git_stash` was already safe by construction
— an explicit `if/elif` chain only recognizes exactly the 4 documented
actions, and anything else silently falls through to a bare
`git stash` (equivalent to a no-message push) rather than reaching an
arbitrary subcommand. Not exploitable, but also not ideal: an invalid
`action` is silently reinterpreted as "push" instead of surfacing a
clear error to the caller.

Fixed via a shared `validate_git_stash_action()` chokepoint (an
explicit allowlist, mirroring the schema's own enum) used by both real
call sites — `chat_agent.py` now rejects an out-of-enum `action` before
ever building the git command, and `tools.py`'s handler now returns a
clear `[ERROR]` instead of silently substituting `push`.
"""

from __future__ import annotations

_VALID_GIT_STASH_ACTIONS = frozenset({"push", "pop", "list", "drop"})

GIT_STASH_TOOL = {
    "name": "git_stash",
    "description": "Stash current changes or pop the most recent stash. Useful for temporarily saving work.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["push", "pop", "list", "drop"],
                "description": "Stash action (default: push)",
            },
            "message": {
                "type": "string",
                "description": "Optional label for the stash (push only)",
            },
        },
        "required": [],
    },
}


def validate_git_stash_action(action: str) -> str | None:
    """Returns an [ERROR] string if `action` isn't one of the schema's
    documented enum values, else None. Shared by both real call sites —
    the schema's `enum` alone is advisory to the model and was never
    enforced at runtime before this fix."""
    if action not in _VALID_GIT_STASH_ACTIONS:
        return (
            f"[ERROR] Invalid action {action!r} — must be one of "
            f"{sorted(_VALID_GIT_STASH_ACTIONS)}."
        )
    return None

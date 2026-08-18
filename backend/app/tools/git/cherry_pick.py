"""git_cherry_pick tool — tool_enhance.md productionization pass, tool
#36 (2026-08-18).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_cherry_pick
Old path: app/agents/tools.py (`_GIT_CHERRY_PICK_TOOL` schema dict and
    the `git_cherry_pick_h` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body)
New path: app/tools/git/cherry_pick.py (this file) —
    `GIT_CHERRY_PICK_TOOL`, `validate_git_cherry_pick_inputs`.
Affected agents: 1 per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, the only real, reachable caller.
    `make_chat_handlers`'s own copy is also reachable by any other agent
    declaring this tool.
Affected modules: app/agents/tools.py (schema re-export;
    `git_cherry_pick_h` now calls the shared validator before building
    its command), app/agents/chat_agent.py (its real dispatch now calls
    the shared validator too).
Affected registries: none — app/fleet/tool_manifest.py's
    "git_cherry_pick" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["git_cherry_pick"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_git_cherry_pick_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_cherry_pick.md.
---------------------------------------------------------------------------

Real finding (moderate — same flag-collision shape as tools #5/#32/#35,
but narrower blast radius): both implementations built
`["git", "cherry-pick", ..., commit_hash]` with zero validation that
`commit_hash` isn't itself a flag-shaped string. `commit_hash` is
documented purely as "SHA or ref of the commit to cherry-pick" — no
legitimate use case for it to start with `-`.

Unlike `git_checkout`'s `-f` (tool #35, a real, immediate,
single-call data-loss exploit) or `create_branch`'s `-D` (tool #32, a
real, immediate branch deletion), empirically testing every dangerous-
looking `git cherry-pick` flag (`--abort`, `--quit`, `-n`) against a
real repo with no cherry-pick already in progress produced only clean,
fail-closed errors — no single-call destructive exploit was
reproducible. `--abort`/`--quit`/`--skip` DO have real side effects
(discarding in-progress conflict-resolution state) if a cherry-pick
sequence happens to already be active, a narrower, two-step scenario.
Fixed anyway, for consistency with the same validated pattern already
applied to every sibling git ref/target field in this initiative
(tools #5/#32/#35) and because the schema's own documented contract
already rules out flag-shaped values.
"""

from __future__ import annotations

GIT_CHERRY_PICK_TOOL = {
    "name": "git_cherry_pick",
    "description": "Apply a specific commit from another branch onto the current branch.",
    "input_schema": {
        "type": "object",
        "properties": {
            "commit_hash": {
                "type": "string",
                "description": "SHA or ref of the commit to cherry-pick",
            },
            "no_commit": {
                "type": "boolean",
                "description": "Stage changes without committing (default: false)",
            },
        },
        "required": ["commit_hash"],
    },
}


def validate_git_cherry_pick_inputs(commit_hash: str) -> str | None:
    """Returns an [ERROR] string if `commit_hash` is unsafe, else None.
    Shared by both real call sites."""
    if not commit_hash:
        return "[ERROR] commit_hash must be non-empty"
    if commit_hash.startswith("-"):
        return (
            f"[ERROR] Invalid commit_hash {commit_hash!r} — commit "
            "hashes/refs may not start with '-' (this would be "
            "interpreted as an additional git flag, not a commit, e.g. "
            "'--abort'/'--quit'/'--skip' can disrupt an in-progress "
            "cherry-pick sequence)."
        )
    return None

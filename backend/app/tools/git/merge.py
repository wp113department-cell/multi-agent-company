"""git_merge tool — tool_enhance.md productionization pass, tool
#38 (2026-08-18).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_merge
Old path: app/agents/tools.py (`_GIT_MERGE_TOOL` schema dict and the
    `git_merge` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body)
New path: app/tools/git/merge.py (this file) — `GIT_MERGE_TOOL`,
    `validate_git_merge_inputs`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, the only real, reachable caller.
    `make_chat_handlers`'s own copy is also reachable by any other agent
    declaring this tool.
Affected modules: app/agents/tools.py (schema re-export; `git_merge`
    handler now calls the shared validator before building its
    command), app/agents/chat_agent.py (its real dispatch now calls the
    shared validator too).
Affected registries: none — app/fleet/tool_manifest.py's "git_merge"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["git_merge"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_git_merge_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_merge.md.
---------------------------------------------------------------------------

Real finding (moderate-to-severe — same flag-collision shape as tools
#5/#32/#35/#36, but here notably more plausible in practice than #36's):
both implementations built `["git", "merge", ..., branch]` with zero
validation that `branch` isn't itself a flag-shaped string. `branch` is
documented purely as "Branch name to merge into current branch" — no
legitimate use case for it to start with `-`.

Empirically proven live: `git merge --abort`, run immediately after a
real merge produced a real CONFLICT state (`UU f.txt`, mid-merge), fully
and silently discarded the in-progress conflict-resolution state and
returned the repo to its pre-merge tree with exit 0 — no confirmation,
no warning. Unlike tool #36's cherry_pick (where a second, independent
call would need to be in flight for `--abort` to matter), THIS tool's
own documented workflow explicitly expects a CONFLICT result to be
followed by more tool calls before the merge is finished — making a
stray/adversarial `branch="--abort"` a highly plausible real
interaction, not a hypothetical edge case.

Fixed via a shared `validate_git_merge_inputs()` chokepoint (rejects an
empty or flag-shaped `branch`), mirroring the same validated-ref pattern
already applied to every sibling git ref/target field in this
initiative (tools #5/#32/#35/#36).
"""

from __future__ import annotations

GIT_MERGE_TOOL = {
    "name": "git_merge",
    "description": "Merge a branch into the current branch.",
    "input_schema": {
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "description": "Branch name to merge into current branch",
            },
            "no_ff": {
                "type": "boolean",
                "description": "Create a merge commit even for fast-forwards (default: false)",
            },
            "squash": {
                "type": "boolean",
                "description": "Squash all commits into one (default: false)",
            },
            "message": {
                "type": "string",
                "description": "Commit message for the merge (optional)",
            },
        },
        "required": ["branch"],
    },
}


def validate_git_merge_inputs(branch: str) -> str | None:
    """Returns an [ERROR] string if `branch` is unsafe, else None.
    Shared by both real call sites."""
    if not branch:
        return "[ERROR] branch must be non-empty"
    if branch.startswith("-"):
        return (
            f"[ERROR] Invalid branch {branch!r} — branch names may not "
            "start with '-' (this would be interpreted as an additional "
            "git flag, not a branch, e.g. '--abort'/'--quit' can silently "
            "discard an in-progress conflict resolution)."
        )
    return None

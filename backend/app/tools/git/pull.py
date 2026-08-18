"""git_pull tool — tool_enhance.md productionization pass, tool
#39 (2026-08-18).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_pull
Old path: app/agents/tools.py (`_GIT_PULL_TOOL` schema dict and the
    `git_pull` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body)
New path: app/tools/git/pull.py (this file) — `GIT_PULL_TOOL`,
    `validate_git_pull_inputs`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, the only real, reachable caller.
    `make_chat_handlers`'s own copy is also reachable by any other agent
    declaring this tool.
Affected modules: app/agents/tools.py (schema re-export; `git_pull`
    handler now calls the shared validator before building its
    command), app/agents/chat_agent.py (its real dispatch now calls the
    shared validator too).
Affected registries: none — app/fleet/tool_manifest.py's "git_pull"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["git_pull"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_git_pull_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_pull.md.
---------------------------------------------------------------------------

Real finding (moderate — same flag-collision shape as tools
#5/#32/#35/#36/#38, but lower severity: git's own pull/merge working-
tree safety already refuses to overwrite uncommitted local changes
regardless of these flags): both implementations built ["git", "pull",
..., remote, branch] with zero validation that `remote`/`branch` aren't
themselves flag-shaped. Neither field has a legitimate use case for
starting with `-` — `remote` is documented as "Remote name (default:
origin)", `branch` as "Branch to pull (default: current branch)".

Empirically proven live (against a real local bare-remote clone): both
`remote="--force"` (with no actual remote given) and `branch="--force"`
(after a real remote) were silently accepted by git as a real
`--force`/`-f` flag rather than a literal name — `git pull --force` /
`git pull origin --force` both ran successfully with exit 0. This does
NOT reproduce a checkout/merge/cherry-pick-style data-loss exploit
(`--force` on `pull` only affects non-fast-forward ref/tag updates
during the underlying fetch, not the merge/rebase step's working-tree
safety, which already refuses to clobber uncommitted local changes
regardless of this flag). The real effect is the LLM's intended
remote/branch silently being dropped and replaced with flag behavior —
a correctness/silent-wrong-action bug, not a data-loss one.

Fixed anyway, for consistency with the same validated-ref pattern
already applied to every sibling git ref/target field in this
initiative (tools #5/#32/#35/#36/#38) and because neither field's own
documented contract allows a flag-shaped value.
"""

from __future__ import annotations

GIT_PULL_TOOL = {
    "name": "git_pull",
    "description": "Pull latest changes from remote. Optionally specify remote and branch.",
    "input_schema": {
        "type": "object",
        "properties": {
            "remote": {
                "type": "string",
                "description": "Remote name (default: origin)",
            },
            "branch": {
                "type": "string",
                "description": "Branch to pull (default: current branch)",
            },
            "rebase": {
                "type": "boolean",
                "description": "Use --rebase instead of merge (default: false)",
            },
        },
        "required": [],
    },
}


def validate_git_pull_inputs(remote: str, branch: str) -> str | None:
    """Returns an [ERROR] string if `remote`/`branch` are unsafe, else
    None. Shared by both real call sites."""
    if remote.startswith("-"):
        return (
            f"[ERROR] Invalid remote {remote!r} — remote names may not "
            "start with '-' (this would be interpreted as an additional "
            "git flag, not a remote name)."
        )
    if branch.startswith("-"):
        return (
            f"[ERROR] Invalid branch {branch!r} — branch names may not "
            "start with '-' (this would be interpreted as an additional "
            "git flag, not a branch name)."
        )
    return None

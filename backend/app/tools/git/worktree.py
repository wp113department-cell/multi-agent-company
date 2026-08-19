"""git_worktree tool — tool_enhance.md productionization pass, tool
#43 (2026-08-19).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_worktree
Old path: app/agents/tools.py (`_GIT_WORKTREE_TOOL` schema dict and the
    `git_worktree` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body)
New path: app/tools/git/worktree.py (this file) — `GIT_WORKTREE_TOOL`,
    `validate_git_worktree_inputs`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, the only real, reachable caller.
    `make_chat_handlers`'s own copy is NOT a real reachable caller for
    the `add` action — grepped the whole repo for "git_worktree" outside
    these two files and app/fleet/tool_manifest.py's metadata-only
    entry: it appears in zero agent's `allowed_tools`, same situation
    `undo_changes`/`git_restore` were in before their own fixes.
Affected modules: app/agents/tools.py (schema re-export; `git_worktree`
    handler now validates inputs and blocks the unconfirmable `add`
    action, matching the established `undo_changes_h`/`git_restore`
    pattern), app/agents/chat_agent.py (its real dispatch now validates
    inputs and adds a real confirmation gate before `add`).
Affected registries: none — app/fleet/tool_manifest.py's "git_worktree"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["git_worktree"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_git_worktree_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_worktree.md.
---------------------------------------------------------------------------

Real finding (severe — an arbitrary-filesystem-write-anywhere
primitive, same severity class as tool #18's docker_build host-file
finding): neither implementation restricted where a new worktree could
be created. `git worktree add <path> <branch>` writes a full checked-
out copy of the branch's tree to `<path>` — unlike every other file-
path field in this initiative, a worktree's whole purpose is to live
OUTSIDE the current repo directory, so a `check_path_in_worktree()`
containment check (this initiative's usual fix) would actually break
legitimate use, not help. Proved live: `git worktree add
/tmp/td_worktree_evil feature` against a real repo succeeded with zero
restriction, exit 0, planting a full working copy of the `feature`
branch's tree at an attacker/LLM-controlled absolute path anywhere on
the host filesystem — zero confirmation, zero warning.

Second, related finding (flag/positional-shifting confusion — a
variant of the flag-collision class from tools #5/#32/#35/#36/#38/#39/
#40/#41): neither implementation validated that `path`/`branch` aren't
flag-shaped. Proved live: `path="-f"` with `branch="feature"` caused
git to consume `-f` as the `--force` flag and silently reinterpret
`branch`'s value ("feature") as the destination PATH instead — creating
an unintended worktree directory named "feature" inside the CURRENT
repo directory rather than the wrong-but-expected/comprehensible error.
No legitimate `path`/`branch` value starts with `-`.

**Ruled out (git's own safety net):** `git worktree remove` already
refuses by default if the target worktree has modified/untracked files
("use --force to delete it") — neither implementation ever passes
`--force`, so no fix needed there; a worktree with real uncommitted
work cannot be silently discarded through this tool.

Fixed via a shared `validate_git_worktree_inputs(action, path, branch)`
chokepoint (rejects flag-shaped `path`/`branch`, requires both for
`add`, requires `path` for `remove`) used by both real call sites, plus
a real `self._confirm()` gate in `chat_agent.py`'s dispatch before
`add` specifically (the only action that writes new content to an
arbitrary filesystem location) — mirroring the same
irreversible/impactful-action confirmation pattern already established
for `git reset --hard`, force-push to a protected branch, and
`git_restore`'s destructive default. `tools.py`'s standalone handler
blocks `add` outright, matching `undo_changes_h`/`git_restore`'s exact
precedent for a destructive action with no real, safely-confirmable
one-shot caller — `list` and `remove` remain available there since
`list` is read-only and `remove` is already git-safety-netted.
"""

from __future__ import annotations

GIT_WORKTREE_TOOL = {
    "name": "git_worktree",
    "description": "Manage git worktrees — isolated checkouts for parallel work.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "add", "remove"],
                "description": "Action to perform (default: list)",
            },
            "path": {
                "type": "string",
                "description": "Path for the new worktree (required for add)",
            },
            "branch": {
                "type": "string",
                "description": "Branch for the new worktree (required for add)",
            },
        },
        "required": [],
    },
}


def validate_git_worktree_inputs(action: str, path: str, branch: str) -> str | None:
    """Returns an [ERROR] string if inputs are unsafe/incomplete for the
    given `action`, else None. Shared by both real call sites."""
    if path.startswith("-"):
        return (
            f"[ERROR] Invalid path {path!r} — worktree paths may not "
            "start with '-' (this would be interpreted as an additional "
            "git flag, not a path)."
        )
    if branch.startswith("-"):
        return (
            f"[ERROR] Invalid branch {branch!r} — branch names may not "
            "start with '-' (this would be interpreted as an additional "
            "git flag, not a branch name)."
        )
    if action == "add" and (not path or not branch):
        return "[ERROR] path and branch required for add"
    if action == "remove" and not path:
        return "[ERROR] path required for remove"
    return None

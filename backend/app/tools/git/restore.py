"""git_restore tool — tool_enhance.md productionization pass, tool
#41 (2026-08-19).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_restore
Old path: app/agents/tools.py (`_GIT_RESTORE_TOOL` schema dict and the
    `git_restore` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body)
New path: app/tools/git/restore.py (this file) — `GIT_RESTORE_TOOL`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, the only real, reachable caller.
    `make_chat_handlers`'s own copy is NOT a real reachable caller —
    grepped the whole repo for "git_restore" outside these two files
    and app/fleet/tool_manifest.py's metadata-only entry: it appears in
    zero agent's `allowed_tools`, same as `undo_changes` before its
    tool #4/#11 fix.
Affected modules: app/agents/tools.py (schema re-export; `git_restore`
    handler now unconditionally blocked, matching `undo_changes_h`'s
    established pattern for a tool with no real, safely-confirmable
    caller), app/agents/chat_agent.py (its real dispatch now adds a
    protected-path check + a real confirmation gate before the
    destructive, default working-tree-discard case).
Affected registries: none — app/fleet/tool_manifest.py's "git_restore"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["git_restore"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_git_restore_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_restore.md.
---------------------------------------------------------------------------

Real finding (severe — this tool's own schema description literally
reads "This CANNOT be undone", yet neither real implementation had any
protected-path check or confirmation gate before running it):

- **`chat_agent.py`'s real dispatch** built `["restore", ..., path]` and
  ran it immediately with zero `_is_protected_path()` check and zero
  `self._confirm()` call — proved live: `git_restore` against a file
  with real uncommitted content silently discarded it, no warning, no
  way to cancel. Compare directly to `undo_changes` (a functionally
  identical tool — discard uncommitted changes to one file, also
  irreversible), which already has BOTH a protected-path check and a
  real confirmation dialog in this same file
  (`app/agents/chat_agent.py`, the `undo_changes` branch). `git_restore`
  was its unprotected twin.
- **`make_chat_handlers`'s own `git_restore`** has the identical gap,
  but — like `undo_changes_h` before its own tool #4/#11 fix — is never
  actually reachable by any real one-shot/batch agent (`session` is
  never non-None for any real caller of `make_chat_handlers()`, and
  `git_restore` is in zero agent's `allowed_tools`; grepped the whole
  repo to confirm). There is no per-call approval channel for a
  one-shot agent to safely confirm an irreversible action through, so
  — matching the exact precedent `undo_changes_h` already established —
  this handler is now unconditionally blocked with a clear message
  instead of silently executing an unconfirmable destructive command.

**Ruled out (git's own boundary protection, same class as tools #27's
`patch` and #37's `git add` findings):** worktree-boundary escape via
`path`. Empirically tested both an absolute outside-repo path and a
`../`-traversal path — `git restore` itself already refuses both with
`fatal: ... is outside repository`, exit 128. No fix needed for this
angle, though the fix below still adds an explicit `_is_protected_path`
check (matching `undo_changes`'s own defense-in-depth, and covering the
denylist patterns `check_path`/`_is_protected_path` enforce beyond pure
worktree containment, e.g. `.env`/`.git/`).

**Also ruled out:** flag-collision via a flag-shaped `path` value.
Unlike the ref/branch fields fixed in tools #5/#32/#35/#36/#38/#39/#40,
`git restore` structurally requires an actual pathspec argument — a
flag-shaped `path` (e.g. `"--ours"`) leaves the command with no real
target and git refuses with "you must specify path(s) to restore" (or
equivalent), verified live. Still added a `--` pathspec separator
before `path` in the fixed command for defense-in-depth and consistency
with the `git add --`/`git checkout --` convention used elsewhere in
this initiative (tools #11's `undo_changes`, #37's `git_commit`).
"""

from __future__ import annotations

GIT_RESTORE_TOOL = {
    "name": "git_restore",
    "description": "Discard changes in a file and restore it to the last committed version. This CANNOT be undone.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path to restore (relative to repo root)",
            },
            "staged": {
                "type": "boolean",
                "description": "Unstage staged changes instead of discarding working tree changes (default: false)",
            },
        },
        "required": ["path"],
    },
}

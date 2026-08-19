# Tool #41 — `git_restore` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_chat_handlers()`'s own `git_restore`.

Both use list-args `subprocess.run`/the shared `_git()` helper — no
`shell=True`, so no shell-injection surface for `path`.

## Problems found (real, empirically verified — severe: this tool's own
schema description literally reads "This CANNOT be undone", yet neither
real implementation enforced anything before running it)

Neither implementation had **any protected-path check or confirmation
gate**. `chat_agent.py`'s real dispatch built `["restore", ..., path]`
and ran it immediately. Compare directly to `undo_changes` — a
functionally identical sibling tool in this exact same file (discard
uncommitted changes to one file, also irreversible) — which already has
both a real `_is_protected_path()` check and a real `self._confirm()`
dialog. `git_restore` was its unprotected twin: proved live that a real
file's uncommitted content was silently discarded with zero warning and
no way to cancel.

`make_chat_handlers`'s own `git_restore` has the identical gap, but —
like `undo_changes_h` before its own tool #4/#11 fix — is never
reachable by any real one-shot/batch agent. Grepped the whole repo:
`git_restore` appears in zero agent's `allowed_tools`, and `session` is
never non-None for any real caller of `make_chat_handlers()`. There is
no per-call approval channel for a one-shot agent to safely confirm an
irreversible action through.

**Ruled out (git's own boundary protection, same class as tools #27's
`patch` and #37's `git add` findings):** worktree-boundary escape via
`path`. Empirically tested both an absolute outside-repo path and a
`../`-traversal path — `git restore` itself already refuses both with
`fatal: ... is outside repository`, exit 128.

**Also ruled out:** flag-collision via a flag-shaped `path`. Unlike the
ref/branch fields fixed in tools #5/#32/#35/#36/#38/#39/#40, `git
restore` structurally requires an actual pathspec — a flag-shaped
`path` leaves the command with no real target and git refuses with "you
must specify path(s) to restore", verified live.

## Changes made

- **`app/tools/git/restore.py`** (new): `GIT_RESTORE_TOOL` schema,
  unchanged.
- **`app/agents/chat_agent.py`**: real dispatch now calls
  `_is_protected_path()` first, then — for the destructive default case
  (`staged=False`, discarding real working-tree content) — checks the
  file exists and requires a real `self._confirm()` before running the
  command, mirroring `undo_changes`'s exact established pattern. The
  non-destructive `staged=True` (unstage) case needs no confirmation,
  since it only moves changes out of the index — no content is lost —
  mirroring `git_reset`'s precedent of only confirming on its
  destructive mode. Also added a `--` pathspec separator for defense-
  in-depth, matching the `git add --`/`git checkout --` convention used
  elsewhere in this initiative.
- **`app/agents/tools.py`**: `git_restore` is now unconditionally
  blocked (after a protected-path pre-check) with
  `"[BLOCKED] git_restore requires interactive session for safety
  confirmation"`, matching `undo_changes_h`'s exact established
  precedent for a tool with no real, safely-confirmable one-shot
  caller.

## Tests (real, not mocked at the mechanism level — real git repos, real
subprocess execution)

`tests/test_git_restore_hardening.py` (new, 8 tests):

- Schema shape check.
- **The proven missing-confirmation-gate finding, verified closed**: a
  declined confirmation preserves the real uncommitted content; an
  approved confirmation genuinely discards it (both through
  `chat_agent.py`'s dispatch); the standalone `make_chat_handlers`
  version is confirmed blocked with the content left untouched.
- Protected-path rejection (`.env`) verified on both real call sites.
- Regression: a `staged=True` unstage requires zero confirmation calls
  (enforced via a fake `_confirm` that raises if invoked) and correctly
  moves a real staged change back to unstaged with its content intact;
  a nonexistent file returns a clean `[ERROR]`.

## Regression

Targeted sweep (new test file + git_rebase + git_pull hardening): **25
passed.** Full suite re-run after this pass: **5171 passed, 52 skipped,
18 deselected, 0 failed** (up from 5163 before this tool).

## Final verdict

**GREEN FLAG.**

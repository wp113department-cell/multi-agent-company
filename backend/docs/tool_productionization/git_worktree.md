# Tool #43 — `git_worktree` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_chat_handlers()`'s own `git_worktree`.

Both use list-args `subprocess.run`/the shared `_git()` helper — no
`shell=True`, so no shell-injection surface.

## Problems found (real, empirically verified)

**Severe — an arbitrary-filesystem-write-anywhere primitive, same
severity class as tool #18's docker_build host-file finding.** Neither
implementation restricted where a new worktree could be created.
`git worktree add <path> <branch>` writes a full checked-out copy of
the branch's tree to `<path>`. Unlike every other file-path field in
this initiative, a worktree's whole purpose is to live OUTSIDE the
current repo directory, so this initiative's usual
`check_path_in_worktree()` containment fix would actually break
legitimate use here. Proved live:

```
git worktree add /tmp/td_worktree_evil feature
```

against a real repo succeeded with zero restriction, exit 0, planting a
full working copy of the `feature` branch's tree at an
attacker/LLM-controlled absolute path anywhere on the host filesystem —
zero confirmation, zero warning.

**Flag/positional-shifting confusion** (a variant of the flag-collision
class from tools #5/#32/#35/#36/#38/#39/#40/#41): neither
implementation validated that `path`/`branch` aren't flag-shaped.
Proved live: `path="-f"` with `branch="feature"` caused git to consume
`-f` as the `--force` flag and silently reinterpret `branch`'s value
("feature") as the destination PATH instead — creating an unintended
worktree directory named "feature" inside the CURRENT repo directory,
rather than a clear error.

**Ruled out (git's own safety net):** `git worktree remove` already
refuses by default if the target worktree has modified/untracked files
("use --force to delete it") — neither implementation ever passes
`--force`, so a worktree with real uncommitted work cannot be silently
discarded through this tool.

## Changes made

- **`app/tools/git/worktree.py`** (new): `GIT_WORKTREE_TOOL` (schema,
  unchanged) and `validate_git_worktree_inputs(action, path, branch)` —
  rejects flag-shaped `path`/`branch`, requires both for `add`,
  requires `path` for `remove`. Used by both real call sites.
- **`app/agents/chat_agent.py`**: real dispatch now validates inputs,
  then adds a real `self._confirm()` gate before `add` specifically
  (the only action that writes new content to an arbitrary filesystem
  location) — mirroring the same irreversible/impactful-action
  confirmation pattern already established for `git reset --hard`,
  force-push to a protected branch, and tool #41's `git_restore`. Both
  `add` and `remove` now use a `--` pathspec separator for defense-in-
  depth.
- **`app/agents/tools.py`**: handler now validates inputs and
  unconditionally blocks `add` with a clear message, matching
  `undo_changes_h`/`git_restore`'s exact established precedent for a
  destructive/impactful action with no real, safely-confirmable
  one-shot caller (`git_worktree` is in zero agent's `allowed_tools` —
  grepped the whole repo to confirm). `list` and `remove` remain
  available there since `list` is read-only and `remove` is already
  git-safety-netted.

## Tests (real, not mocked at the mechanism level — real git repos, real
subprocess execution)

`tests/test_git_worktree_hardening.py` (new, 11 tests):

- Schema enum shape check.
- Pure validator tests: flag-shaped `path`/`branch` rejected, required
  fields enforced per action, `list` allowed with no extra fields.
- **The proven arbitrary-path-write finding, verified closed**: a
  declined confirmation creates nothing; an approved confirmation
  genuinely creates a real worktree (checked via the worktree
  directory and its file existing on disk); the standalone
  `make_chat_handlers` version is confirmed blocked with nothing
  created.
- **The proven flag/positional-shifting finding, verified closed**:
  `path="-f"` rejected, confirmed no unintended directory was created.
- Regression: a real add → list → remove round trip (worktree
  confirmed to exist after add, appear in list output, and be gone
  after remove) through `chat_agent.py`, plus a real `list` through
  `make_chat_handlers`.

## Regression

Targeted sweep (new test file + git_stash + git_restore hardening):
**27 passed.** Full suite re-run after this pass: **5190 passed, 52
skipped, 18 deselected, 0 failed** (up from 5179 before this tool).

## Final verdict

**GREEN FLAG.**

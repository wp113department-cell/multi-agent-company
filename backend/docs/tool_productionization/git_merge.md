# Tool #38 — `git_merge` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_chat_handlers()`'s own `git_merge`.

Both use list-args `subprocess.run`/the shared `_git()` helper — no
`shell=True`, so no shell-injection surface for `branch`.

## Problems found (real, empirically verified — moderate-to-severe: same
flag-collision shape as tools #5/#32/#35/#36, but more plausible in
practice than #36's cherry_pick finding)

Both implementations built `["git", "merge", ..., branch]` with **zero
validation that `branch` isn't itself a flag-shaped string**. `branch`
is documented purely as "Branch name to merge into current branch" — no
legitimate use case for it to start with `-`.

Proved directly against a real repo: a real merge (`branch="feature"`)
produced a real `CONFLICT` state (`UU f.txt`, mid-merge) — this tool's
own returned message explicitly instructs the caller to keep working
with follow-up tool calls ("Use parse_merge_conflicts... then
resolve_merge_conflict... then git_commit to finish the merge"). At
that point, calling `git_merge` again with `branch="--abort"` **fully
and silently discarded the in-progress conflict-resolution state**,
returning the repo to its pre-merge tree with exit 0 — no confirmation,
no warning. Unlike tool #36's `cherry_pick --abort` (which needs an
unrelated, independently-started cherry-pick to be in flight for
`--abort` to matter), THIS tool itself is what produces the
conflict state in the first place, making a stray/adversarial
`branch="--abort"` a highly plausible real interaction rather than a
hypothetical edge case.

## Changes made

- **`app/tools/git/merge.py`** (new): `GIT_MERGE_TOOL` (schema,
  unchanged) and `validate_git_merge_inputs(branch)` — the shared
  chokepoint, rejecting an empty or flag-shaped `branch` before either
  implementation builds its git command. Mirrors
  `validate_git_cherry_pick_inputs`/`validate_git_checkout_inputs`'s
  exact pattern and reasoning (tools #35/#36).
- **`app/agents/chat_agent.py`**, **`app/agents/tools.py`**: both real
  call sites now call the shared validator before building their
  command.

## Tests (real, not mocked at the mechanism level — real git repos, real
subprocess execution)

`tests/test_git_merge_hardening.py` (new, 8 tests):

- Schema shape check.
- Pure validator tests: flag-shaped `branch` rejected (`--abort`,
  `--quit`, `-X`), empty `branch` rejected, a real legitimate branch/ref
  allowed.
- **The exact proven exploit, verified closed against both real call
  sites**: a real merge conflict is produced, then `branch="--abort"`
  is rejected and the conflict state (`git status --short` showing
  `UU f.txt`) is confirmed to survive untouched.
- Regression: a real no-ff merge (confirmed via the merge commit and
  the new file landing) through `chat_agent.py`, and a real
  fast-forward merge through `make_chat_handlers`.

## Regression

Targeted sweep (new test file + git_commit + git_cherry_pick
hardening): **27 passed.** Full suite re-run after this pass: **5146
passed, 52 skipped, 18 deselected** (up from 5138 before this tool).

## Final verdict

**GREEN FLAG.**

# Tool #36 — `git_cherry_pick` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_chat_handlers()`'s own `git_cherry_pick_h`.

Both use list-args `subprocess.run`/the shared `_git()` helper — no
`shell=True`, so no shell-injection surface for `commit_hash`.

## Problems found (real, empirically verified — moderate: same
flag-collision shape as tools #5/#32/#35, but narrower blast radius)

Both implementations built `["git", "cherry-pick", ..., commit_hash]`
with **zero validation that `commit_hash` isn't itself a flag-shaped
string**. `commit_hash` is documented purely as "SHA or ref of the
commit to cherry-pick" — no legitimate use case for it to start with
`-`.

Unlike `git_checkout`'s `-f` (tool #35, a real, immediate, single-call
data-loss exploit) or `create_branch`'s `-D` (tool #32, a real,
immediate branch deletion), empirically testing every dangerous-looking
`git cherry-pick` flag against a real repo with **no cherry-pick already
in progress** produced only clean, fail-closed errors:

- `git cherry-pick --abort` → `"error: no cherry-pick or revert in
  progress"`, exit 128.
- `git cherry-pick -n` (alone, no commit) → usage text, exit 129.

No single-call destructive exploit was reproducible this way.
`--abort`/`--quit`/`--skip` DO have real side effects (discarding
in-progress conflict-resolution state) **if a cherry-pick sequence
happens to already be active** — a narrower, two-step scenario than
every sibling git-ref finding in this initiative.

Fixed anyway, for consistency with the same validated-ref pattern
already applied to every sibling git ref/target field (tools
#5/#32/#35) and because the schema's own documented contract already
rules out flag-shaped values.

## Changes made

- **`app/tools/git/cherry_pick.py`** (new): `GIT_CHERRY_PICK_TOOL`
  (schema, unchanged) and `validate_git_cherry_pick_inputs(commit_hash)`
  — the shared chokepoint, rejecting an empty or flag-shaped
  `commit_hash` before either implementation builds its git command.
  Mirrors `validate_git_checkout_inputs`/`validate_create_branch_inputs`'s
  exact pattern and reasoning (tools #32/#35).
- **`app/agents/chat_agent.py`**, **`app/agents/tools.py`**: both real
  call sites now call the shared validator before building their
  command.

## Tests (real, not mocked at the mechanism level — real git repos, real
subprocess execution)

`tests/test_git_cherry_pick_hardening.py` (new, 11 tests):

- Schema shape check.
- Pure validator tests: flag-shaped `commit_hash` rejected (`-D`,
  `--abort`, `--quit`, `--skip`, `-n`), empty `commit_hash` rejected, a
  real legitimate hash/ref/relative-ref allowed.
- The proven flag-collision finding, verified closed against both real
  call sites: `commit_hash="--abort"` / `"-D"` rejected before ever
  reaching `subprocess.run`.
- Regression: a real cherry-pick against a real two-branch repo,
  confirmed via the target file's post-pick content and `git log`
  showing the picked commit — through both `chat_agent.py`'s dispatch
  and `make_chat_handlers`. Also covers `no_commit=True` (confirms the
  change is staged but no new commit is created).

## Regression

Targeted sweep (new test file + git_checkout + create_branch hardening):
**30 passed.** Full suite re-run after this pass: **5128 passed, 52
skipped, 18 deselected** (up from 5119 before this tool).

## Final verdict

**GREEN FLAG.**

# Tool #39 — `git_pull` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_chat_handlers()`'s own `git_pull`.

Both use list-args `subprocess.run`/the shared `_git()` helper — no
`shell=True`, so no shell-injection surface for `remote`/`branch`.

## Problems found (real, empirically verified — moderate: same
flag-collision shape as tools #5/#32/#35/#36/#38, but lower severity)

Both implementations built `["git", "pull", ..., remote, branch]` with
**zero validation that `remote`/`branch` aren't themselves flag-shaped
strings**. Neither field has a legitimate use case for starting with
`-` — `remote` is documented as "Remote name (default: origin)",
`branch` as "Branch to pull (default: current branch)".

Proved live against a real local bare-remote clone:

```python
handlers["git_pull"]({"remote": "--force"})
handlers["git_pull"]({"remote": "origin", "branch": "--force"})
```

Both ran successfully (exit 0) with git silently treating `--force` as
a real flag rather than a literal remote/branch name. This does **not**
reproduce a checkout/merge/cherry-pick-style data-loss exploit — `pull
--force` only affects non-fast-forward ref/tag updates during the
underlying fetch, not the merge/rebase step's working-tree safety,
which already refuses to clobber uncommitted local changes regardless
of this flag. The real effect is the LLM's intended remote/branch
silently being dropped and replaced by flag behavior — a
correctness/silent-wrong-action bug, not a data-loss one.

Fixed anyway, for consistency with the same validated-ref pattern
already applied to every sibling git ref/target field in this
initiative and because neither field's own documented contract allows
a flag-shaped value.

## Changes made

- **`app/tools/git/pull.py`** (new): `GIT_PULL_TOOL` (schema,
  unchanged) and `validate_git_pull_inputs(remote, branch)` — the
  shared chokepoint, rejecting a flag-shaped `remote` or `branch`
  before either implementation builds its git command.
- **`app/agents/chat_agent.py`**, **`app/agents/tools.py`**: both real
  call sites now call the shared validator before building their
  command.

## Tests (real, not mocked at the mechanism level — real git repos, a
real local bare "remote", real clones, real subprocess execution)

`tests/test_git_pull_hardening.py` (new, 8 tests):

- Schema shape check.
- Pure validator tests: flag-shaped `remote` rejected, flag-shaped
  `branch` rejected, a real legitimate remote/branch allowed.
- **The exact proven finding, verified closed against both real call
  sites**: `remote="--force"` / `branch="--force"` rejected before ever
  reaching `subprocess.run`.
- Regression: a real pull against a real local bare remote + clone,
  confirmed via the pulled file's post-pull content — through both
  `chat_agent.py`'s dispatch and `make_chat_handlers` (including the
  default-args no-op-schema-required case).

## Regression

Targeted sweep (new test file + git_merge + git_commit hardening):
**26 passed.** Full suite re-run after this pass: **5154 passed, 52
skipped, 18 deselected** (up from 5146 before this tool).

## Final verdict

**GREEN FLAG.**

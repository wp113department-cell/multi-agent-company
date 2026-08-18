# Tool #32 — `create_branch` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_chat_handlers()`'s own `create_branch`.

Both use list-args `subprocess.run`/the shared `_git()` helper — no
`shell=True`, so no shell-injection surface for `name`/`from_branch`.

## Problems found (real, empirically verified — severe: same bug class
as tool #5's `git_reset` flag-collision bug)

Both implementations built `["git", "branch", name, from_branch]` with
**zero validation that `name` isn't itself a flag-shaped string**.
Proved directly against a real repo, through the real `chat_agent.py`
dispatch:

```python
result = await agent._execute_tool("create_branch", {
    "name": "-D",
    "from_branch": "important-feature-branch",  # a real, existing branch
})
```

produces the real command `git branch -D important-feature-branch` —
**deleting the real branch** — even though `create_branch` is documented
and used everywhere in this codebase as a purely additive, non-
destructive operation, with no confirmation gate anywhere (unlike
genuinely destructive tools like `git_reset`/`delete_file`, which do get
one).

Worse, the subsequent checkout step (`do_checkout` defaults to `True`)
then failed for an unrelated reason (`-D` isn't a valid `git checkout`
flag either), producing a confusing `[ERROR]` message that gave **no
indication the branch deletion had already happened for real** in the
first step — a caller reading only the returned error text would
reasonably assume nothing happened at all.

## Changes made

- **`app/tools/git/create_branch.py`** (new): `CREATE_BRANCH_TOOL`
  (schema, unchanged) and `validate_create_branch_inputs(name,
  from_branch)` — the shared chokepoint, rejecting any `name`/
  `from_branch` starting with `-` before either implementation builds
  its git command. Mirrors `validate_git_reset_inputs`'s exact pattern
  and reasoning (tool #5).
- **`app/agents/chat_agent.py`**, **`app/agents/tools.py`**: both real
  call sites now call the shared validator before building their
  command.

## Tests (real, not mocked at the mechanism level — real git repos, real
subprocess execution)

`tests/test_create_branch_hardening.py` (new, 11 tests):

- Schema shape check.
- Pure validator tests: flag-shaped `name` rejected, flag-shaped
  `from_branch` rejected, empty `name` rejected, a real legitimate name
  (with and without a base branch) allowed.
- **The exact proven exploit, verified closed against both real call
  sites**: `name="-D"` + a real, existing `from_branch` is rejected, and
  the target branch is confirmed to still exist afterward — through both
  `chat_agent.py`'s dispatch and `make_chat_handlers`.
- Regression: real branch creation with checkout (confirmed via `git
  branch --show-current`), without checkout, from a real named base
  branch, and through `make_chat_handlers` directly.

## Regression

Targeted sweep (new test file + git_reset/git_tag hardening): **31
passed.** Full suite re-run after this pass — see
`tool_enhance_tracking.md`'s row for this tool for the final count.

## Final verdict

**GREEN FLAG.**

A real, live, silent-branch-deletion vulnerability — masked by a
misleading downstream error message — closed with the same validated
pattern already proven correct for tool #5's `git_reset`. No
functionality lost: real branch creation, with or without checkout, from
any real base branch, continues to work exactly as before.

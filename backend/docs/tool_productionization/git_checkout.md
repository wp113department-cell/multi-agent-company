# Tool #35 — `git_checkout` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_chat_handlers()`'s own `git_checkout`.

Both use list-args `subprocess.run`/the shared `_git()` helper — no
`shell=True`, so no shell-injection surface for `target`/`file`.

## Problems found (real, empirically verified — severe: same bug class
as tools #5/#32's flag-collision bugs, arguably worse since neither
implementation has any confirmation gate at all)

Both implementations built `["git", "checkout", target]` with **zero
validation that `target` isn't itself a flag-shaped string**. `target`
is documented purely as "Branch name or commit hash to checkout" — no
legitimate use case for it to start with `-`. Proved directly, through
the real `chat_agent.py` dispatch, against a real repo with real
uncommitted work:

```python
result = await agent._execute_tool("git_checkout", {"target": "-f"})
```

produces the real command `git checkout -f` — `-f`/`--force` **silently
discards uncommitted local changes** when switching branches (or, with
no other branch given, discards the current branch's uncommitted
changes back to the last commit). A real, uncommitted file's content was
genuinely destroyed, and the tool returned `"(no output)"` — giving zero
indication anything destructive had happened. Unlike `git_reset --hard`
(tool #5, which at least gets a confirmation gate), `git_checkout` has
no confirmation gate anywhere in this codebase.

## Changes made

- **`app/tools/git/checkout.py`** (new): `GIT_CHECKOUT_TOOL` (schema,
  unchanged) and `validate_git_checkout_inputs(target, file)` — the
  shared chokepoint, rejecting any `target`/`file` starting with `-`
  before either implementation builds its git command. Mirrors
  `validate_git_reset_inputs`/`validate_create_branch_inputs`'s exact
  pattern and reasoning (tools #5/#32).
- **`app/agents/chat_agent.py`**, **`app/agents/tools.py`**: both real
  call sites now call the shared validator before building their
  command.

## Tests (real, not mocked at the mechanism level — real git repos, real
subprocess execution)

`tests/test_git_checkout_hardening.py` (new, 10 tests):

- Schema shape check.
- Pure validator tests: flag-shaped `target` rejected, flag-shaped
  `file` rejected, empty `target` rejected, a real legitimate
  target/file allowed.
- **The exact proven exploit, verified closed against both real call
  sites**: `target="-f"` against a real repo with real uncommitted work
  is rejected, and the uncommitted content is confirmed to survive
  untouched — through both `chat_agent.py`'s dispatch and
  `make_chat_handlers`.
- Regression: a real branch switch (confirmed via `git branch
  --show-current`), a real single-file restore from `HEAD` (confirmed
  the file's content reverts to the committed version), and the same
  branch switch through `make_chat_handlers`.

## Regression

Targeted sweep (new test file + git_service + create_branch hardening):
**43 passed.** Full suite re-run after this pass — see
`tool_enhance_tracking.md`'s row for this tool for the final count.

## Final verdict

**GREEN FLAG.**

A real, live, silent-data-loss vulnerability — with no confirmation gate
at all, unlike its sibling `git_reset` — closed with the same validated
pattern already proven correct for tools #5/#32. No functionality lost:
real branch switching and real single-file restoration both continue to
work exactly as before.

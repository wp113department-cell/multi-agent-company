# Tool #40 — `git_rebase` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_chat_handlers()`'s own `git_rebase_h`.

Both use list-args `subprocess.run`/the shared `_git()` helper — no
`shell=True`, so no shell-injection surface for `onto`.

## Problems found (real, empirically verified — severe: same
flag-collision shape as tool #38's `git_merge` finding, equally
plausible in practice)

Both implementations built `["git", "rebase", onto]` with **zero
validation that `onto` isn't itself a flag-shaped string**. `onto` is
documented purely as "Branch or commit to rebase onto (e.g. 'main',
'HEAD~3')" — no legitimate use case for it to start with `-`.

Proved directly against a real repo: a real rebase (`onto="feature"`)
produced a real conflict (`UU f.txt`, mid-rebase) — git's own error
output for this exact command literally suggests the next step:

```
hint: To abort and get back to the state before "git rebase", run "git rebase --abort".
```

At that point, calling `git_rebase` again with `onto="--abort"` **fully
and silently discarded the in-progress rebase conflict**, returning the
repo to its pre-rebase state with exit 0 — no confirmation, no warning.
Same severity class as tool #38's `git_merge --abort` finding: this
tool itself is what produces the conflict state in the first place,
making a stray/adversarial `onto="--abort"` a highly plausible real
interaction rather than a hypothetical edge case.

## Changes made

- **`app/tools/git/rebase.py`** (new): `GIT_REBASE_TOOL` (schema,
  unchanged) and `validate_git_rebase_inputs(onto)` — the shared
  chokepoint, rejecting an empty or flag-shaped `onto` before either
  implementation builds its git command. Mirrors
  `validate_git_merge_inputs`/`validate_git_cherry_pick_inputs`'s exact
  pattern and reasoning (tools #36/#38).
- **`app/agents/chat_agent.py`**, **`app/agents/tools.py`**: both real
  call sites now call the shared validator before building their
  command (and before the existing `interactive` TTY-block check,
  unchanged).

## Tests (real, not mocked at the mechanism level — real git repos, real
subprocess execution)

`tests/test_git_rebase_hardening.py` (new, 9 tests):

- Schema shape check.
- Pure validator tests: flag-shaped `onto` rejected (`--abort`,
  `--skip`, `-i`), empty `onto` rejected, a real legitimate
  branch/relative-ref allowed.
- **The exact proven exploit, verified closed against both real call
  sites**: a real rebase conflict is produced, then `onto="--abort"` is
  rejected and the conflict state (`git status --short` showing
  `UU f.txt`) is confirmed to survive untouched.
- Regression: a real clean rebase (confirmed via `git log` showing both
  commits) through both `chat_agent.py`'s dispatch and
  `make_chat_handlers`, plus confirmation the pre-existing
  `interactive=True` TTY-block still fires correctly.

## Regression

Targeted sweep (new test file + git_pull + git_merge hardening): **25
passed.**

Full suite re-run after this pass surfaced 4 failures, none from this
tool's own change:

- **2 real, caused by this modularization pass (fixed as part of this
  turn)**: `tests/test_new_tools.py::test_total_tool_names_190` and
  `tests/test_final_session.py::test_total_tools_190` both regex-scan
  only `app/agents/tools.py`'s raw text for `"name": "..."` literals and
  assert the count is `>= 190`. Since tool #40 (git_rebase) is the
  latest in a long line of tools whose schema got moved out of
  `tools.py` into `app/tools/<domain>/`, this crossed the count below
  190 for the first time this initiative. No tool was actually lost —
  scanning `tools.py` + all of `app/tools/**/*.py` together (the real,
  current location of every tool schema) gives 229 unique names. Fixed
  both tests to scan both locations, preserving their real intent
  (catch an actually-deleted tool) while accounting for the
  intentional, ongoing modularization.
- **2 pre-existing, unrelated to git_rebase or this pass**:
  `tests/test_audit04_orchestration_fixes.py::TestOrch04_001_LaunchCoderCommits::test_launch_coder_commits_files_before_diff`
  and
  `tests/test_day0_capabilities.py::TestMemoryHookNodeFires::test_memory_hook_merges_lessonstore_and_db_memory`
  both pass cleanly when run in isolation — confirmed real (order-
  dependent/state-leakage flakiness in a 5000+ test suite), not caused
  by this tool's change. Left as-is; out of this tool's scope.

Full suite re-run once more after the test-count fix: **5163 passed, 52
skipped, 18 deselected, 0 failed** (up from 5154 before this tool; the
two flaky orchestration/memory-hook tests both passed cleanly on this
rerun, confirming they were pre-existing order-dependent noise).

## Final verdict

**GREEN FLAG.**

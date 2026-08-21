# Tool #54 — `npm_run` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations, BOTH real and reachable before this fix:

1. `chat_agent.py`'s real interactive dispatch — reachability already
   fixed by tool #4.
2. `make_chat_handlers()`'s own `npm_run_h` — unlike its
   `npm_install`/`pip_install` siblings (already unconditionally
   `[BLOCKED]` since tool #4), this one was NOT blocked, despite having
   no real one-shot caller either.

## Problems found (real, empirically verified — severe, and worse than
tool #53's `npm_install` finding since neither implementation had a
confirmation gate at all)

Both implementations built `target_dir = str(root / directory)` with
**zero validation that `directory` stays inside the repo**. Proved
live, through `make_chat_handlers`'s own `npm_run` — no confirmation
dialog stood between the call and real code execution:

```python
handlers["npm_run"]({"script": "build", "directory": "/tmp/td_npmrun_outside"})
```

where `/tmp/td_npmrun_outside/package.json` had a `build` script of
`"touch /tmp/td_npmrun_PWNED_marker"` — genuinely executed, confirmed
via the marker file's real existence afterward.

**Second, real finding: an inconsistency with npm_run's own siblings.**
`make_chat_handlers`'s `npm_run_h` had zero real one-shot caller
(grepped: not in any agent's `allowed_tools`) and produces a real side
effect (arbitrary script execution) — the exact same shape
`npm_install_h`/`pip_install_h` already handle by being unconditionally
`[BLOCKED]` right next to it in the same file. `npm_run_h` was
apparently missed when that policy was applied during tool #4's
earlier pass.

## Changes made

- **`app/tools/execution/npm_run.py`** (new): `NPM_RUN_TOOL` (schema,
  unchanged) and `validate_npm_run_directory(directory, worktree_path)`
  — a `check_path_in_worktree()` chokepoint, same mechanism as tool
  #53's `validate_npm_install_directory`.
- **`app/agents/chat_agent.py`**: real dispatch now rejects an
  out-of-worktree `directory` before ever building the npm command.
  The pre-existing no-confirmation-gate design is **kept** — its
  original reasoning ("running a package.json script is lower-risk
  than installing new dependencies") is only actually true once
  `directory` is genuinely constrained to the real repo (this fix);
  under that constraint `npm run` can only execute a script already
  defined in this repo's own `package.json`, the same trust level
  `run_tests`/`run_make` already operate at without a confirmation
  dialog.
- **`app/agents/tools.py`**: `npm_run_h` is now unconditionally
  `[BLOCKED]`, matching `npm_install_h`/`pip_install_h`'s existing
  precedent in this same file — closing the inconsistency rather than
  leaving it in place.

## Tests (real, not mocked — real `npm` subprocess execution against
real `package.json` files on disk; skipped if `npm` isn't installed)

`tests/test_npm_run_hardening.py` (new, 7 tests):

- Schema shape check, and confirms `npm_run` appears in `CHAT_TOOLS`
  exactly once.
- Pure validator tests: an outside-repo `directory` rejected, a real
  in-repo `directory` allowed.
- **The exact proven exploit, verified closed on both real call
  sites**: the malicious `build`-script/directory setup is rejected
  before `npm` ever runs (real dispatch) and the standalone handler is
  confirmed blocked (`make_chat_handlers`) — both paths' marker files
  confirmed to never exist.
- Regression: a real `npm run` script execution still succeeds
  (confirmed via real stdout output) through `chat_agent.py`.

Also swept 2 pre-existing test files referencing `npm_run`
(`test_git_push_hardening.py`, `test_github_create_pr_hardening.py`) —
both use the default `directory="."` (unaffected) and don't touch the
now-blocked standalone handler; all 27 confirmed still passing.
Searched the whole test suite for any direct
`handlers["npm_run"]` call expecting real execution — found none
besides this turn's own new test.

## Regression

Targeted sweep (new test file + npm_install hardening + the two
pre-existing test files): **42 passed.** Full suite re-run after this
pass: **5277 passed, 52 skipped, 18 deselected, 0 failed** (up from
5270 before this tool).

## Final verdict

**GREEN FLAG.**

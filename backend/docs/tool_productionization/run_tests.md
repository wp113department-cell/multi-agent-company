# Tool #16 — `run_tests` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three implementations:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_chat_handlers()`'s own `run_tests` — reachable by 5 real agents
   per `tool_inventory.json`.
3. `make_fleet_apply_handlers()`'s `run_tests_h` — a narrower,
   pytest-only variant for the 4 fleet self-enhancement agents.

## Problems found (real, empirically verified — same bug class as tool
#8's `run_migration`)

**Shell injection in `chat_agent.py`'s real dispatch.** `path` and
`flags` (both LLM-controlled) were interpolated directly into an f-string
`shell=True` command with zero validation or quoting:

```python
cmd_str = f"cd {repo} && {_venv_activate_snippet()} && python -m pytest {test_path} {flags} --tb=short -q 2>&1"
```

Proved directly, before writing any fix: a `path` value of
`"; touch /tmp/PWNED_run_tests.txt; echo "` created a real marker file on
the host, completely outside the intended pytest invocation.

**`make_chat_handlers`'s own `run_tests` was already correctly
guarded** — `shlex.quote(path)` plus a shell-metacharacter denylist
(`_shell_metachar_reason`) on `flags`, the same established pattern this
codebase already uses for other flag-shaped values that need to stay
multiple space-separated tokens (where `shlex.quote` on the whole string
would collapse it into one argument). The fix for `chat_agent.py` reuses
this already-proven-correct pattern rather than inventing a new one —
the bug was specifically that `chat_agent.py`'s own dispatch never had it
applied, not that the pattern itself needed inventing.

**`make_fleet_apply_handlers`'s `run_tests_h` was also already correctly
guarded**, independently implementing the same pattern.

## Changes made

- **`app/tools/execution/run_tests.py`** (new): `RUN_TESTS_TOOL` (schema
  — unchanged wording, now the single canonical copy) and
  `run_tests_handler(repo_path, inp, *, activate_snippet)` — the shared
  core, applying `shlex.quote(path)` + `_shell_metachar_reason(flags)`
  before building any of the 3 runner-specific commands (pytest,
  npm_test, tsc), execution, pytest-summary parsing, and exit-code-based
  `[ERROR]` prefixing (all ported from `make_chat_handlers`'s own,
  already-correct implementation).
- **`app/agents/chat_agent.py`**: its real dispatch now calls the shared
  handler via `asyncio.to_thread` instead of the vulnerable inline
  f-string construction. Removed the now-unused `parse_pytest_summary`
  import (logic moved into the shared handler).
- **`app/agents/tools.py`**: `make_chat_handlers`'s own `run_tests` now
  delegates to the shared function. `_RUN_TESTS_TOOL` (used across
  several tool lists) now aliases the canonical schema. Removed the
  now-unused `parse_pytest_summary` import.

**One observable, intentional, low-risk change**: `chat_agent.py`'s
dispatch previously truncated output to 8000 chars; the shared handler
(matching `make_chat_handlers`'s prior behavior) truncates to 5000.
Checked every test referencing `run_tests`'s output length beforehand —
none exist; only substring/prefix assertions.

**Deliberately left untouched**: `make_fleet_apply_handlers`'s
`run_tests_h` — already correctly guarded, but a real, intentionally
narrower tool (pytest-only, no `runner` field, tail-truncates instead of
head-truncates, no pytest-summary parsing) for the 4 fleet agents, not
accidental duplication.

## Tests (real, not mocked at the mechanism level — real
subprocess/pytest execution throughout)

`tests/test_run_tests_hardening.py` (new, 13 tests):

- Schema shape check.
- **The exact proven exploit, verified closed**: shell injection via
  `path`, shell injection via `flags`, and shell-metacharacter rejection
  in `flags` across all 3 runners.
- Regression: a real passing pytest run, a real failing pytest run
  correctly flagged `[ERROR]` with the failure message intact, an
  unknown-runner error, pytest-summary text present on a real failure.
- Both real call sites exercised directly, each proving the exploit is
  closed end-to-end: `chat_agent.py`'s dispatch (previously **untested**
  for this tool — a real coverage gap closed) and `make_chat_handlers`'s
  own handler.

## Regression

Targeted sweep (new test file + gap15/audit_q_batch01/gap50 tests +
run_sql/run_python_snippet hardening): **85 passed.** Full suite re-run
after this pass — see `tool_enhance_tracking.md`'s row for this tool for
the final count.

## Final verdict

**GREEN FLAG.**

A real, live shell-injection vulnerability — closed by applying an
already-proven-correct pattern from a sibling implementation, not
inventing new validation logic. No functionality lost: real passing and
failing test runs, pytest-summary parsing, and exit-code-based failure
detection all continue to work exactly as before.

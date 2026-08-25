# Tool #101 — `run_linter` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Four real implementations:

1. `chat_agent.py`'s own interactive dispatch (`shell=True`, **no
   quoting at all**).
2. `run_linter` inside `make_chat_handlers()` (`shell=True` +
   `shlex.quote()`).
3. `sr_run_linter` (`make_style_reviewer_handlers`).
4. `td_run_linter` (`make_tech_debt_agent_handlers`).

Per `tool_inventory.json`, agents declaring `run_linter` go through
one of the factories above. `CHAT_TOOLS.count("run_linter") == 1`
verified. 2 existing test files reference this tool — read in context,
directly-exercising tests re-run and confirmed passing unchanged (7
tests).

## Problems found

**Finding #1 — the most severe of this initiative's `run_linter`
audit: a genuine, direct shell-injection (arbitrary command
execution), on `chat_agent.py`'s dispatch.** `lint_path` was
interpolated COMPLETELY UNQUOTED (not even `shlex.quote()`'d, unlike
the sibling `make_chat_handlers` implementation) into an f-string
`shell=True` command. Proved live: `path="; touch /tmp/
PWNED_RUN_LINTER_SHELL; echo x"` genuinely created a real file outside
any intended scope — the injected command executed for real, same
severity class as tool #8's `run_migration` shell injection.

**Finding #2 — a real, severe confirmation/opt-in bypass, on
`make_chat_handlers`' `run_linter`.** The schema documents `fix` as an
explicit, default-`False` opt-in boolean. But `path` was placed as a
bare positional shell token, protected only by `shlex.quote()` (shell-
safety, not the receiving program's own flag parser). Proved live:
`path="--fix"` with `fix` explicitly left at its default `False`
genuinely caused ruff to auto-fix AND REWRITE A REAL FILE ON DISK
(`Found 2 errors (2 fixed, 0 remaining)`) — completely bypassing the
schema's own opt-in contract, similar in spirit to tool #5's
`git_reset` flag-collision confirmation bypass. ruff also has a real
`-o`/`--output-file <path>` flag (arbitrary-file-write primitive)
reachable the same way.

**Finding #3 — `sr_run_linter`/`td_run_linter` are CURRENTLY
COMPLETELY BROKEN for every real call, unrelated to security.** Both
pass `--output-format=text` to ruff — proved live this is not a valid
ruff output format (`error: invalid value 'text' for
'--output-format'`, exit code 2) — EVERY real call fails outright. On
top of that, both implementations ignore the `tool`/`fix` fields
entirely and always hardcode a ruff-only check — the same
"dead/ignored field" class already established for tools
#24/#82/#90/#99.

**Finding #4 — a real, documented-but-unimplemented gap:
`tool="eslint"` is a valid schema enum value, but NO implementation
ever supported it.** Verified `apps/web/package.json` genuinely
configures eslint (`"lint": "eslint ."`) — a real, available
capability the schema promised but no implementation ever wired up.

## Changes made

New shared `run_linter_handler()` in `app/tools/execution/run_linter.py`:
- **structural fix for findings #1/#2, not just validation**: all
  subprocess calls are now list-args (no `shell=True` at all,
  anywhere) — eliminates the shell-injection class by construction;
- `path`, when given, is additionally validated (rejected if
  flag-shaped) and checked via `check_path_in_worktree()`;
- `--output-format=text` replaced with ruff's actual default — closes
  finding #3's total breakage;
- `tool`/`fix` are now read and honored identically across all four
  real call sites — closes finding #3's dead-field bug;
- real `eslint` support added (`npx eslint .` in `apps/web/`, mirroring
  the existing `tsc` invocation shape) — closes finding #4.

Venv activation no longer goes through a shell snippet — list-args
calls invoke the venv's own `python` binary directly by path when
present, falling back to `sys.executable`.

`app/agents/tools.py`'s `_RUN_LINTER_TOOL` now aliases the shared
`RUN_LINTER_TOOL` constant via a plain module-level assignment. One
now-dead `import subprocess as _sp` removed from
`make_style_reviewer_handlers` (`ruff`-caught; the sibling `_sp` in
`make_tech_debt_agent_handlers` is still genuinely used by
`td_coverage_report`, left alone). One now-dead `parse_diagnostic_summary`
import removed from `chat_agent.py` (its only usage was inside the old
`run_linter` dispatch).

## Tests

New file `tests/test_run_linter_hardening.py`, 17 tests, all real (no
mocking, real subprocess calls) — schema check, duplicate-registration
check, real proof the shell injection doesn't execute, real proof the
`--fix` flag-collision is rejected (file verified unchanged) across
the interactive dispatch AND all three handler factories
(parametrized), a real proof the genuine, intended `fix=True`
capability still works (not a regression), real proof
`sr_`/`td_run_linter` actually work now (previously 100% broken), a
real proof `sr_run_linter` now honors the `tool` field, real proof
`eslint` no longer errors, worktree-escape rejection, and
legitimate-usage regression (a real ruff diagnostic) across all four
real access paths. Existing tests (`test_day3_agents.py::
TestStyleReviewerTools`, `TestStyleReviewerHandlers`) re-run and
confirmed passing unchanged (7 tests).

## Regression

Per the established once-per-5-tool-batch cadence, the full suite will
run once this batch (#99-#103) completes — see
`feedback_tool_enhance_batch_full_suite` memory. This tool (#101) is
tool 3 of the batch; its own new hardening tests (17/17 pass) and
directly-referencing existing tests (7/7 pass) are the per-tool
verification gate.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
run_linter.py` sweep (98 files clean), an `importlib.import_module()`
sweep over all 97 `app/agents/` modules (all clean), a `ruff check` on
all 3 touched files (clean, after removing 2 now-dead imports), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** All four real findings — a genuine shell-injection
RCE, a real confirmation-bypass file-rewrite, two implementations that
were completely broken for every call, and a documented-but-missing
eslint capability — proved live and closed across all four real
implementations; the underlying tool became MORE capable (real eslint
support, real mypy support for `sr_`/`td_`) rather than less; no
functionality lost; tool-specific and directly-referencing regression
tests clean. Full-suite confirmation pending as part of the #99-#103
batch.

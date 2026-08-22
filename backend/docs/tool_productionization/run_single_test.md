# Tool #62 — `run_single_test` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

Already flagged as a likely finding during tool #14's proactive scan
(2026-08-17): "`run_single_test` (~L2362) — `rst_kw` sits inside single
quotes in the f-string (`-k '{rst_kw}'`) — a literal `'` in `rst_kw`
breaks out of that quoting; `rst_path`/`rst_vflag` also unquoted."
Confirmed right on `chat_agent.py`'s dispatch. `tools.py`'s own
implementation turned out to already be correctly `shlex.quote()`'d —
only `chat_agent.py` had the injection bug, but a second, more severe
finding affected both (see below).

## Current implementation (audit)

Two real implementations:

1. `chat_agent.py`'s real interactive dispatch — built `f"{activate} &&
   python -m pytest {rst_path} -k '{rst_kw}' {rst_vflag} ..."` with
   `rst_kw` inside single quotes and NO escaping, `rst_path` entirely
   unquoted.
2. `app/agents/tools.py`'s `make_chat_handlers()` `run_single_test` —
   already correctly used `shlex.quote()` on both `rst_path` and
   `rst_kw`.

`CHAT_TOOLS.count("run_single_test") == 1` verified.

## Problems found

**Finding #1 — classic shell injection, `chat_agent.py`'s dispatch
only.** Proved live:

```python
await agent._execute_tool("run_single_test", {
    "keyword": "x' ; touch /tmp/PWNED ; echo '",
})
```

genuinely created `/tmp/PWNED` — the literal `'` in `keyword` broke out
of the single-quoted `-k '...'` region. `tools.py`'s already-correct
`shlex.quote()`'d implementation was not exposed to this exact payload.

**Finding #2 (severe — worktree-boundary escape via `file`, on BOTH
implementations, including the one already correctly quoted).** Neither
implementation validated `file` stayed inside the repo. Proved live
against BOTH real call sites: a real Python file OUTSIDE the repo
(`/tmp/rst_outside_dir/test_evil.py`) with a module-level
`os.system("touch /tmp/PWNED")` side effect was passed as `file`,
pytest collected and imported it, and the side effect genuinely ran —
a real arbitrary-code-execution primitive.

This finding is distinct from the shell-injection/flag-injection/
program-injection classes found in tools #59/#60/#61: it doesn't
involve a shell, a flag, or a choice of program at all. `shlex.quote()`
only prevents shell metacharacters from being interpreted by the
enclosing `shell=True` command; it does nothing to stop `pytest`
itself from IMPORTING an attacker-chosen `.py` file, which executes
that file's module-level code unconditionally as a side effect of
collection — before any test in it even runs. This is why `tools.py`'s
already-quoted implementation was just as exploitable as
`chat_agent.py`'s unquoted one.

## Changes made

- **`app/tools/execution/run_single_test.py`** (new): `RUN_SINGLE_TEST_TOOL`
  schema (moved verbatim), `validate_run_single_test_file(file,
  worktree_path)` — validates `file` via `check_path_in_worktree()`
  when provided (closes finding #2) — plus
  `run_single_test_handler(repo_path, inp, *, activate_snippet)`, a
  single shared implementation using the already-correct
  `shlex.quote()`'d command construction from `tools.py`'s original
  (closes finding #1 by reuse, not reinvention — same precedent as tool
  #16's `run_tests` fix).
- **`app/agents/chat_agent.py`**: dispatch no longer builds its own
  unescaped shell string — delegates to the shared handler, matching
  `tools.py`'s already-safe quoting.
- **`app/agents/tools.py`**: handler now delegates to the same shared
  function (zero behavior change on this side beyond the new `file`
  validation).
- `activate_snippet` is passed in by each caller (not imported into the
  new module), matching `run_python_snippet_handler`'s established
  pattern for this small per-caller helper.

## Tests (real, not mocked — every test runs a genuine pytest
subprocess against real temporary test files)

`tests/test_run_single_test_hardening.py` (new, 12 tests):

- Schema shape check.
- `validate_run_single_test_file()`: allows no file and a relative
  in-repo file; rejects an absolute outside-repo file and a `../`
  traversal.
- **Both proven findings, verified closed**: the exact single-quote
  breakout payload no longer creates a marker file
  (`chat_agent.py`'s dispatch); the exact outside-repo
  import-time-code-execution payload is now rejected before pytest
  ever runs, on both real call sites.
- Regression: a real matching test still runs and reports "1 passed"
  on both call sites, an explicit in-repo `file` still works,
  `run_single_test` appears exactly once in `CHAT_TOOLS`.

Also re-ran `tests/test_chat_tools.py::TestRunSingleTest` (its 1
pre-existing test uses only a keyword, no `file` — confirmed
unaffected) and the full `test_chat_tools.py` file (132 passed).

## Regression

Full suite: **5388 passed, 52 skipped, 18 deselected, 0 failed** (up
from 5375 before this tool).

## Final verdict

**GREEN FLAG.**

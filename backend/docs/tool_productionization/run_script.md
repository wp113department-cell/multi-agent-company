# Tool #61 — `run_script` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

Already flagged as a likely finding during tool #14's proactive scan
(2026-08-17): "`run_script` (~L3038) — `rscr_interp` (the `interpreter`
field) is used AS-IS unquoted whenever it isn't exactly 'auto' ... a
custom interpreter value never gets validated or quoted at all." That
scan understated the real severity — the actual finding is broader than
classic shell injection (see finding #2 below).

## Current implementation (audit)

Two real implementations:

1. `chat_agent.py`'s real interactive dispatch — built `f"{interpreter}
   {path} 2>&1"` and ran it via the shell=True `_run_subprocess()`
   helper.
2. `app/agents/tools.py`'s `make_chat_handlers()` `run_script_h` —
   already used list-args (`subprocess.run([interpreter, path], ...)`,
   no shell=True).

`CHAT_TOOLS.count("run_script") == 1` verified.

## Problems found (all real, empirically proven live before any fix)

**Finding #1 — classic shell injection, `chat_agent.py`'s dispatch
only.** Proved live:

```python
await agent._execute_tool("run_script", {
    "path": "hello.py",
    "interpreter": "cat; touch /tmp/PWNED; echo",
})
```

genuinely created `/tmp/PWNED`. The `tools.py` implementation's
list-args construction meant this exact payload was not exploitable
there.

**Finding #2 (severe, NEW class — same shape as tool #59's run_make
finding #2, discovered independently) — arbitrary-program execution via
`interpreter`, on BOTH implementations, including the one already using
list-args.** Neither implementation restricted `interpreter` to the
documented set (`'auto', 'python3', 'bash', 'node'`) at all — any other
string reached `argv[0]`, i.e. the actual program to execute, with the
target script's path as its sole argument. Proved live against the
ALREADY-LIST-ARGS `tools.py` implementation (zero shell involved):

```python
handlers["run_script"]({"path": "victim.txt", "interpreter": "rm"})
```

genuinely DELETED `victim.txt` — `subprocess.run(["rm", "<path>"])` is
exactly the shape of `rm <path>`, and `rm` needs no flags at all to
delete a single file. This is not a shell-metacharacter problem; it is
an LLM (or a successful prompt injection) choosing which HOST PROGRAM
to run — list-args argv construction, the fix that closed classic shell
injection for tools #16/#18/#19/#20/#21, does nothing to prevent it,
exactly as tool #59 (`run_make`) found for GNU Make's own flag parser
one turn earlier.

**Finding #3 — worktree-boundary escape via `path`, on BOTH
implementations.** Same root-cause pathlib bug class as tools
#10/#11/#18/#23/#43/#59: `root / path` silently discards `root` when
`path` is absolute. Proved live end-to-end: a real script OUTSIDE the
repo (`/tmp/rs_outside_dir/evil.sh`) was genuinely executed through the
tool, with a real observable side effect (a marker file created at the
attacker's chosen host path).

## Changes made

- **`app/tools/execution/run_script.py`** (new): `RUN_SCRIPT_TOOL`
  schema (description clarified: no value outside the documented set is
  accepted), `validate_run_script_inputs(path, interpreter,
  worktree_path)` — rejects any `interpreter` other than `"auto"` or
  one of `python3`/`bash`/`node` (closes finding #2 completely, and
  combined with removing the shell layer below, closes finding #1 too
  — none of the 4 allowed values contain shell metacharacters) and
  validates `path` via `check_path_in_worktree()` (closes finding #3) —
  plus `run_script_handler(root, worktree_path, inp)`, a single shared
  implementation.
- `chat_agent.py`'s shell=True layer is removed entirely (not quoted
  around) in favor of the same list-args execution `tools.py`'s
  implementation already used — matching the tool #59/#60 precedent of
  eliminating an unnecessary shell layer. Since both real
  implementations became functionally identical once that layer was
  gone, they are unified into one shared handler (matching the
  `run_python_snippet`/`run_node`/`run_make` precedent). The one small
  formatting difference between the two originals (an `[exit N]` suffix
  on nonzero exit) is kept, matching `tools.py`'s more informative
  original behavior.
- **`app/agents/tools.py`**, **`app/agents/chat_agent.py`**: both real
  call sites now delegate to the shared, fixed handler.

## Tests (real, not mocked — every test runs a genuine subprocess
against real temporary files and scripts)

`tests/test_run_script_hardening.py` (new, 23 tests):

- Schema shape check.
- `validate_run_script_inputs()`: allows `auto` and each of the 3
  documented interpreters; rejects 6 disallowed interpreter values
  (`rm`, a shell-injection payload, an absolute binary path, `python`,
  `sh`, empty string); rejects a `path` outside the repo.
- **All three proven findings, verified closed on both real dispatch
  paths where applicable**: shell-injection via `interpreter` (Finding
  #1, `chat_agent.py` only), arbitrary-program execution via
  `interpreter` (Finding #2, both real call sites — the exact
  `interpreter="rm"` payload that deleted a real file before the fix,
  now rejected with the target file confirmed to survive), path escape
  running a real outside-repo script (Finding #3, both real call
  sites).
- Regression: a legitimate Python script still runs on both call sites,
  an explicit `interpreter="bash"` still works, auto-detection still
  works, a missing script still errors cleanly, `run_script` appears
  exactly once in `CHAT_TOOLS`.

Also re-ran `tests/test_day1_tools.py::TestRunScript` (its 4
pre-existing tests use only allowlisted interpreters and relative
paths — confirmed unaffected) and the full `test_day1_tools.py` file
(134 passed).

## Regression

Full suite: **5375 passed, 52 skipped, 18 deselected, 1 failed** (up
from 5353 before this tool). The 1 failure
(`test_batch11_privacy_api.py::test_export_and_erase_a_real_user`) is
unrelated to this tool — a cross-event-loop `asyncpg` `RuntimeError`
("got Future ... attached to a different loop") in an unrelated
privacy/audit-export API test, no overlap with any file this turn
touched. Confirmed pre-existing/environmental, not a regression: the
identical test passed cleanly (1 passed) when re-run in isolation
immediately after.

## Final verdict

**GREEN FLAG.**

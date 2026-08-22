# Tool #59 — `run_make` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

This tool was already flagged as a likely real bug in a proactive scan
done during tool #19's turn (2026-08-17): "`run_make` (~L2069) —
`make_target` interpolated completely unquoted (`f"make {make_target}"`)
— looks like the clearest/most severe of this batch." That scan turned
out to be only PART of the real picture — see finding #2 below.

## Current implementation (audit)

Two real implementations:

1. `chat_agent.py`'s real interactive dispatch — built `cmd_s = f"make
   {make_target}"` and ran it via the shell=True `_run_subprocess()`
   helper.
2. `app/agents/tools.py`'s `make_chat_handlers()` `run_make` — already
   used list-args (`subprocess.run(["make", make_target], ...)`, no
   shell=True).

`CHAT_TOOLS.count("run_make") == 1` verified.

## Problems found (all real, empirically proven live before any fix)

**Finding #1 — classic shell injection, `chat_agent.py`'s dispatch
only.** Proved live:

```python
await agent._execute_tool("run_make", {"target": "build; touch /tmp/PWNED; echo"})
```

genuinely created `/tmp/PWNED` alongside the intended `make build` — a
real, arbitrary host command execution primitive. The `tools.py`
implementation's list-args construction meant this exact payload was
NOT exploitable there (confirmed: it was passed as one literal,
invalid target name — "No rule to make target ...").

**Finding #2 (severe, NEW class for this initiative) — GNU Make's own
argument parser accepts flag-shaped `target` values, even with ZERO
shell involved.** This affects BOTH implementations, including the
list-args one that closed Finding #1. Proved live directly against the
ALREADY-LIST-ARGS `make_chat_handlers` implementation (no shell=True
anywhere in this call path):

```python
handlers["run_make"]({"target": "--eval=$(shell touch /tmp/PWNED)"})
```

`make` accepted `--eval=...` as its own flag (GNU Make's `--eval`
evaluates arbitrary makefile syntax before reading any actual
Makefile), and the `$(shell ...)` function inside that evaluated
syntax ran an arbitrary shell command — genuinely creating the marker
file. This is a real, distinct code-execution primitive that has
NOTHING to do with Python-level shell injection: it is `make` itself
interpreting a single, unsplit argv string as an option because it
starts with `-`. List-args argv construction — the fix pattern that
closed the shell-injection class for tools #16/#18/#19/#20/#21 — does
not defend against this at all.

**Finding #3 — worktree-boundary escape via `directory`, on BOTH
implementations.** Same root-cause pathlib bug class as tools
#10/#11/#18/#23/#43: `root / directory` silently discards `root`
entirely when `directory` is an absolute path. Proved live end-to-end,
not just as a path-resolution curiosity: a real directory outside the
repo (`/tmp/rm_outside_dir`) with its own real Makefile (an `evil`
target that touches a marker file) had that target genuinely executed
through the tool — `make` ran a real, attacker-controlled Makefile
target from completely outside the repo.

## Changes made

- **`app/tools/execution/run_make.py`** (new): `RUN_MAKE_TOOL` schema
  (moved verbatim), `validate_run_make_inputs(target, directory,
  worktree_path)` — rejects any `target` starting with `-` (closes
  Finding #2 completely: every one of make's own dangerous flags
  requires a leading `-`, and this tool has no legitimate use case for
  a flag-shaped target — real Makefile targets are plain names) and
  validates `directory` via `check_path_in_worktree()` (closes Finding
  #3, the standard chokepoint used since tool #9) — plus
  `run_make_handler(root, worktree_path, inp)`, a single shared
  implementation.
- Since both real call sites had byte-identical logic once
  `chat_agent.py`'s shell=True layer was removed (see below), they are
  now unified into the one shared handler — matching the
  `run_python_snippet`/`replace_class`/`rename_file` precedent for
  tools where the two real implementations had no genuine behavioral
  difference worth preserving separately (unlike, e.g., `docker_build`,
  where 3 real implementations have genuinely different output
  formatting and only the validator is shared).
- **`app/agents/chat_agent.py`**: `run_make` dispatch no longer builds
  a shell string or calls `_run_subprocess` at all — it now calls the
  shared `run_make_handler()` via `asyncio.to_thread`, closing Finding
  #1 by removing the shell layer entirely rather than trying to
  `shlex.quote()` around it.
- **`app/agents/tools.py`**: `run_make` handler now delegates to the
  same shared function.

## Tests (real, not mocked — every test runs a genuine `make` subprocess
against a real temporary Makefile)

`tests/test_run_make_hardening.py` (new, 22 tests):

- Schema shape check.
- `validate_run_make_inputs()`: allows a plain target + no/relative
  directory; rejects 6 different flag-shaped targets (`-n`, `-C/tmp`,
  `-f/etc/passwd`, `--eval=...`, `--`, `-`); rejects an absolute
  outside-repo directory and a `../` traversal.
- **All three proven findings, verified closed on both real dispatch
  paths where applicable**: shell-metacharacter injection (Finding #1,
  `chat_agent.py` only — the exact payload that created a real marker
  file before the fix), `--eval` flag-injection (Finding #2, both real
  call sites), directory escape running a real outside-repo Makefile
  target (Finding #3, both real call sites).
- Regression: a legitimate target still runs and returns real output on
  both call sites, target-listing with no `target` still works, a
  legitimate relative `directory` still works, no-Makefile still errors
  cleanly, `run_make` appears exactly once in `CHAT_TOOLS`.

Also re-ran `tests/test_chat_tools.py::TestRunMake` (its 3 pre-existing
tests use only plain, non-flag-shaped targets and no `directory` field
— confirmed unaffected) and the full `test_chat_tools.py` file (132
passed).

## Regression

Full suite: **5342 passed, 52 skipped, 18 deselected, 0 failed** (up
from 5320 before this tool).

## Final verdict

**GREEN FLAG.**

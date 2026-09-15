# Tool #176 — `read_output` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

TWO real implementations, both already dispatched: `read_output_h`
inside `make_chat_handlers()`, AND `chat_agent.py`'s own separate
`if tool_name == "read_output":` dispatch body. Both already
delegated to the same shared `app.fleet.process_manager.read_output()`
for the actual stdout/stderr reading — no injection surface there,
`pid` is only ever used as a dict key into the caller's own
per-session tracked-process map, never reaches a subprocess or shell.
Same "duplicate implementation, core logic already shared and safe"
shape as tool #162's `list_background_processes`.

Existing tests referencing this tool: `tests/test_day1_tools.py` (2
tests) and `tests/test_audit_q_batch01_execution_terminal_fixes.py`
(5 tests, testing `process_manager.read_output()` directly) —
confirmed via grep and re-run.

## Problems found

One real finding: **uncaught crash on malformed `pid`/`lines`
input**, same class as tools #70/#72/#76/#127/#130/#135. Both call
sites did their own `int(inp["pid"])` / `int(inp.get("lines", 50))`
conversion before calling the shared `process_manager.read_output()`
— with no `try`/`except` around either. Proved live on all 3 real
access paths:
- `read_output({})` (missing `pid`) → uncaught `KeyError('pid')`.
- `read_output({"pid": "not-a-number"})` → uncaught `ValueError`.
- `read_output({"pid": 12345, "lines": "bad"})` → uncaught
  `ValueError`.

Through `chat_agent.py`'s real graph-node call path these were caught
by its own outer generic `except Exception` (turning a crash into a
`"[ERROR] Tool read_output failed: ..."` result — the same mitigating
factor already documented for the `list_files` #68 finding), but
`make_chat_handlers()`'s handlers dict is consumed directly, with no
such outer wrapper, by 18+ one-shot agents (`mcp_developer_agent`,
`evaluation_agent`, `devex_agent`, etc., confirmed via grep) — for
those, an uncaught exception genuinely propagates.

## Changes made

New shared `read_output_handler()` in
`app/tools/execution/read_output.py` consolidates the pid/lines
parsing (previously duplicated identically at both call sites) into
one place: malformed `pid`/`lines` now returns a clean `[ERROR]`
message instead of raising, on both call sites. The underlying
`process_manager.read_output()` logic is unchanged (already safe).

`app/agents/tools.py`'s `_READ_OUTPUT_TOOL` now aliases the shared
`READ_OUTPUT_TOOL` constant, and `read_output_h` / `chat_agent.py`'s
dispatch both delegate to the new shared handler, each still passing
their own session-scoped `procs` dict (`_session_bg_procs` /
`self._background_processes` — legitimately separate per-caller
state, not consolidated). No external direct-importers of the old
names were found.

## Tests

New file `tests/test_read_output_hardening.py`, 10 tests: schema
check, duplicate-registration check, re-confirmation that missing
pid / non-numeric pid / non-numeric lines all now return a clean
`[ERROR]` on both real access paths (never raise), and
legitimate-usage regression (a real background process's real stdout
genuinely read back via both `make_chat_handlers()` and the
`chat_agent.py` dispatch, plus a clean error for an unknown/dead PID).

Existing tests (`tests/test_day1_tools.py`, 2 tests, and
`tests/test_audit_q_batch01_execution_terminal_fixes.py`, 5 tests)
re-run clean.

## Regression

This tool is tool 3 of the #174-#178 batch. Its own new hardening
tests (10/10 pass) plus the 7 pre-existing tests (7/7 pass) are the
per-tool verification gate; the full suite runs once the batch
completes.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
read_output.py` sweep (102 files clean), an `importlib`-reload sweep
over all `app.agents.*` modules (all clean), a `ruff check` on all
touched files (clean), a compile()-based source escape-sequence check
on the new module (clean), and a `CHAT_TOOLS.count("read_output") ==
1` check (clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding was proved live on both call
sites and closed; the shared, already-safe `process_manager.
read_output()` logic is unchanged; no functionality lost;
tool-specific regression tests clean (17/17 across new + swept
existing tests).

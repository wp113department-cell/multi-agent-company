# Tool #99 — `find_config` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three real implementations:

1. `chat_agent.py`'s own interactive dispatch (`shell=True` +
   `shlex.quote()`, 2 separate grep calls).
2. `find_config_h` inside `make_chat_handlers()` (3-variant retry loop
   — exact key, upper, lower).
3. `sec_find_config` (`make_security_reviewer_handlers`).

Per `tool_inventory.json`, 3 agents declare `find_config` in
`allowed_tools`. `CHAT_TOOLS.count("find_config") == 1` verified. 2
existing test files reference this tool — read in context, all
directly-exercising tests re-run and confirmed passing unchanged (4
tests).

## Problems found

**Finding #1 — the same flag-collision class already established for
tools #69/#89/#90/#91, on 2 of 3 implementations** (`find_config_h`
and `chat_agent.py`'s dispatch — `shlex.quote()` again only protects
the shell, not grep's own argv-level flag parser). `key` was a bare
positional argv element with no `--` separator. Proved live two ways:
`key="-f"` was silently consumed as grep's own `-f <file>` flag, which
then consumed the intended search DIRECTORY as its pattern-file
argument instead — `grep: <dir>: Is a directory`, zero real search,
a misleadingly-confident "not found" answer. WORSE: `key="--include=*"`
was consumed as grep's own `--include` flag, leaving grep with no
directory argument at all — it fell back to reading from stdin and
**hung until the timeout**, a real, reproduced resource-exhaustion
vector (`find_config_h`'s own 3-variant retry loop meant a single
malicious `key` could tie up a worker for up to 3x the per-call
timeout).

**Finding #2 — a real, severe functionality bug: `sec_find_config`
ignores the `key` field ENTIRELY.** It reads a nonexistent
`file_pattern` field (never in the schema) and runs a FIXED, hardcoded
regex (`host|port|database|db_url|dsn|connection_string`). Proved
live: `find_config({"key": "API_KEY"})` through this implementation
never even attempts to search for "API_KEY" — every real,
schema-conformant call silently returns results for an unrelated
pattern instead. Same "dead/wrong field read" class already
established for tools #24/#82/#90.

## Changes made

Extracted a shared `find_config_handler()` in
`app/tools/filesystem/find_config.py` with `validate_find_config_key()`
(rejects any `key` starting with `-`, matching the
`find_sql`/`find_api`/`find_route` precedent). Adopted by all three
real call sites. As a genuine architectural improvement (not just a
security patch): the previous 3-variant case retry loop is collapsed
into a single `-i` (case-insensitive) grep call — this closes the
up-to-3x-timeout hang surface structurally, not just by rejecting the
payload, and is simpler and faster for legitimate calls too.
`sec_find_config` is fully replaced by the shared handler (adopting
the correct, working behavior rather than kept as a second, broken
implementation), reusing the fuller include-glob list already used by
`find_config_h`/`chat_agent.py`.

## Tests

New file `tests/test_find_config_hardening.py`, 17 tests, all real (no
mocking) — schema check, duplicate-registration check, 3 pure
validator unit tests, flag-collision rejection on the interactive
dispatch AND both handler factories (parametrized), a timed proof the
`--include=*` hang is closed (rejects in well under 3s instead of
hanging until timeout), a real proof `sec_find_config` now genuinely
searches for the requested key (and no longer returns unrelated
hardcoded-pattern matches), and legitimate-usage regression (a real
found key, case-insensitive match, clean not-found reporting) across
all three real access paths. Existing tests
(`test_day1_tools.py::TestFindConfig`) re-run and confirmed passing
unchanged (4 tests).

## Regression

Per the established once-per-5-tool-batch cadence, the full suite will
run once this new batch (#99-#103) completes — see
`feedback_tool_enhance_batch_full_suite` memory. This tool (#99) is
tool 1 of the new batch; its own new hardening tests (17/17 pass) and
directly-referencing existing tests (4/4 pass) are the per-tool
verification gate.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
find_config.py` sweep (98 files clean), an `importlib.import_module()`
sweep over all 97 `app/agents/` modules (all clean), a `ruff check` on
all 3 touched files (clean), and a `python -W error` docstring
escape-sequence check on the new module (clean) — BEFORE claiming
GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed across all
three real implementations — including a real DoS/hang vector, timed
and confirmed fixed, and a severe functionality bug where a whole
implementation silently ignored its own required field; the fix also
removes redundant subprocess calls rather than adding complexity; no
functionality lost; tool-specific and directly-referencing regression
tests clean. Full-suite confirmation pending as part of the #99-#103
batch.

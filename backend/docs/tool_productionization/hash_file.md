# Tool #154 — `hash_file` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `hash_file_h` inside `make_chat_handlers()`.

`hash_file` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

Existing tests referencing this tool: `tests/test_new_tools.py`'s
`test_hash_file` (1 test) — confirmed via grep and re-run.

## Problems found

Two real, empirically-verified findings.

**Finding #1 — a worktree-boundary escape that is a genuine SHA-256
HASH DISCLOSURE oracle.** `hash_file_h` built `root / path` without
ever validating it stayed inside the worktree — the same `pathlib`-
silently-discards-`root`-for-an-absolute-right-operand class already
documented for tools
#99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144/#146.
Proved live: `hash_file({"path": "/tmp/<outside file>"})` genuinely
computed and returned the real SHA-256 hash of a file entirely
outside the intended worktree, confirmed against the file's real
hash via an independent `sha256sum`. A hash is a real
content-verification oracle: it lets a caller confirm or refute a
guess about an outside file's exact content without ever reading the
content directly, and lets a caller fingerprint outside files for
further reconnaissance.

**Finding #2 — advertised but never dispatched on the interactive
chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153.**
`hash_file` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: hash_file"`.

## Changes made

New shared `hash_file_handler()` in `app/tools/filesystem/hash_file.py`:
`path` is now validated with `check_path_in_worktree()` (checked for
both relative traversal and absolute-path escapes) before the file is
ever opened, closing finding #1. A new `chat_agent.py` dispatch branch
delegates to this same shared handler, closing finding #2 —
`hash_file` is now genuinely reachable from interactive chat for the
first time.

`app/agents/tools.py`'s `_HASH_FILE_TOOL` now aliases the shared
`HASH_FILE_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_hash_file_hardening.py`, 10 tests: schema check,
duplicate-registration check, worktree-escape-blocked proof (absolute
and relative traversal, across the direct handler, `make_chat_handlers`,
and the new `chat_agent.py` dispatch) with an assertion the outside
file's real hash never leaks into the result, a proof the new
dispatch no longer returns "Unknown tool", and legitimate-usage
regression (real SHA-256 hash verified against Python's own
`hashlib`, missing-file error).

Existing test (`tests/test_new_tools.py::test_hash_file`, 1 test)
re-run clean.

## Regression

This tool is tool 1 of a new #154-#158 batch. Its own new hardening
tests (10/10 pass) plus the 1 pre-existing test (1/1 pass) are the
per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
hash_file.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), a
`python -W error` docstring escape-sequence check on the new module
(clean), and a `CHAT_TOOLS.count("hash_file") == 1` check (clean) —
BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed; the tool
is now genuinely reachable from interactive chat for the first time —
a strict capability increase, not a narrowing; no functionality lost;
tool-specific regression tests clean (11/11 across new + swept
existing tests).

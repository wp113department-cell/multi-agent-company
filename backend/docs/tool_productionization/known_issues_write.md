# Tool #161 — `known_issues_write` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `known_issues_write_h` inside
`make_chat_handlers()`.

`issue` and `severity` are free-text fields appended into a markdown
log file, but the destination path itself (shared with sibling tool
#160's `known_issues_read`, via `known_issues_path()`) is derived
deterministically from `repo_path` alone, never from either input
field — no worktree-boundary-escape or path-injection surface exists,
checked directly. `severity`/`issue` reach `embed_bug_sync()` →
`embed_bug()`, which uses SQLAlchemy ORM parameter binding (not raw
string-formatted SQL) — no injection surface there either, confirmed
by direct code inspection of already-audited, pre-existing shared
memory infrastructure.

`known_issues_write` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see the finding
below.

Existing tests referencing this tool: `tests/
test_batch15_tool_handlers.py`'s 3 `known_issues_write` tests —
confirmed via grep and re-run.

## Problems found

One real, empirically-verified finding.

**Advertised but never dispatched on the interactive chat agent, same
class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160.**
`known_issues_write` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: known_issues_write"`.

## Changes made

New shared `known_issues_write_handler()` in `app/tools/agents/
known_issues_write.py`, containing the unchanged append/embed logic.
The original's cross-platform advisory file lock (`msvcrt.locking()`
on Windows, `fcntl.flock()` everywhere else) is preserved unchanged —
a first draft of this module hardcoded a bare `import fcntl`, which
would have crashed on import on Windows; caught before finalizing by
re-reading the original's own platform branch, not by any test
failure. A new `chat_agent.py` dispatch branch delegates to the shared
handler, closing the finding — `known_issues_write` is now genuinely
reachable from interactive chat for the first time.

`app/agents/tools.py`'s `_KNOWN_ISSUES_WRITE_TOOL` now aliases the
shared `KNOWN_ISSUES_WRITE_TOOL` constant. The now-dead
`_mem_issues_path` variable (only ever used by this tool's old
closure) was also removed, matching the "no dead code" standard
already applied on tool #159's turn.

## Tests

New file `tests/test_known_issues_write_hardening.py`, 8 tests: schema
check, duplicate-registration check, a proof the new dispatch no
longer returns "Unknown tool", and legitimate-usage regression (real
appends verified via round-trip read-back on all 3 real access paths,
multiple writes append rather than overwrite, default severity).

Existing tests (3 in `tests/test_batch15_tool_handlers.py`, plus its 2
unrelated `record_preference` tests in the same file) re-run clean.
Sibling `known_issues_read`'s tests also re-run clean, confirming the
shared `_mem_lock`/`_mem_unlock` helpers (used by other memory tools
too) were unaffected by removing the now-dead `_mem_issues_path`.

## Regression

This tool is tool 3 of the #159-#163 batch. Its own new hardening
tests (8/8 pass) plus the 6 pre-existing tests in the same file (6/6
pass) are the per-tool verification gate; the full suite runs once the
batch completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/agents/
known_issues_write.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), a
`python -W error` docstring escape-sequence check on the new module
(clean), and a `CHAT_TOOLS.count("known_issues_write") == 1` check
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding was proved live and closed; the
tool is now genuinely reachable from interactive chat for the first
time — a strict capability increase, not a narrowing; the
cross-platform file lock was preserved correctly (caught a self-
introduced portability regression before it shipped); no functionality
lost; tool-specific regression tests clean (14/14 across new + swept
existing tests).

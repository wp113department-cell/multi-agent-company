# Tool #167 — `memory_read` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `memory_read_h` inside `make_chat_handlers()`.

`key` reaches only a pure in-memory dict lookup (`store.get(key)`)
against a JSON store loaded from a FIXED, deterministic path (an md5
slug of `repo_path` alone, never influenced by `key`) — no
worktree-boundary-escape or injection surface exists here at all,
checked directly.

`memory_read` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see the finding
below.

Existing tests referencing this tool: `tests/
test_memory_write_hardening.py` (which exercises `memory_read` as
part of verifying sibling tool #51's own concurrency fix, including a
20-concurrent-thread stress test) and `tests/
test_fleet_tool_manifest.py`'s manifest-coverage check — confirmed via
grep and re-run.

## Problems found

One real, empirically-verified finding.

**Advertised but never dispatched on the interactive chat agent, same
class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166.**
`memory_read` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: memory_read"`.

## Changes made

New shared `memory_read_handler()` in `app/tools/agents/memory_read.py`,
reusing sibling tool #51's `app.tools.agents.memory_write.
memory_store_path()` directly rather than re-deriving the per-repo
memory-store path a third time — matching the established DRY
precedent from tools #159's `json_validate`/`yaml_validate` and
#160/#161's shared `known_issues_path()`. A new `chat_agent.py`
dispatch branch delegates to the shared handler, closing the finding —
`memory_read` is now genuinely reachable from interactive chat for the
first time.

**Incidental cleanup**: removing `memory_read_h`'s old body also
removed the last real caller of `_read_mem_store()`/
`_write_mem_store()` inside `make_chat_handlers()`'s closure — both
were fully dead code, since `memory_write_h` and `decision_log_append_h`
already delegate to their own shared modules (tools #51 and #133).
Confirmed via grep before removing: zero remaining references to
`_read_mem_store`, `_write_mem_store`, `_mem_store_path`,
`_mem_lock`/`_mem_unlock` (the cross-platform advisory file lock),
`_json_mem`, or `_mem_decisions_path` anywhere else in
`app/agents/tools.py`. `app/agents/tools.py`'s `_MEMORY_READ_TOOL` now
aliases the shared `MEMORY_READ_TOOL` constant.

## Tests

New file `tests/test_memory_read_hardening.py`, 8 tests: schema check,
duplicate-registration check, a proof the new dispatch no longer
returns "Unknown tool", and legitimate-usage regression (missing key,
real value round-trip, cross-path write-then-read consistency,
different-repo isolation).

Existing tests re-run clean: `tests/test_memory_write_hardening.py`'s
full 7-test suite (including the 20-concurrent-thread stress test),
confirming the incidental dead-code cleanup did not disturb
`memory_write`'s own hard-won concurrency fix; `tests/
test_fleet_tool_manifest.py`'s 49 tests; `tests/
test_decision_log_append_hardening.py`'s 7 tests re-run as an extra
regression check since that tool shares the same code region the dead
code was removed from.

## Regression

This tool is tool 4 of the #164-#168 batch. Its own new hardening
tests (8/8 pass) plus 63 pre-existing tests across 3 test files (63/63
pass) are the per-tool verification gate; the full suite runs once the
batch completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/agents/memory_read.py`
sweep (102 files clean), an `importlib.import_module()` sweep over all
`app/agents/` modules (all clean), a `ruff check` on all touched files
(clean — including catching the `F821 Undefined name
memory_read_handler` this cleanup introduced mid-edit, fixed by
completing the import wiring before finishing), a `python -W error`
docstring escape-sequence check on the new module (clean), and
`CHAT_TOOLS.count("memory_read") == 1` / `count("memory_write") == 1`
/ `count("decision_log_append") == 1` checks (all clean) — BEFORE
claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding was proved live and closed; the
tool is now genuinely reachable from interactive chat for the first
time — a strict capability increase, not a narrowing; a substantial
incidental dead-code cleanup (5 names orphaned since tools #51/#133)
was completed and verified not to disturb sibling tools' own
regression tests, including a 20-thread concurrency stress test; no
functionality lost; tool-specific regression tests clean (71/71
across new + swept existing tests).

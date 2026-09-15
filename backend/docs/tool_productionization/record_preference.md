# Tool #178 — `record_preference` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `make_record_preference_handler()`, a
factory function living directly in `app/agents/tools.py` (not yet
modularized). Its ONE real caller is `make_chat_handlers()` itself —
confirmed via grep: unlike sibling tool #66's `record_learning`
(called by ~80 one-shot agent modules), no other agent module
references this factory at all. `record_preference` IS in
`CHAT_TOOLS` (confirmed), but `chat_agent.py`'s `_execute_tool()` had
zero dispatch branch for it — see finding.

Existing tests referencing this tool:
`tests/test_batch15_tool_handlers.py` (3 tests) — confirmed via grep
and re-run.

## Audit of injection surface (checked, no issue found)

Same audit shape as sibling tool #66's `record_learning`.
`preference`/`scope` reach `embed_preference_sync()` as plain string
content, inserted through the ORM (`MemoryEmbedding`), never
string-interpolated into raw SQL or a shell command; there is no
filesystem path or network destination anywhere in this tool's input
schema, so there is no worktree-escape or SSRF surface either. The
sync/async bridge (`embed_preference_sync` in `app/memory/store.py`)
already uses `new_isolated_async_engine()` + its own `asyncio.run()`,
matching this initiative's own established "never `asyncio.run()`
against the shared `app.db.session` engine from sync code" rule —
already correct, not a violation. Proved live against the real DB: a
real `preference` was genuinely persisted (`"Recorded."`) and an
empty `preference` was cleanly rejected
(`"[ERROR] preference is required."`).

## Problems found

One real finding.

**Advertised but never dispatched on the interactive chat agent, same
class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168/#169/#170/#171/#172/#173/#174/#175/#176/#177.**
`record_preference` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: record_preference"`. This finding is notably more
consequential than the average "missing dispatch" instance in this
initiative: this tool's own module docstring explicitly states chat
is "the direct human-facing conversational surface where a preference
is naturally stated ('always use f-strings', 'prefer pytest
fixtures')" — so the tool had never actually been reachable from the
ONE surface it was designed for.

## Changes made

Extracted into `app/tools/agents/record_preference.py`
(`RECORD_PREFERENCE_TOOL`, `make_record_preference_handler()`), moved
verbatim (no logic change — already safe). `app/agents/tools.py` now
imports and self-re-exports both names (`as`-aliased, matching
record_learning's established pattern for mypy's explicitly-exported
check), with its own `make_chat_handlers()` call site unchanged. A
new `chat_agent.py` dispatch branch delegates to the shared
`make_record_preference_handler()` — `record_preference` is now
genuinely reachable from interactive chat for the first time.

## Tests

New file `tests/test_record_preference_hardening.py`, 9 tests: schema
check, duplicate-registration check, re-confirmation that empty/
missing `preference` is cleanly rejected (audit re-verification), a
proof the new dispatch no longer returns "Unknown tool" and correctly
rejects empty preferences, and legitimate-usage regression (real DB
writes on both access paths, default-scope behavior) — all requiring
real DB connectivity (`pytestmark = pytest.mark.skipif(not
get_settings().database_url, ...)`, matching this initiative's
established pattern for DB-backed tools).

Existing tests (`tests/test_batch15_tool_handlers.py`, 3 tests)
re-run clean.

## Regression

This tool is tool 5 of the #174-#178 batch — **BATCH COMPLETE**. Its
own new hardening tests (9/9 pass) plus the 3 pre-existing tests
(3/3 pass) are the per-tool verification gate; the full batch suite
runs next.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/agents/
record_preference.py` sweep (102 files clean), an `importlib`-reload
sweep over all `app.agents.*` modules (all clean), a `ruff check` on
all touched files (clean), a compile()-based source escape-sequence
check on the new module (clean), and a
`CHAT_TOOLS.count("record_preference") == 1` check (clean) — BEFORE
claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding was proved live and closed; the
tool is now genuinely reachable from interactive chat for the first
time — the one surface it was designed for — a strict capability
increase, not a narrowing; no functionality lost; tool-specific
regression tests clean (12/12 across new + swept existing tests).

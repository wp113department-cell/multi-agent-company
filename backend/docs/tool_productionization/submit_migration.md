# Tool #188 — `submit_migration` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `mg_submit` inside
`make_migration_agent_handlers()`. Exactly 1 real agent declares this
tool per `tool_inventory.json`: `migration_agent`
(`app/agents/migration_agent.py`). Deliberately NOT in `CHAT_TOOLS` —
confirmed via membership check (count is 0) — same correct-and-
intentional absence already established for sibling tools
#66/#180-#186.

`make_migration_agent_handlers()`'s other handlers (`run_sql`,
`inspect_schema`, `write_file`, `bash`) are each their own separately-
productionized concern (`run_sql`/`inspect_schema` already reference
tool #96's shared fix) — deliberately untouched here, out of scope for
this tool's own turn.

Existing tests referencing this tool:
`tests/test_day3_agents.py::TestMigrationAgentTools` and
`::TestMigrationAgentHandlers` — assert only tool-list membership and
handler-key presence, neither references the internal
`_migration_result` dict, so no fix was required there (same shape as
tool #184).

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`migration_file` is a free-form
string describing a path already written via the agent's own
separately gated `write_file` handler before this tool is ever
called; `is_reversible`/`summary`/`warnings` are plain
booleans/strings) — no injection surface.

## Problems found

One real finding, same class and shape as sibling tools #180-#186:
**dead-code accumulator, never actually read.** `mg_submit`'s original
body did `migration_result.update(inp)`, and the factory separately
exported `handlers["_migration_result"] = migration_result` — but
grepping the entire production codebase found zero real readers.
Traced the actual, working result-capture mechanism: it lives entirely
in `app/agents/base_graph.py`'s generic tool-execution node
(`tool_name.startswith("submit_")` → captures `dict(tu_input)`
directly into `state["result"]`), confirmed by reading
`migration_agent.py`'s own `raw = final_state["result"]` line — that
is what real production code actually consumes, completely
independent of `migration_result`/`_migration_result`.

## Changes made

Extracted into `app/tools/agents/submit_migration.py`
(`SUBMIT_MIGRATION_TOOL`, `submit_migration_handler`). The dead
`migration_result` dict and `handlers["_migration_result"]` export are
removed entirely — `submit_migration_handler()` now does exactly what
the real, functioning mechanism actually needs: return the same
confirmation string as before (`"Migration submitted"`), with zero
behavior change to the tool's real end-to-end effect. All other
`make_migration_agent_handlers()` handlers left byte-for-byte
unchanged.

## Tests

No existing test required a fix (verified: neither
`TestMigrationAgentTools` nor `TestMigrationAgentHandlers` reads
`_migration_result`). All 102 tests across
`tests/test_submit_migration_hardening.py` +
`tests/test_day3_agents.py` pass.

New file `tests/test_submit_migration_hardening.py`, 9 tests: schema
check, duplicate-registration check (in `MIGRATION_AGENT_TOOLS`),
confirmation it is correctly absent from `CHAT_TOOLS`,
re-confirmation `_migration_result` is no longer exported, and
legitimate-usage regression (identical confirmation string returned
regardless of input shape, repeated calls don't accumulate or leak
state, sibling handlers unaffected).

## Regression

This tool is tool 5 of the #184-#188 batch — **BATCH COMPLETE**. Its
own new hardening tests (9/9 pass) plus the unaffected 93 existing
`tests/test_day3_agents.py` tests are the per-tool verification gate;
the full batch suite runs next.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.migration_agent` and `app.agents.tools` (both clean), a
`ruff check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_new_tools.py` + `tests/test_final_session.py` tool-count
regression tests (61/61 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding (dead-code state) was identified
and removed with zero change to the tool's real, working end-to-end
behavior; no functionality lost (no existing test needed to change);
tool-specific regression tests clean (102/102 across new + existing
tests). Agent alignment verified: PASS (`migration_agent.py`'s real
`raw = final_state["result"]` consumption path is unaffected by the
removal of the dead accumulator).

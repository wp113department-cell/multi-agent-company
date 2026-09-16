# Tool #187 — `submit_health_report` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: the `submit_health_report` closure inside
`make_devops_handlers()`. Exactly 1 real agent declares this tool per
`tool_inventory.json`: `devops` (`app/agents/devops.py`, via
`run_devops()`). Deliberately NOT in `CHAT_TOOLS` — confirmed via
membership check (count is 0) — a batch agent, never exposed to
interactive chat.

**Important difference from sibling tools #180-#186**: this is NOT a
dead accumulator. `run_devops()` does not use `run_agent_graph`'s
generic `final_state["result"]` submit_* capture mechanism at all for
this agent — instead it reads `handlers.get("_health_result", {})`
directly (confirmed by reading the full function body), and builds its
returned `HealthReport` dataclass entirely from that dict's
`status`/`checks`/`summary` keys, with an explicit "Agent spoke but
never called submit_health_report" fallback path when it's empty. This
is a real, live, genuinely necessary result sink — the opposite of
tools #180-#186's finding class.

Existing tests referencing this tool: `tests/test_devops_agent.py`
(asserts `handlers["_health_result"]["status"]` after a real call —
already correct, matching real behavior) and
`tests/test_session3_migration.py` (patches `make_devops_handlers` to
return `{"_health_result": ...}` and verifies `run_devops()`'s
consumption of it — already correct). Neither required a change.

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`status` is an enum, `checks` is
free-form structured data, `summary` is a string) — no injection
surface. `status`/`checks[].status` are real JSON Schema enums
enforced by the calling LLM API's tool-use validation, consistent with
every other enum-typed submit_* schema in this codebase (e.g.
`submit_arch_review`'s `severity` enum) — not a new gap.

## Problems found

None. No security vulnerability and no functional bug found in the one
real implementation.

## Changes made

Modularized purely for consistency with the already-established
`make_submit_docs_handler`/`docs_result` pattern (tool #85): extracted
into `app/tools/agents/submit_health_report.py`
(`SUBMIT_HEALTH_REPORT_TOOL`, `make_submit_health_report_handler`).
The factory takes the externally-owned `health_result` dict (still
created and exported by `make_devops_handlers()` exactly as before)
rather than owning it itself — preserving the exact existing contract
`run_devops()` relies on. The shared `bash` closure in the same
factory function is untouched, out of scope for this tool's own turn
(tracked separately per `app/tools/execution/bash.py`'s own migration
note about the 10 bundled bash variants).

## Tests

No existing test required a fix — both `test_devops_agent.py` and
`test_session3_migration.py` already assert on real,
correctly-preserved behavior (`handlers["_health_result"]`).

New file `tests/test_submit_health_report_hardening.py`, 10 tests:
schema check, duplicate-registration check (in `DEVOPS_TOOLS`),
confirmation it is correctly absent from `CHAT_TOOLS`, and — unlike
the dead-accumulator siblings — direct proof the factory mutates the
exact dict object it was given (not a copy), that
`make_devops_handlers()` exports that same object, that repeated calls
accumulate via `update()` exactly as before, and that independent
handler instances don't share state.

## Regression

This tool is tool 4 of the #184-#188 batch. Its own new hardening
tests (10/10 pass) plus the unaffected 94 total tests across
`test_devops_agent.py` + `test_session3_migration.py` are the per-tool
verification gate; the full batch suite runs after tool #188.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.devops` and `app.agents.tools` (both clean), a `ruff
check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_new_tools.py` + `tests/test_final_session.py` tool-count
regression tests (61/61 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** No security or functional defect found; the tool was
already correctly wired and genuinely consumed by its one real caller.
Modularized for structural consistency only, with zero behavior
change and zero existing test needing a fix. Tool-specific regression
tests clean (94/94). Agent alignment verified: PASS
(`devops.py`'s real `handlers.get("_health_result", {})` consumption
path is unaffected — the factory still mutates the same dict object
`make_devops_handlers()` exports).

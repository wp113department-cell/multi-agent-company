# Tool #191 — `submit_qa_result` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: the `submit_qa_result` closure inside
`make_qa_handlers()`. Exactly 1 real agent declares this tool per
`tool_inventory.json`: `qa` (`app/agents/qa.py`, via `run_qa()`).
Deliberately NOT in `CHAT_TOOLS` — confirmed via membership check
(count is 0) — a batch agent, never exposed to interactive chat.

**Important difference from sibling tools #180-#186/#188-#190, same
class as tool #187's `submit_health_report`**: this is NOT a dead
accumulator. `run_qa()` does not use `run_agent_graph`'s generic
`final_state["result"]` submit_* capture mechanism at all for this
agent — instead it reads `handlers.get("_qa_result", {})` directly on
BOTH its normal success path AND its turn-limit-exhausted
retry-giveup path (confirmed by reading the full function body,
including the outer `for attempt in range(max_retries)` retry loop
that salvages a partial `_qa_result` even when the agent never
finished within a turn). This is a real, live, genuinely necessary
result sink.

Existing tests referencing this tool: `tests/test_session3_migration.py`
(patches `make_qa_handlers` to return `{"_qa_result": ...}` and
verifies `run_qa()`'s consumption of it on both success and
empty-result paths — already correct), `tests/test_tool_scoping.py`
(tool-name membership in `QA_TOOLS`, unaffected), and
`tests/test_fleet_tool_manifest.py` (manifest entry name, unaffected).
None required a change.

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`status` is an enum,
`tests_run`/`tests_passed`/`tests_failed` are integers,
`typecheck_clean`/`lint_clean` are booleans, `errors` is a string
array, `summary` is a string — all self-reported structured data from
checks the agent already ran via its own separately gated `bash`
handler) — no injection surface.

## Problems found

None. No security vulnerability and no functional bug found in the one
real implementation.

## Changes made

Modularized purely for consistency with the already-established
`make_submit_docs_handler`/`make_submit_health_report_handler` pattern
(tools #85/#187): extracted into
`app/tools/agents/submit_qa_result.py` (`SUBMIT_QA_RESULT_TOOL`,
`make_submit_qa_result_handler`). The factory takes the
externally-owned `qa_result` dict (still created and exported by
`make_qa_handlers()` exactly as before) rather than owning it itself —
preserving the exact existing contract `run_qa()` relies on, on both
its success and retry-giveup paths. The shared `bash` closure in the
same factory function is untouched, out of scope for this tool's own
turn.

## Tests

No existing test required a fix — `test_session3_migration.py`,
`test_tool_scoping.py`, and `test_fleet_tool_manifest.py` all already
assert on real, correctly-preserved behavior.

New file `tests/test_submit_qa_result_hardening.py`, 11 tests: schema
check, duplicate-registration check (in `QA_TOOLS`), confirmation it
is correctly absent from `CHAT_TOOLS`, and — unlike the
dead-accumulator siblings — direct proof the factory mutates the exact
dict object it was given (not a copy), that `make_qa_handlers()`
exports that same object, that repeated calls accumulate via
`update()` exactly as before, and that independent handler instances
don't share state.

## Regression

This tool is tool 3 of the #189-#193 batch. Its own new hardening
tests (11/11 pass) plus the unaffected 152 total tests across
`test_session3_migration.py` + `test_tool_scoping.py` +
`test_fleet_tool_manifest.py` are the per-tool verification gate; the
full batch suite runs after tool #193.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.qa` and `app.agents.tools` (both clean), a `ruff check` on
all touched files (clean), a `CHAT_TOOLS` duplicate-registration check
(clean), and `tests/test_new_tools.py` + `tests/test_final_session.py`
tool-count regression tests (61/61 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** No security or functional defect found; the tool was
already correctly wired and genuinely consumed by its one real caller
on both its success and retry-giveup paths. Modularized for structural
consistency only, with zero behavior change and zero existing test
needing a fix. Tool-specific regression tests clean (152/152). Agent
alignment verified: PASS (`qa.py`'s real
`handlers.get("_qa_result", {})` consumption path is unaffected — the
factory still mutates the same dict object `make_qa_handlers()`
exports).

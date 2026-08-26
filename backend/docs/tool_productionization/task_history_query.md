# Tool #118 — `task_history_query` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: a single `task_history_query(inp)` function
in `app/agents/tools.py`, reused directly by:

1. `app/agents/agent_advisor.py` — imports the function itself by name
   and assigns it straight into its own handlers dict (confirmed by
   reading that call site directly, not assumed from the import
   count).
2. `task_history_query_h = task_history_query` inside
   `make_chat_handlers()` — reused by every one-shot batch agent built
   on that factory.

`task_history_query` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #3.

No existing tests reference this tool at all (confirmed by grep, no
sweep needed).

## Problems found

Three real, empirically-verified findings.

**Finding #1 (most severe) — the tool was completely non-functional;
every real call failed.** The query was `SELECT id, status, created_at
FROM task_logs ...`, but the real `task_logs` table
(`app/db/models.py::TaskLog`) has no `status` column at all — its
actual columns are `id`, `task_id`, `category`, `message`,
`extra_data`, `rationale`, `created_at`, `archived`, `archived_at`.
Proved live against the real project database: executing the exact
query this tool constructs raised `psycopg2.errors.UndefinedColumn:
column "status" does not exist`. The `status` values the tool's own
schema documents ("completed, failed, blocked") are `dev_tasks.status`
(`app/db/models.py::DevTask`) values — proved live that `SELECT id,
status, created_at FROM dev_tasks` is the query that was actually
intended, and it genuinely works and returns real task rows.

**Finding #2 — a genuine, live SQL injection, same class as tools
#15/#96, on the corrected query.** `status` was directly
f-string-interpolated into the raw SQL string, then handed to `psql
-c` as a single argv element (identical multi-statement-per-call
wire-protocol behavior already documented for tool #96's
`inspect_schema`). Proved directly against the real project database:
`status = "x'; SELECT 'INJECTED_MARKER_TASK_HISTORY' AS proof; --"`
produced a query that, executed verbatim, genuinely returned the
injected marker as a second, separate result. (This host has no
`psql` binary at all — same environment note as tool #96 — so the
tool's own `subprocess.run(["psql", ...])` call always raised
`FileNotFoundError` before finding #1 could even surface on this
particular host; the injection was reproduced by executing the
identical constructed string over a real `psycopg2` connection
instead, per tool #96's established methodology.)

**Finding #3 — advertised but never dispatched on the interactive chat
agent, same class as tools #100/#103/#110/#112.** `task_history_query`
is in `CHAT_TOOLS` and registered in `make_chat_handlers()`'s handlers
dict, but `chat_agent.py`'s `_execute_tool()` had no dispatch branch —
every real interactive-chat call fell through to `"[ERROR] Unknown
tool: task_history_query"`.

## Changes made

New shared `task_history_query()` in
`app/tools/database/task_history_query.py` (function name kept
verbatim, not renamed to `*_handler`, because `agent_advisor.py`
imports and assigns the function itself directly):
- Queries `dev_tasks` instead of `task_logs`, closing finding #1.
- Real `psycopg2` parameter binding for both `status` and `limit` —
  neither is ever string-interpolated into SQL text, closing finding
  #2, and dropping the `psql` subprocess call entirely (a side-effect
  fix for the "no `psql` binary" robustness gap on this host).
- `limit` is clamped to `[1, 200]`.
- A new `chat_agent.py` dispatch branch delegating to this same shared
  function, closing finding #3 — `task_history_query` is now genuinely
  reachable from interactive chat for the first time.

`app/agents/tools.py` re-exports the function and schema unchanged
(`task_history_query as task_history_query` self-re-export — required
for `mypy`'s "explicitly exported" check to follow through to
`agent_advisor.py`'s direct import, caught by the comprehensive
`mypy` sweep). The schema's own description was corrected from
"Query recent task history from the task_logs table" to "Query recent
task history (id, status, created_at) from dev_tasks" to match reality.

## Tests

New file `tests/test_task_history_query_hardening.py`, 13 tests:
schema check, duplicate-registration check, a real proof the corrected
table query succeeds (finding #1), SQL-injection-blocked proof on the
direct function call, `make_chat_handlers()`, and the new
`chat_agent.py` dispatch (finding #2), a proof the new dispatch no
longer returns "Unknown tool" (finding #3), and legitimate-usage
regression (real rows, `limit` honored, `status` filter honored)
across all three real access paths. Skipped without a real
`DATABASE_URL`, matching tools #15/#96's precedent.

Zero existing tests referenced this tool — confirmed via grep, no
sweep needed.

## Regression

This tool is tool 5 of the #114-#118 batch, completing it. Its own new
hardening tests (13/13 pass) are the per-tool verification gate; the
full suite runs now that the batch is complete, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/database/
task_history_query.py` sweep (98 files clean, after fixing one
`attr-defined` error caught by the sweep — `agent_advisor.py`'s direct
import of `task_history_query` required the `as`-aliased
self-re-export pattern), an `importlib.import_module()` sweep over all
`app/agents/` modules (all clean), a `ruff check` on all touched files
(clean), and a `python -W error` docstring escape-sequence check on
the new module (clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** All three real findings proved live and closed; the
tool went from completely non-functional (every real call errored) to
genuinely working, injection-free, and reachable from interactive chat
for the first time — a strict capability increase, not a narrowing;
`agent_advisor.py`'s real integration re-verified working; no
functionality lost.

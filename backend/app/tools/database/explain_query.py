"""explain_query tool — tool_enhance.md productionization pass, tool
#98 (2026-08-25).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: explain_query
Old path: app/agents/tools.py (`_EXPLAIN_QUERY_TOOL` schema dict) with
    FOUR real implementations, all building an `EXPLAIN ANALYZE
    <query>` string by directly f-string-interpolating the
    LLM-controlled `query` field and shelling out to the `psql` CLI:
    `sq_explain_query` (`make_sql_agent_handlers`), `pr_explain_query`
    (`make_performance_reviewer_handlers`), `explain_query_h` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch (also `shell=True`, `shlex.quote()`'d — see
    note below on why that did not help).
New path: app/tools/database/explain_query.py (this file) —
    `EXPLAIN_QUERY_TOOL`, `explain_query_handler`. ALL FOUR real call
    sites now delegate to this one shared handler, which no longer
    shells out to `psql` at all — same design direction as tools #15
    (`run_sql`) and #96 (`inspect_schema`).
Affected agents: per tool_inventory.json, 4 agents declare
    `explain_query` in `allowed_tools`.
Affected modules: app/agents/tools.py (both of its own closures
    delegate to the shared handler), app/agents/chat_agent.py (its
    dispatch now calls the same shared handler, dropping its
    `_run_subprocess`/`shell=True` psql invocation entirely).
Affected registries: none — app/fleet/tool_manifest.py's
    "explain_query" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the three handler factories or
    `ChatAgent._execute_tool`, and none locked in psql's exact text
    formatting (checked directly). New tests added: see
    tests/test_explain_query_hardening.py (skipped when no real DB is
    reachable, matching tools #15/#96's precedent).

Runtime verification: PASS — see
    backend/docs/tool_productionization/explain_query.md.
---------------------------------------------------------------------------

Real finding (severe — this tool's own schema explicitly promises
"Read-only (EXPLAIN does not modify data)", and this promise is FALSE
for all four implementations, proven two separate ways against the
real project database, safely, using a disposable table never part of
real project data):

1. **Statement stacking.** `EXPLAIN ANALYZE {query}` (or `EXPLAIN
   (ANALYZE, BUFFERS, FORMAT TEXT) {query};`) is a single string handed
   to `psql -c` (or, for `pr_`/`explain_query_h`, after only stripping
   a single TRAILING semicolon — an embedded one is untouched). Because
   `EXPLAIN` only prefixes the FIRST statement in a semicolon-separated
   sequence, a `query` value of `"SELECT 1; INSERT INTO
   explain_query_hardening_proof VALUES (999)"` produced `EXPLAIN
   ANALYZE SELECT 1; INSERT INTO explain_query_hardening_proof VALUES
   (999)` — executing this exact string over a real connection
   genuinely inserted a real row. Same "simple query protocol" multi-
   statement mechanism already proven for tools #15/#96.

2. **A DISTINCT, more fundamental gap, independent of stacking**:
   PostgreSQL's `EXPLAIN ANALYZE` genuinely EXECUTES whatever statement
   it is given, including a single, non-stacked INSERT/UPDATE/DELETE —
   this is documented core Postgres behavior, not a bug in Postgres,
   but this tool never restricted `query` to a read-only statement
   shape in the first place. Proved directly: `EXPLAIN ANALYZE INSERT
   INTO explain_query_hardening_proof2 VALUES (1)`, with ZERO
   stacking, genuinely inserted a real row. The tool's own schema
   promises "SQL SELECT query to analyse" — nothing ever enforced that.

`chat_agent.py`'s dispatch additionally wraps this in `shell=True` +
`shlex.quote(expq_full)` — this does NOT help, the same
`shlex.quote()`-is-not-enough class already documented for
`find_api`/`find_route`/`find_sql`/`inspect_schema`'s `chat_agent.py`
dispatches: it protects the shell from the string, not the SQL parser
from the SQL already embedded inside it.

Fixed via a shared `explain_query_handler()` with a real, two-part
validator (`_validate_explain_query()`):
 - rejects any `query` containing an embedded semicolon (after
   stripping at most one purely-trailing one) — closes finding #1;
 - rejects any `query` that doesn't start with `SELECT` or `WITH`
   (case-insensitive, leading whitespace/comments stripped) — closes
   finding #2 for the overwhelmingly common case.

**Known, documented residual limitation** (not fixed — flagged
explicitly rather than silently left, matching this initiative's
established practice for narrow residual gaps, e.g. tools #33/#46's
ReDoS deferrals): a `WITH` CTE can legally contain a data-modifying
statement with `RETURNING` (e.g. `WITH x AS (DELETE FROM t RETURNING
*) SELECT * FROM x`) — a real, sophisticated PostgreSQL feature no
simple leading-keyword check can rule out without a full SQL parser.
This is a narrow, deliberate-use pattern (not something an
accidental/naive `query` value would produce), and closing it
completely would require adding a real SQL-parsing dependency for one
low-risk residual case — out of scope for this turn's heuristic
validator, logged here for visibility rather than silently ignored.

No longer shells out to `psql` at all — real `psycopg2` connection
instead, matching tools #15/#96's precedent (also sidesteps this host
having no `psql` binary installed).
"""

from __future__ import annotations

import re
from typing import Any


def _validate_explain_query(query: str) -> tuple[str, str | None]:
    """Returns (cleaned_query, error_reason). error_reason is None on
    success. Never raises — a rejected query becomes a denial reason,
    matching every other validator in this initiative."""
    cleaned = query.strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].rstrip()

    if ";" in cleaned:
        return query, "query must be a single statement (embedded ';' is not allowed)"

    lowered = cleaned.lstrip().lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        return query, "query must be a read-only SELECT/WITH statement"

    return cleaned, None


def explain_query_handler(database_url: str, inp: dict[str, Any]) -> str:
    """Core explain_query logic shared by all four real call sites."""
    if not database_url:
        return "[ERROR] DATABASE_URL not configured"

    query = str(inp["query"])
    cleaned, error = _validate_explain_query(query)
    if error:
        return f"[ERROR] {error}"

    import psycopg2

    dsn = re.sub(r"^postgresql\+\w+://", "postgresql://", database_url)
    try:
        conn = psycopg2.connect(dsn, connect_timeout=10)
    except Exception as e:
        return f"[ERROR] Could not connect to database: {e}"
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {cleaned}")
            rows = cur.fetchall()
            return "\n".join(r[0] for r in rows) or "(no plan)"
    except Exception as e:
        return f"[ERROR] {e}"
    finally:
        conn.close()


EXPLAIN_QUERY_TOOL = {
    "name": "explain_query",
    "description": (
        "Run EXPLAIN ANALYZE on a SQL query against the configured DATABASE_URL. "
        "Shows query plan and execution times. Read-only (EXPLAIN does not modify data)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "SQL SELECT query to analyse (no trailing semicolon needed)",
            },
        },
        "required": ["query"],
    },
}

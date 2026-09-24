"""task_history_query tool — tool_enhance.md productionization pass,
tool #118 (2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: task_history_query
Old path: app/agents/tools.py (`_TASK_HISTORY_QUERY_TOOL` schema dict,
    `task_history_query()` function).
New path: app/tools/database/task_history_query.py (this file) —
    `TASK_HISTORY_QUERY_TOOL`, `task_history_query()`. Same function
    name kept verbatim (not renamed to a `*_handler` suffix) because
    `app/agents/agent_advisor.py` imports the function itself directly
    by name (`from app.agents.tools import ... task_history_query`)
    and assigns it straight into its own handlers dict — confirmed by
    reading that real call site before writing this module, not
    assumed from the import count alone.
Affected agents: `agent_advisor.py` (direct function import) + every
    `make_chat_handlers()`-based one-shot agent that declares
    `task_history_query` in `allowed_tools`, per `tool_inventory.json`.
    Also newly reachable from the interactive chat agent — see finding
    #3 below.
Affected modules: app/agents/tools.py (re-exports the function and
    schema unchanged for `agent_advisor.py` and `make_chat_handlers()`
    to keep working), app/agents/chat_agent.py (gains a real dispatch
    branch it never had — see finding #3).
Affected registries: none — app/fleet/tool_manifest.py's
    "task_history_query" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_task_history_query_hardening.py (skipped when no real
    DB is reachable, matching tools #15/#96's precedent).

Runtime verification: PASS — see
    backend/docs/tool_productionization/task_history_query.md.
---------------------------------------------------------------------------

Three real, empirically-verified findings.

1. **The tool was completely non-functional — every real call failed.**
   The query selected `FROM task_logs`, but the real `task_logs` table
   (`app/db/models.py::TaskLog`) has no `status` column at all (its
   columns are `id`, `task_id`, `category`, `message`, `extra_data`,
   `rationale`, `created_at`, `archived`, `archived_at`). Proved live
   against the real project database: the exact query this tool
   constructs (`SELECT id, status, created_at FROM task_logs ...`)
   raised `psycopg2.errors.UndefinedColumn: column "status" does not
   exist`. The `status` values this tool's own schema documents
   ("completed, failed, blocked") are `dev_tasks.status`
   (`app/db/models.py::DevTask`) values, not a `task_logs` concept —
   confirmed live that `SELECT id, status, created_at FROM dev_tasks`
   is the query that was actually intended and genuinely works.

2. **A genuine, live SQL injection (same class as tools #15/#96), on
   the corrected query.** `status` was directly f-string-interpolated
   into the raw SQL string, then handed to `psql -c` as a single argv
   element (multi-statement-per-call, same wire-protocol behavior as
   tool #96's `inspect_schema` finding). Proved directly against the
   real project database: `status = "x'; SELECT
   'INJECTED_MARKER_TASK_HISTORY' AS proof; --"` produced a query that,
   executed verbatim, genuinely returned the injected marker as a
   second, separate result. (This host has no `psql` binary at all —
   same as tool #96's environment note — so the tool's own
   `subprocess.run(["psql", ...])` call always raised `FileNotFoundError`
   before finding #1 could even surface; the injection was reproduced
   by executing the identical constructed string over a real
   psycopg2 connection instead, per tool #96's established
   methodology — the vulnerability lives in the STRING CONSTRUCTION,
   not in which client sends it.)

3. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools #100/#103/#110/#112.** `task_history_query` is
   in `CHAT_TOOLS` and registered in `make_chat_handlers()`'s handlers
   dict, but `app/agents/chat_agent.py`'s `_execute_tool()` has NO
   dispatch branch for it — every real interactive-chat call fell
   through to `"[ERROR] Unknown tool: task_history_query"`.

Fixed by: (1) correcting the table to `dev_tasks`, the table that
actually has the `status`/`created_at` columns this tool's schema
promises; (2) real `psycopg2` parameter binding — `status`/`limit` are
never string-interpolated into SQL text — same design direction as
tools #15/#96, dropping the `psql` subprocess call entirely (also
closes the "no `psql` binary" robustness gap as a side effect); (3) a
new `chat_agent.py` dispatch branch delegating to this same shared
function, making the tool genuinely reachable from interactive chat
for the first time.
"""

from __future__ import annotations

import re
from typing import Any

MAX_LIMIT = 200


def task_history_query(inp: dict[str, Any]) -> str:
    """Query recent task history from dev_tasks. Standalone (not
    repo-scoped) so any agent can reuse it, not just chat. Uses real
    psycopg2 parameter binding — `status` is never string-interpolated
    into SQL text, closing the injection the prior `psql`-based
    implementation had."""
    from app.config import get_settings

    db_url = getattr(get_settings(), "database_url", "")
    if not db_url:
        return "[ERROR] DATABASE_URL not set"

    limit = max(1, min(int(inp.get("limit", 20)), MAX_LIMIT))
    status_filter = inp.get("status")

    import psycopg2

    dsn = re.sub(r"^postgresql\+\w+://", "postgresql://", db_url)
    try:
        conn = psycopg2.connect(dsn, connect_timeout=10)
    except Exception as e:
        return f"[ERROR] Could not connect to database: {e}"
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            if status_filter:
                cur.execute(
                    "SELECT id, status, created_at FROM dev_tasks "
                    "WHERE status = %s ORDER BY created_at DESC LIMIT %s",
                    (str(status_filter), limit),
                )
            else:
                cur.execute(
                    "SELECT id, status, created_at FROM dev_tasks "
                    "ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
            rows = cur.fetchall()
            if not rows:
                return "(no task history found)"
            lines = [
                f"{task_id}  {status}  {created_at}"
                for task_id, status, created_at in rows
            ]
            return "\n".join(lines)
    except Exception as e:
        return f"[ERROR] {e}"
    finally:
        conn.close()


TASK_HISTORY_QUERY_TOOL: dict[str, Any] = {
    "name": "task_history_query",
    "description": "Query recent task history (id, status, created_at) from dev_tasks.",
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max records to return (default 20)",
            },
            "status": {
                "type": "string",
                "description": "Filter by status: completed, failed, blocked (optional)",
            },
        },
        "required": [],
    },
}

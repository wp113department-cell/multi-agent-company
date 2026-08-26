"""task_progress tool — tool_enhance.md productionization pass, tool
#119 (2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: task_progress
Old path: app/agents/tools.py (`_TASK_PROGRESS_TOOL` schema dict) with
    THREE real implementations, all shelling out to the `psql` CLI:
    `mon_task_progress` (`make_monitoring_agent_handlers`),
    `task_progress_h` (inside `make_chat_handlers()`), and
    `app/agents/chat_agent.py`'s own interactive dispatch.
New path: app/tools/database/task_progress.py (this file) —
    `TASK_PROGRESS_TOOL`, `task_progress_handler`. ALL THREE real call
    sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `task_progress` in `allowed_tools` (plus interactive chat).
Affected modules: app/agents/tools.py (both of its own closures
    delegate to the shared handler), app/agents/chat_agent.py (its
    dispatch now calls the same shared handler, dropping its
    `_run_subprocess`/`shell=True` psql invocation entirely).
Affected registries: none — app/fleet/tool_manifest.py's
    "task_progress" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_task_progress_hardening.py (skipped when no real DB is
    reachable, matching tools #15/#96/#118's precedent).

Runtime verification: PASS — see
    backend/docs/tool_productionization/task_progress.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **The tool was completely non-functional on this host — every real
   call failed.** All three implementations shell out to the `psql`
   CLI, which is not installed on this host at all. Proved live: all
   three real call sites returned `[ERROR] psql not found` /
   `FileNotFoundError` / `psql: not found` (the interactive dispatch's
   `shell=True` invocation surfaced it as `/bin/sh: 1: psql: not
   found`). Unlike tool #118's `task_history_query` (whose `status`
   field was a raw, unvalidated string — a genuine SQL injection
   vector once the table name was fixed), `task_id`/`limit` here are
   already `int()`-coerced by every implementation before reaching the
   SQL text, so there was no live-provable SQL injection on this
   specific tool — but the design is fragile (one accidental removal
   of an `int()` cast away from the exact same injection class as
   tools #15/#96/#118) and, more importantly, genuinely non-functional
   wherever `psql` isn't installed, matching tool #104's
   (`coverage_report`) "missing dependency" class.

2. **A real functionality-divergence bug: `mon_task_progress` silently
   ignores the schema's own documented `limit` field** — it hardcodes
   `LIMIT 10` regardless of what the caller passes, while its two
   siblings (`task_progress_h`, `chat_agent.py`'s dispatch) already
   honor it correctly. `mon_task_progress` also selects a different
   column set (`title` instead of `created_at`) than its two siblings.

Fixed via a shared `task_progress_handler()`: real `psycopg2`
parameter binding for `task_id`/`limit` (structurally closing the
injection risk for good, not just relying on every future edit
remembering the `int()` cast, and dropping the `psql` subprocess call
entirely — closing finding #1 for any host, with or without `psql`
installed). Selects the union of both column sets (`id`, `title`,
`status`, `created_at`, `updated_at`) so no caller loses a column it
previously had, and correctly honors `limit` on all three call sites,
closing finding #2.
"""

from __future__ import annotations

import re
from typing import Any

MAX_LIMIT = 200


def task_progress_handler(inp: dict[str, Any]) -> str:
    """Core task_progress logic shared by all three real call sites.
    Uses real psycopg2 parameter binding — `task_id`/`limit` are never
    string-interpolated into SQL text."""
    from app.config import get_settings

    db_url = getattr(get_settings(), "database_url", "")
    if not db_url:
        return "[ERROR] DATABASE_URL not set"

    task_id_raw = inp.get("task_id")
    if task_id_raw is not None:
        try:
            task_id = int(task_id_raw)
        except (TypeError, ValueError):
            return f"[ERROR] Invalid task_id: {task_id_raw!r}"
    else:
        task_id = None
    limit = max(1, min(int(inp.get("limit", 10)), MAX_LIMIT))

    import psycopg2

    dsn = re.sub(r"^postgresql\+\w+://", "postgresql://", db_url)
    try:
        conn = psycopg2.connect(dsn, connect_timeout=10)
    except Exception as e:
        return f"[ERROR] Could not connect to database: {e}"
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            if task_id is not None:
                cur.execute(
                    "SELECT id, title, status, created_at, updated_at "
                    "FROM dev_tasks WHERE id = %s LIMIT 1",
                    (task_id,),
                )
            else:
                cur.execute(
                    "SELECT id, title, status, created_at, updated_at "
                    "FROM dev_tasks ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
            rows = cur.fetchall()
            if not rows:
                return "(no tasks)"
            lines = [
                f"{row_id}  {title}  {status}  {created_at}  {updated_at}"
                for row_id, title, status, created_at, updated_at in rows
            ]
            return "\n".join(lines)
    except Exception as e:
        return f"[ERROR] {e}"
    finally:
        conn.close()


TASK_PROGRESS_TOOL: dict[str, Any] = {
    "name": "task_progress",
    "description": "Query recent task status from the dev_tasks database table. Optionally filter by task ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "Specific task ID (optional; default: last 10 tasks)",
            },
            "limit": {
                "type": "integer",
                "description": "Max tasks to return (default: 10)",
            },
        },
        "required": [],
    },
}

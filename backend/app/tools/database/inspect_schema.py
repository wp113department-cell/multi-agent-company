"""inspect_schema tool — tool_enhance.md productionization pass, tool
#96 (2026-08-25).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: inspect_schema
Old path: app/agents/tools.py (`_INSPECT_SCHEMA_TOOL` schema dict) with
    FIVE real implementations, all building a raw SQL/psql-meta-command
    string from the LLM-controlled `table` field and shelling out to the
    `psql` CLI: `sq_inspect_schema` (`make_sql_agent_handlers`),
    `mg_inspect_schema` (`make_migration_agent_handlers`),
    `sa_inspect_schema` (`make_schema_agent_handlers`), `inspect_schema`
    (inside `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch (also `shell=True`, `shlex.quote()`'d — see
    note below on why that did not help).
New path: app/tools/database/inspect_schema.py (this file) —
    `INSPECT_SCHEMA_TOOL`, `inspect_schema_handler`. ALL FIVE real call
    sites now delegate to this one shared handler, which no longer
    shells out to `psql` at all — same design direction as tool #15's
    `run_sql` (real psycopg2 parameter binding replacing raw psql
    string construction).
Affected agents: per tool_inventory.json, 4 agents declare
    `inspect_schema` in `allowed_tools` (plus interactive chat).
Affected modules: app/agents/tools.py (all three of its own closures
    delegate to the shared handler), app/agents/chat_agent.py (its
    dispatch now calls the same shared handler, dropping its
    `_run_subprocess`/`shell=True` psql invocation entirely).
Affected registries: none — app/fleet/tool_manifest.py's
    "inspect_schema" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the four handler factories or
    `ChatAgent._execute_tool`, and none locked in psql's exact text
    formatting (checked directly). New tests added: see
    tests/test_inspect_schema_hardening.py (skipped when no real DB is
    reachable, matching tool #15's precedent).

Runtime verification: PASS — see
    backend/docs/tool_productionization/inspect_schema.md.
---------------------------------------------------------------------------

Real finding (severe — a proven, live SQL injection, same class as tool
#15's `run_sql`): ALL FIVE implementations built a raw SQL string (or,
for `mg_`/`sa_`, a psql `\\d+`/`\\dt+` meta-command string) by directly
f-string-interpolating the LLM-controlled `table` field, then handed the
WHOLE constructed string to `psql -c` as a single argv element. Because
`psql`'s `-c` (and psycopg2's plain, non-parameterized `execute()`, which
uses the identical "simple query protocol" wire format) both accept
MULTIPLE semicolon-separated statements in one call, an attacker-supplied
`table` value can close the intended string literal early and append a
second, fully attacker-controlled SQL statement.

Proved directly against the real project database (safe, read-only,
statement-stacking marker proof — no data touched, same methodology as
tool #15): `table = "x'; SELECT 'INJECTED_MARKER_INSPECT_SCHEMA' AS
proof; --"` produced the query string `... WHERE table_name = 'x';
SELECT 'INJECTED_MARKER_INSPECT_SCHEMA' AS proof; --' ORDER BY
ordinal_position` — executing this EXACT string (the same string every
real implementation constructs and would hand to `psql -c`) via a real
connection genuinely returned the injected marker as a second, separate
result set. (Note: the live host this fix was developed on has no `psql`
binary installed at all, so the exploit was reproduced by executing the
identical constructed string over a real wire-protocol connection
instead — the vulnerability lives in the STRING CONSTRUCTION, not in
which client sends it, and `psql -c`/psycopg2's simple-query-protocol
share the same multi-statement-per-call behavior.)

`chat_agent.py`'s dispatch additionally wraps this in `shell=True` +
`shlex.quote(is_q)` — this does NOT help: `shlex.quote()` only prevents
the SHELL from misinterpreting the string, it does nothing to stop the
malicious SQL already embedded inside the (correctly shell-quoted, still
intact) query string from executing once `psql` parses it — the exact
same shlex.quote()-is-not-enough class already documented for
`find_api`/`find_route`/`find_sql`'s `chat_agent.py` dispatches earlier
in this initiative.

Fixed by full replacement, matching tool #15's precedent: the shared
`inspect_schema_handler()` no longer shells out to `psql` at all. It
opens a real `psycopg2` connection and uses genuine, out-of-band
parameter binding (`WHERE table_name = %s`) for the table-scoped query —
the same mechanism `run_sql_handler()` already uses, which cannot be
subverted by embedded quotes/semicolons because the value is never
concatenated into the SQL text. As a bonus (not a requirement, but
closing a real, separate FUNCTIONALITY gap along the way): the tool's own
schema has always promised "constraints" in its description, but only
the `\\d+`-based `mg_`/`sa_` implementations ever actually included any —
the three SELECT-based implementations (`sq_`, `inspect_schema`,
`chat_agent.py`) silently never delivered on that half of their own
contract. The unified handler now includes real primary/foreign/unique
constraint info (via `information_schema.table_constraints` +
`key_column_usage`, also parameter-bound) for EVERY caller, a capability
increase for 3 of the 5 previous call sites rather than a narrowing for
the other 2 — `mg_`/`sa_`'s richer `\\d+` output (which also showed
indexes and triggers, information this tool's schema never promised) is
the one piece of prior behavior not reproduced 1:1, a deliberate,
documented tradeoff for closing a live SQL injection rather than trying
to preserve an unsafe code path.
"""

from __future__ import annotations

import re
from typing import Any

MAX_TABLES = 200


def _format_columns(rows: list[tuple[Any, ...]]) -> list[str]:
    lines = ["Columns:"]
    for name, data_type, nullable, default in rows:
        default_part = f" DEFAULT {default}" if default else ""
        null_part = "NULL" if nullable == "YES" else "NOT NULL"
        lines.append(f"  {name}  {data_type}  {null_part}{default_part}")
    return lines


def _format_constraints(rows: list[tuple[Any, ...]]) -> list[str]:
    if not rows:
        return []
    lines = ["Constraints:"]
    for constraint_type, constraint_name, column_name in rows:
        lines.append(f"  {constraint_type}  {constraint_name}  ({column_name})")
    return lines


def inspect_schema_handler(database_url: str, inp: dict[str, Any]) -> str:
    """Core inspect_schema logic shared by all five real call sites.
    Uses real psycopg2 parameter binding — `table` is never
    string-interpolated into SQL text, closing the injection every prior
    implementation had."""
    if not database_url:
        return "[ERROR] DATABASE_URL not configured"

    table = str(inp.get("table", "")).strip()

    import psycopg2

    dsn = re.sub(r"^postgresql\+\w+://", "postgresql://", database_url)
    try:
        conn = psycopg2.connect(dsn, connect_timeout=10)
    except Exception as e:
        return f"[ERROR] Could not connect to database: {e}"
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            if table:
                cur.execute(
                    "SELECT column_name, data_type, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s "
                    "ORDER BY ordinal_position",
                    ("public", table),
                )
                columns = cur.fetchall()
                if not columns:
                    return f"(table not found: {table})"

                cur.execute(
                    "SELECT tc.constraint_type, tc.constraint_name, kcu.column_name "
                    "FROM information_schema.table_constraints tc "
                    "JOIN information_schema.key_column_usage kcu "
                    "  ON tc.constraint_name = kcu.constraint_name "
                    "  AND tc.table_schema = kcu.table_schema "
                    "WHERE tc.table_schema = %s AND tc.table_name = %s "
                    "ORDER BY tc.constraint_type, kcu.ordinal_position",
                    ("public", table),
                )
                constraints = cur.fetchall()

                lines = [f"Table: {table}", ""]
                lines.extend(_format_columns(columns))
                constraint_lines = _format_constraints(constraints)
                if constraint_lines:
                    lines.append("")
                    lines.extend(constraint_lines)
                return "\n".join(lines)

            cur.execute(
                "SELECT table_name, "
                "pg_size_pretty(pg_total_relation_size(quote_ident(table_name)::regclass)) "
                "FROM information_schema.tables "
                "WHERE table_schema = %s ORDER BY table_name",
                ("public",),
            )
            rows = cur.fetchmany(MAX_TABLES + 1)
            if not rows:
                return "(no tables found)"
            truncated = len(rows) > MAX_TABLES
            lines = [f"{len(rows)}{'+' if truncated else ''} table(s):"]
            for name, size in rows[:MAX_TABLES]:
                lines.append(f"  {name}  ({size})")
            return "\n".join(lines)
    except Exception as e:
        return f"[ERROR] {e}"
    finally:
        conn.close()


INSPECT_SCHEMA_TOOL = {
    "name": "inspect_schema",
    "description": "Show the PostgreSQL database schema: tables, columns, types, and constraints.",
    "input_schema": {
        "type": "object",
        "properties": {
            "table": {
                "type": "string",
                "description": "Specific table name to inspect (default: list all tables)",
            },
        },
        "required": [],
    },
}

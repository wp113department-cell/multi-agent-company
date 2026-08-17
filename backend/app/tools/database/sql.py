"""run_sql tool — tool_enhance.md productionization pass, tool #15
(2026-08-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: run_sql (the params-substitution variant — not the 4 other real
    run_sql implementations, which never accepted a `params` field in the
    first place; see "Deliberately left untouched")
Old path: app/agents/tools.py (`_RUN_SQL_TOOL` schema dict and the
    `run_sql` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body)
New path: app/tools/database/sql.py (this file) — `RUN_SQL_TOOL`,
    `run_sql_handler`.
Affected agents: 5 per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, plus every agent built on `make_chat_handlers()`
    that declares `run_sql` in `allowed_tools`.
Affected modules: app/agents/tools.py (compatibility re-export, handler
    delegates to the shared function), app/agents/chat_agent.py (its real
    dispatch now calls `run_sql_handler` via `asyncio.to_thread`).
Affected registries: none — app/fleet/tool_manifest.py's "run_sql"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["run_sql"](...)` or `ChatAgent._execute_tool`,
    and none locked in psql's exact text-table output formatting (checked
    directly — only loose `isinstance(result, str)`/substring assertions
    exist). New tests added: see tests/test_run_sql_hardening.py.

Deliberately left untouched: `make_sql_agent_handlers`'s `sq_run_sql`,
`make_performance_reviewer_handlers`'s `pr_run_sql`,
`make_migration_agent_handlers`'s `mg_run_sql`,
`make_schema_agent_handlers`'s `sa_run_sql` — none of these 4 accept a
`params` field at all; their `query` field is raw, LLM-authored SQL text
executed as a single `psql -c` list-arg (no `shell=True`, so no shell
injection), which is the tool's own documented, intended purpose, not a
parameterization bug. They were not exposed to this vulnerability in the
first place.

Runtime verification: PASS — see
    backend/docs/tool_productionization/run_sql.md.
---------------------------------------------------------------------------

Real finding (severe — a proven, live SQL injection): both real
implementations that accept `params` did naive string substitution —
`query.replace(f"${{i}}", f"'{{param}}'")` — with **zero escaping** of the
parameter value. Proved directly against the real project database (a
safe, read-only, 3-statement stacking proof — no data modified): a param
value of `"x'; SELECT 'INJECTED_STATEMENT_EXECUTED' AS marker; --"`
produced the string
`SELECT 'x'; SELECT 'INJECTED_STATEMENT_EXECUTED' AS marker; SELECT 'y' AS col`
and executed as 3 real, separate statements when run — the single quote
in the parameter was never escaped, so it closed the intended string
literal early and let an attacker-controlled second statement execute in
the same call.

User's explicit scope decision (AskUserQuestion, offered "escape quotes
in the psql string-substitution" as the narrower alternative): fix this
properly via real parameter binding (psycopg2, already a project
dependency) rather than hand-rolled string escaping, which is fragile
against edge cases (embedded NULs, encoding quirks, `standard_conforming_strings`
mode, etc.) that a real DB driver's wire-protocol parameter binding
handles correctly by construction. This also required discovering (and
empirically verifying) that psql's own `:'var'`-style safe variable
interpolation does NOT work with `-c` inline commands — only with `-f`
script files — making a psql-CLI-based fix meaningfully more complex than
initially assumed and reinforcing the case for switching to a direct DB
connection instead.
"""

from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER_RE = re.compile(r"\$(\d+)")
MAX_RESULT_ROWS = 200


def _convert_placeholders(
    query: str, params: list[str]
) -> tuple[str, tuple[str, ...], str | None]:
    """Converts `$1`/`$2`/... positional placeholders (this tool's own
    documented, LLM-facing convention) into psycopg2's native `%s` binding
    style, reordering (and, if a placeholder repeats, duplicating) values
    from `params` to match placeholder OCCURRENCE order in the query —
    `%s` slots bind positionally, so `WHERE b = $2 AND a = $1` requires the
    bound tuple to be `(params[1], params[0])`, not `params` unchanged.

    Returns (converted_query, bound_params, error_reason). error_reason is
    None on success. Never raises — a malformed placeholder reference
    becomes a denial reason, matching every other validator in this
    initiative."""
    bound: list[str] = []
    error: list[str] = []

    def _replace(m: "re.Match[str]") -> str:
        idx = int(m.group(1))
        if idx < 1 or idx > len(params):
            error.append(
                f"query references \\${idx} but only {len(params)} param(s) were given"
            )
            return m.group(0)
        bound.append(params[idx - 1])
        return "%s"

    converted = _PLACEHOLDER_RE.sub(_replace, query)
    if error:
        return query, (), error[0]
    return converted, tuple(bound), None


def _format_rows(columns: list[str], rows: list[tuple[Any, ...]]) -> str:
    if not rows:
        return " | ".join(columns) + "\n(0 rows)"
    lines = [" | ".join(columns)]
    lines.append("-+-".join("-" * len(c) for c in columns))
    truncated = len(rows) > MAX_RESULT_ROWS
    for row in rows[:MAX_RESULT_ROWS]:
        lines.append(" | ".join("" if v is None else str(v) for v in row))
    footer = f"({len(rows)}{'+' if truncated else ''} row(s))"
    if truncated:
        footer += f" — showing first {MAX_RESULT_ROWS}"
    lines.append(footer)
    return "\n".join(lines)


RUN_SQL_TOOL = {
    "name": "run_sql",
    "description": "Execute a SQL query against the project's PostgreSQL database.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "SQL query to execute"},
            "params": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Query parameters (positional, replaces $1, $2, ...) — safely bound, never string-substituted",
            },
        },
        "required": ["query"],
    },
}


def run_sql_handler(database_url: str, inp: dict[str, Any]) -> str:
    """Core run_sql logic shared by both real call sites. Executes via a
    real psycopg2 connection with genuine parameter binding — `$N`
    placeholders in `query` are converted to psycopg2's `%s` style and the
    matching values are passed to `cursor.execute(query, params)` for the
    driver to bind out-of-band over the wire protocol, never string-
    interpolated into the SQL text. This is what actually closes the
    injection this tool previously had, not a smarter escaping function."""
    if not database_url:
        return "[ERROR] DATABASE_URL not configured"

    query = str(inp["query"])
    params = [str(p) for p in (inp.get("params") or [])]
    converted_query, bound_params, error = _convert_placeholders(query, params)
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
            cur.execute(converted_query, bound_params or None)
            if cur.description is None:
                # psycopg2 reports rowcount as -1 for DDL/statements where
                # an affected-row count isn't meaningful (CREATE, etc.).
                if cur.rowcount < 0:
                    return "Query OK"
                return f"Query OK, {cur.rowcount} row(s) affected"
            columns = [d.name for d in cur.description]
            rows = cur.fetchmany(MAX_RESULT_ROWS + 1)
            return _format_rows(columns, rows)
    except Exception as e:
        return f"[ERROR] {e}"
    finally:
        conn.close()

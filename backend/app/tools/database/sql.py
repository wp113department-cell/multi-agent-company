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

# ---------------------------------------------------------------------------
# Write gate (verification batch B3, items #218/#220).
#
# Proved live: chat's run_sql executed `DELETE FROM t` and `DROP TABLE t`
# against the platform's OWN database with autocommit and no confirmation, and
# four agents' run_sql wrappers shelled out to `psql <postgresql+asyncpg://...>`
# (psql reads that as a database NAME, so they could never connect) with no
# read-only guard at all — the role files' "blocked from DROP/DELETE" was
# prompt-only.
#
# A Postgres read-only transaction is NOT enough on its own: proved live that
# `SET TRANSACTION READ WRITE; DELETE ...` and `COMMIT; BEGIN READ WRITE;
# DELETE ...; COMMIT` execute inside one "read-only" call. So a statement is
# treated as read-only only if ALL of these hold: exactly one statement (after
# stripping comments/strings/dollar-quotes), it starts with an allow-listed
# keyword, it uses none of the forbidden tokens (COPY .. PROGRAM, server-file
# and large-object functions, dblink, ...) — and it then runs inside a
# read-only transaction as a second, independent layer. Anything else is
# refused with WRITE_BLOCKED; the interactive chat asks a human and re-runs it
# with allow_write=True, headless agents simply cannot write.
# ---------------------------------------------------------------------------

WRITE_BLOCKED = "[WRITE BLOCKED]"
_READ_FIRST_KEYWORDS = frozenset(
    {"select", "with", "values", "table", "show", "explain"}
)
_FORBIDDEN_TOKENS = frozenset(
    {
        "copy",
        "program",
        "lo_import",
        "lo_export",
        "lo_unlink",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "dblink",
        "dblink_exec",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "pg_rotate_logfile",
        "set_config",
        "pg_advisory_lock",
        "nextval",
        "setval",
        "into",  # SELECT ... INTO newtable
        # DML/DDL/session-control words anywhere in a "read" statement: a writable
        # CTE (WITH d AS (DELETE ...) SELECT ...), EXPLAIN ANALYZE <write>, SELECT ... FOR UPDATE.
        # (`end`/`fetch`/`start` are deliberately NOT here: CASE ... END and
        # FETCH FIRST n ROWS are ordinary read syntax.)
        "insert",
        "update",
        "delete",
        "merge",
        "truncate",
        "drop",
        "create",
        "alter",
        "grant",
        "revoke",
        "vacuum",
        "reindex",
        "cluster",
        "refresh",
        "lock",
        "do",
        "call",
        "prepare",
        "deallocate",
        "discard",
        "reset",
        "set",
        "commit",
        "rollback",
        "savepoint",
    }
)


def _scrub_sql(sql: str) -> str:
    """The SQL with comments removed and the CONTENT of string literals,
    quoted identifiers and dollar-quoted bodies blanked — so keyword/`;`
    scanning can't be fooled by text inside them."""
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        two = sql[i : i + 2]
        if two == "--":
            j = sql.find("\n", i)
            i = n if j == -1 else j
            out.append(" ")
        elif two == "/*":
            depth, i = 1, i + 2
            while i < n and depth:
                if sql[i : i + 2] == "/*":
                    depth, i = depth + 1, i + 2
                elif sql[i : i + 2] == "*/":
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            out.append(" ")
        elif c == "'" or (
            c in "eE"
            and sql[i + 1 : i + 2] == "'"
            and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_"))
        ):
            escapes = c in "eE"
            i += 2 if escapes else 1
            while i < n:
                if escapes and sql[i] == "\\":
                    i += 2
                elif sql[i] == "'":
                    if sql[i + 1 : i + 2] == "'":
                        i += 2
                    else:
                        i += 1
                        break
                else:
                    i += 1
            out.append(" '' ")
        elif c == '"':
            i += 1
            while i < n and not (sql[i] == '"' and sql[i + 1 : i + 2] != '"'):
                i += 2 if sql[i] == '"' else 1
            i += 1
            out.append(" ident ")
        elif c == "$":
            m = re.match(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$", sql[i:])
            if m:
                tag = m.group(0)
                end = sql.find(tag, i + len(tag))
                i = n if end == -1 else end + len(tag)
                out.append(" '' ")
            else:
                out.append(c)
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def is_read_only_sql(sql: str) -> bool:
    """True only for a single, allow-listed, side-effect-free-looking statement."""
    bare = _scrub_sql(sql).lower()
    statements = [part for part in bare.split(";") if part.strip()]
    if len(statements) != 1:
        return False
    tokens = re.findall(r"[a-z_][a-z0-9_$]*", statements[0])
    if not tokens or tokens[0] not in _READ_FIRST_KEYWORDS:
        return False
    return not (_FORBIDDEN_TOKENS & set(tokens))


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


def run_sql_handler(
    database_url: str, inp: dict[str, Any], *, allow_write: bool = False
) -> str:
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
    read_only = is_read_only_sql(query)
    if not read_only and not allow_write:
        return (
            f"{WRITE_BLOCKED} This statement is not a single read-only query "
            "(it may modify data or schema, run several statements, or use a "
            "server-side file/command feature). Running it needs explicit human "
            "approval, which this run does not have."
        )

    import psycopg2

    dsn = re.sub(r"^postgresql\+\w+://", "postgresql://", database_url)
    try:
        conn = psycopg2.connect(dsn, connect_timeout=10)
    except Exception as e:
        return f"[ERROR] Could not connect to database: {e}"
    try:
        if read_only:
            # second, independent layer under the statement classifier
            conn.set_session(readonly=True, autocommit=False)
        else:
            conn.autocommit = True  # approved write: unchanged behaviour
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
        try:
            if read_only:
                conn.rollback()
        finally:
            conn.close()

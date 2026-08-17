# Tool #15 — `run_sql` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Six implementations, but only two accept a `params` field:

1. `chat_agent.py`'s real interactive dispatch — accepts `query` +
   `params`, does naive string substitution.
2. `make_chat_handlers()`'s own `run_sql` — same shape, same bug —
   reachable by 5 real agents per `tool_inventory.json`.
3. `make_sql_agent_handlers`'s `sq_run_sql` — raw `query` only, no
   `params`.
4. `make_performance_reviewer_handlers`'s `pr_run_sql` — raw `query`
   only, plus a destructive-keyword blocklist (read-only agent).
5. `make_migration_agent_handlers`'s `mg_run_sql` — raw `query` only,
   plus its own destructive-keyword blocklist.
6. `make_schema_agent_handlers`'s `sa_run_sql` — raw `query` only, plus
   its own destructive-keyword blocklist.

Implementations 3-6 pass `query` as a single list-arg to `psql` (no
`shell=True`), and never accept a `params` array at all — their `query`
is raw, LLM-authored SQL, which is the tool's own documented, intended
purpose (a `run_sql`-style tool inherently lets the LLM run SQL it
writes). That's not a parameterization bug; it's the tool working as
designed. This audit's finding is specific to implementations 1 and 2,
which advertised `params` as a *safe* way to inject values into a query
— and weren't.

## Problems found (real, empirically verified — the most severe of this
initiative since the high-risk tier)

**SQL injection via unescaped parameter substitution.** Both
implementations 1 and 2 did:

```python
for rs_i, rs_p in enumerate(rs_params, 1):
    rs_query = rs_query.replace(f"${rs_i}", f"'{rs_p}'")
```

— wrapping each parameter in single quotes but never escaping a quote
*inside* the parameter value. Proved directly against the real project
database (a safe, read-only, 3-statement-stacking proof — no data
modified, no destructive statement executed):

```python
rs_query = "SELECT $1 AS col"
rs_params = ["x'; SELECT 'INJECTED_STATEMENT_EXECUTED' AS marker; SELECT 'y"]
# after substitution:
# SELECT 'x'; SELECT 'INJECTED_STATEMENT_EXECUTED' AS marker; SELECT 'y' AS col
```

Executing this string against the real database succeeded as **3 real,
separate SQL statements** — the single quote in the parameter closed the
intended string literal early, and the attacker-controlled middle
statement executed for real. With destructive SQL (`DROP TABLE`,
`DELETE`, etc.) instead of the harmless marker `SELECT` used for this
proof, this would have been a real data-destruction/exfiltration
primitive, reachable directly from the main interactive chat agent.

## Research: why not just escape the quotes in place?

Investigated using `psql`'s own native safe-substitution mechanism
(`-v var=value` + `:'var'` syntax) instead of hand-rolled escaping —
`psql` has a real feature for exactly this. **Verified empirically it
does not work the way expected**: `:'var'` interpolation only fires when
`psql` reads a script via `-f`; it is a no-op (a literal syntax error)
when passed through `-c`, which is what every implementation here uses.
Making that mechanism work would require restructuring every call site to
write a temp script file — a comparable-sized change to switching
databases drivers entirely, without psycopg2's stronger guarantee (wire-
protocol parameter binding handles every input shape correctly by
construction; hand-rolled quote-doubling only handles the single-quote
case and can still be wrong under encoding edge cases).

## User's scope decision

Presented two options via AskUserQuestion: (a) switch to real
psycopg2-parameterized queries (recommended — the only fully robust fix),
or (b) a minimal patch (double every single quote before substitution,
staying on the `psql`-CLI architecture). **User chose (a).**

## Changes made

- **`app/tools/database/sql.py`** (new): `RUN_SQL_TOOL` (schema — now
  documents params as "safely bound, never string-substituted"),
  `_convert_placeholders()` (converts this tool's own `$1`/`$2`/...
  convention into psycopg2's native `%s` binding style, reordering values
  to match placeholder *occurrence* order — `WHERE b = $2 AND a = $1`
  correctly binds `(params[1], params[0])`, not `params` unchanged — and
  correctly handles a placeholder referenced more than once), and
  `run_sql_handler()` (opens a real `psycopg2` connection — stripping the
  project's `postgresql+asyncpg://` SQLAlchemy-style URL prefix down to
  plain `postgresql://` for psycopg2's own DSN parser — and executes via
  `cursor.execute(query, params)`, letting the driver bind parameters
  out-of-band over the wire protocol instead of string-interpolating them
  into SQL text at all).
- **`app/agents/chat_agent.py`**: its real dispatch now calls
  `run_sql_handler` via `asyncio.to_thread` instead of building a raw
  shell command.
- **`app/agents/tools.py`**: `make_chat_handlers`'s own `run_sql` now
  delegates to the shared function. `_RUN_SQL_TOOL` (used by 4 separate
  tool lists) now aliases the canonical schema.

**Output format changed** from `psql`'s own text-table rendering to a
simple, equivalent `col1 | col2` / dashes / rows / `(N row(s))` format
built directly from the driver's own result set (no `psql` binary
dependency at all anymore for these 2 call sites). Checked every test
referencing `run_sql`'s output beforehand — only loose
`isinstance(result, str)`/substring assertions exist, none locked in
`psql`'s specific formatting.

**Deliberately left untouched**: `sq_run_sql`/`pr_run_sql`/`mg_run_sql`/
`sa_run_sql` — never accepted `params`, never exposed to this bug.

## Tests (real, not mocked at the mechanism level — require a real
`DATABASE_URL`, skipped otherwise matching this codebase's convention)

`tests/test_run_sql_hardening.py` (new, 17 tests):

- Schema shape check.
- Pure unit tests of `_convert_placeholders`: simple positional binding,
  out-of-order reordering, a repeated placeholder reference, an
  out-of-range placeholder producing a clean error.
- **The exact proven exploit run against the real database** and
  confirmed closed: the stacked-statement payload, a bare embedded single
  quote, and a `DROP TABLE`-shaped payload all come back as one intact
  literal row value — proof the driver bound them as data, not SQL.
- Regression: a real no-params query, a real single-param query, DDL
  with no result set, a missing-`DATABASE_URL` error, a real SQL syntax
  error surfaced cleanly.
- Both real call sites exercised directly, each proving the exploit is
  closed end-to-end through the real dispatch path (not just the shared
  function in isolation): `chat_agent.py`'s dispatch and
  `make_chat_handlers`'s own handler.

## Regression

Targeted sweep (new test file + chat_tools/day2/day2_agent_contracts/
day3/phase4 tests + run_python_snippet/edit_file/write_file hardening):
**445 passed.** Full suite re-run after this pass — see
`tool_enhance_tracking.md`'s row for this tool for the final count.

## Final verdict

**GREEN FLAG.**

A real, live, proven SQL injection — the most severe finding of this
initiative since the high-risk tier's shell-injection bugs — closed via
the objectively correct fix (real parameter binding), not a patch. No
functionality lost: every legitimate query, with or without parameters,
in any order, continues to work correctly.

# Tool #96 — `inspect_schema` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Five real implementations, all building a raw SQL/psql-meta-command
string from the LLM-controlled `table` field and shelling out to the
`psql` CLI:

1. `chat_agent.py`'s own interactive dispatch (`shell=True` +
   `shlex.quote()`).
2. `inspect_schema` inside `make_chat_handlers()`.
3. `sq_inspect_schema` (`make_sql_agent_handlers`).
4. `mg_inspect_schema` (`make_migration_agent_handlers`) — uses psql's
   `\d+`/`\dt+` meta-commands instead of a SELECT.
5. `sa_inspect_schema` (`make_schema_agent_handlers`) — identical to
   `mg_inspect_schema`.

Per `tool_inventory.json`, 4 agents declare `inspect_schema` in
`allowed_tools`. `CHAT_TOOLS.count("inspect_schema") == 1` verified. 3
existing test files reference this tool — read in context and re-run,
all still pass unchanged (4 tests).

## Problems found

**Real, proven SQL injection — same class as tool #15's `run_sql`,**
on all five implementations. Each f-string-interpolates `table`
directly into a SQL/meta-command string, then hands the WHOLE
constructed string to `psql -c` as a single argv element. Because
`psql -c` (and psycopg2's plain, non-parameterized `execute()`, which
uses the same "simple query protocol" wire format) both accept
multiple semicolon-separated statements in one call, an
attacker-supplied `table` can close the intended string literal early
and append a second, fully attacker-controlled SQL statement.

Proved directly against the real project database (safe, read-only,
statement-stacking marker proof — no data touched): `table = "x';
SELECT 'INJECTED_MARKER_INSPECT_SCHEMA' AS proof; --"` produced `...
WHERE table_name = 'x'; SELECT 'INJECTED_MARKER_INSPECT_SCHEMA' AS
proof; --' ORDER BY ordinal_position` — executing this EXACT
constructed string over a real connection genuinely returned the
injected marker as a second, separate result set. (The host this fix
was developed on has no `psql` binary installed at all, so the exploit
was reproduced by executing the identical constructed string over a
real wire-protocol connection instead of literally shelling to `psql`
— the vulnerability lives in the string construction, not in which
client sends it.)

`chat_agent.py`'s dispatch additionally wraps this in `shell=True` +
`shlex.quote(is_q)` — this does NOT help: `shlex.quote()` only prevents
the shell from misinterpreting the string, it does nothing to stop the
malicious SQL already embedded inside the (correctly shell-quoted,
still intact) query string from executing once `psql` parses it — the
same `shlex.quote()`-is-not-enough class already documented for
`find_api`/`find_route`/`find_sql`'s `chat_agent.py` dispatches.

## Changes made

Full replacement, matching tool #15's precedent: the shared
`inspect_schema_handler()` in `app/tools/database/inspect_schema.py`
no longer shells out to `psql` at all. It opens a real `psycopg2`
connection and uses genuine, out-of-band parameter binding (`WHERE
table_name = %s`) — the same mechanism `run_sql_handler()` already
uses, immune to embedded quotes/semicolons because the value is never
concatenated into SQL text.

As a bonus (not required, but closing a real, separate gap along the
way): the tool's own schema has always promised "constraints" in its
description, but only the `\d+`-based `mg_`/`sa_` implementations ever
actually included any. The unified handler now includes real
primary/foreign/unique constraint info (via `information_schema.
table_constraints` + `key_column_usage`, also parameter-bound) for
EVERY caller — a capability increase for 3 of the 5 previous call
sites. `mg_`/`sa_`'s richer `\d+` output (which also showed indexes
and triggers, information this tool's schema never promised) is the
one piece of prior behavior not reproduced 1:1 — a deliberate,
documented tradeoff for closing a live SQL injection rather than
trying to preserve an unsafe code path.

`app/agents/tools.py`'s `_INSPECT_SCHEMA_TOOL` now aliases the shared
`INSPECT_SCHEMA_TOOL` constant via a plain module-level assignment.
No external direct-importers found (checked proactively before
wiring, per the standing tool #86 lesson).

## Tests

New file `tests/test_inspect_schema_hardening.py`, 18 tests, all real
against the live project database (skipped if `DATABASE_URL` isn't
configured, matching tool #15's precedent) — schema check,
duplicate-registration check, injection-payload-treated-as-opaque-data
proof (including a real `DROP TABLE`-shaped payload with a live
survival check afterward), the exploit closed on the interactive
dispatch AND all four handler factories (parametrized), and
legitimate-usage regression (table listing, real column + constraint
info) across all five real access paths. Existing tests
(`test_chat_tools.py::TestInspectSchema`, `test_day3_agents.py::
TestMigrationAgentHandlers::test_inspect_schema_handler`) re-run and
confirmed passing unchanged (4 tests).

## Regression

Per the user's 2026-08-25 cadence correction, the full suite is run
once per 5-tool batch rather than per tool — see
`feedback_tool_enhance_batch_full_suite` memory. This tool (#96) is
tool 3 of the current batch (#94-#98); its own new hardening tests
(18/18 pass against the real DB) and directly-referencing existing
tests (4/4 pass) are the per-tool verification gate. The full-suite
run covering this batch will be executed and reported once tool #98
completes.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/database/
inspect_schema.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all 97 `app/agents/` modules
(all clean), a `ruff check` on all 3 touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(caught and fixed a real `SyntaxWarning: invalid escape sequence '\d'`
in the docstring's own prose describing `\d+`/`\dt+`, same class as
tool #90's lesson) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The real, live SQL injection proved and closed across
all five real implementations via genuine parameter binding, not
string escaping; the fix also closes a real, separate documented-
contract gap (constraints); no functionality meaningfully lost (one
documented, deliberate tradeoff — `\d+`'s index/trigger info, never
part of this tool's own promised contract); tool-specific and
directly-referencing regression tests clean against the real database.
Full-suite confirmation pending as part of the #94-#98 batch.

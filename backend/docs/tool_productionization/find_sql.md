# Tool #91 — `find_sql` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Five real implementations:

1. `sec_find_sql` (`make_security_reviewer_handlers`) — grep-based,
   vulnerable.
2. `sq_find_sql` (`make_sql_agent_handlers`) — same shape as #1.
3. `pr_find_sql` (`make_performance_reviewer_handlers`) — the only
   pure-Python implementation, no subprocess at all.
4. `find_sql_h` (inside `make_chat_handlers()`, ~35 one-shot agents) —
   grep-based, more complete scope, vulnerable.
5. `app/agents/chat_agent.py`'s separate interactive dispatch — same
   scope as #4, `keyword` passed through `shlex.quote()`, vulnerable.

Per `tool_inventory.json`, 5 agents declare `find_sql` in
`allowed_tools`. `CHAT_TOOLS.count("find_sql") == 1` verified. 3
existing test files reference this tool; the real handler-invoking
ones re-run and confirmed passing unchanged (4 tests).

## Problems found

**Finding #1 — the same flag-injection class already established for
tools #69/#89/#90, on FOUR of the five real implementations.**
`keyword` was placed as a bare positional argv element with no `--`
separator in `sec_find_sql`, `sq_find_sql`, `find_sql_h`, and
`chat_agent.py`'s dispatch. Once again, `chat_agent.py`'s
`shlex.quote()` does NOT protect against this — it stops the shell
from misinterpreting the string, not grep's own argument parser.
Proved live: `keyword="-w"` was silently consumed as grep's real `-w`
(whole-word match) flag instead of being searched for as a literal
string, producing a misleadingly-confident "no SQL found" answer.
`pr_find_sql` was never exposed to this class at all (no subprocess).

**Finding #2 — a real functionality bug in `pr_find_sql`.** The
schema's own description promises "empty = all SQL" when `keyword` is
omitted — every grep-based implementation searches the full keyword
set (`SELECT|INSERT|UPDATE|DELETE|CREATE TABLE|...`), but
`pr_find_sql` silently defaulted to searching for `"SELECT"` alone.
Proved live: a real `INSERT INTO users VALUES (1)` statement was
invisible to `pr_find_sql({})` while present in the file.

A secondary, harmless observation: `sec_find_sql`/`sq_find_sql` also
read an `inp.get("file_pattern", "*.py")` field that does not exist
anywhere in the schema — dead code, since no real caller can ever
populate it. Dropped during unification.

## Changes made

Extracted `validate_find_sql_keyword()` + `find_sql_handler()` in
`app/tools/filesystem/find_sql.py`, adopted by all five real call
sites: the validator rejects any `keyword` starting with `-` outright,
matching the `search_code`/`find_api`/`find_route` precedent, closing
finding #1. `pr_find_sql` is fully replaced by the shared handler
(rather than kept as a second, divergent pure-Python implementation)
— adopting the correct full-keyword-set default closes finding #2.

`app/agents/tools.py`'s `_FIND_SQL_TOOL` now aliases the shared
`FIND_SQL_TOOL` constant (no external direct-importers found, verified
before wiring).

## Tests

New file `tests/test_find_sql_hardening.py`, 16 tests, all real (no
mocking) — schema check, `validate_find_sql_keyword()` direct unit
checks, the flag-shaped-`keyword` rejection verified closed on all
four grep-based dispatch paths (parametrized), the `pr_find_sql`
empty-keyword fix verified closed, and legitimate-usage regression
(keyword search, empty-keyword "all SQL" search, clean no-match
message) across all five real access paths. The existing real tests
(`test_day1_tools.py::TestFindSql`) re-run and confirmed passing
unchanged.

## Regression

Full suite (`pytest tests/ -q`) run in the background after the new
tests passed — see run log for the final tally; no failures introduced
by this change. Per the standing lesson from tool #88, this turn was
also verified via a comprehensive `mypy app/agents/` sweep (98 files
clean), an `importlib.import_module()` sweep (all clean), and a
`python -W error` docstring escape-sequence check (clean, applying the
lesson from tool #90) BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed across all
five real implementations; `pr_find_sql` fully unified rather than
left as a divergent second implementation; no functionality lost;
full regression clean.

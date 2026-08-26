# Tool #113 — `health_check` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three real implementations:

1. `chat_agent.py`'s own interactive dispatch — already correct.
2. `health_check_h` inside `make_chat_handlers()` — already correct,
   identical design.
3. `mon_health_check` (`make_monitoring_agent_handlers`) — see
   findings below, a genuinely different, broken implementation.

Per `tool_inventory.json`, agents declaring `health_check` go through
one of the factories above. `CHAT_TOOLS.count("health_check") == 1`
verified. 4 existing test files reference this tool — 1 genuinely
exercises the real handler (`test_day1_tools.py::TestHealthCheck`, 3
tests), re-run and confirmed passing unchanged; the others are
unrelated matches (a `find_api` test searching for a literally-named
`health_check` function in sample code, and `FleetManager` agent-
capability-routing tests using "health_check" as a capability string,
not this tool).

`service` is the only LLM-controlled field, and it only ever SELECTS
which fixed branch(es) run — never embedded into any command string.
`port` and `database_url` come from server-side settings, never the
LLM. So the usual worktree-escape/flag-collision/shell-injection
classes established throughout this initiative are structurally
impossible for the two already-correct implementations.

## Problems found

**Finding #1 — a real, severe functionality bug: `mon_health_check`
completely ignores the `service` field — the tool's only documented
input — and reads an entirely UNDOCUMENTED `url` field instead.**
Proved live: a real, schema-conformant call with `service="db"` is
silently ignored — this implementation ALWAYS curls a single
hardcoded URL regardless of what `service` requests, and NEVER checks
database connectivity at all, in any case — directly contradicting
the tool's own description ("backend HTTP health endpoint AND
database connectivity").

**Finding #2 — a real, second-order SSRF surface.** Because tool
schemas are advisory to the model, not strictly enforced server-side
(the same principle already established for tool #42's `git_stash`),
nothing prevents a real tool-call payload from including an extra,
undocumented `url` key. `mon_health_check` would use that value
directly as its `curl` target with zero validation — a real
Server-Side Request Forgery primitive (e.g. a cloud metadata endpoint)
reachable through a tool the caller would reasonably assume takes no
attacker-influenced network target at all.

## Changes made

Fully replaced `mon_health_check` with the shared
`health_check_handler()` in `app/tools/execution/health_check.py` —
adopting the already-correct design (`health_check_h`/`chat_agent.py`'s
dispatch, both independently verified safe) rather than kept as a
second, broken, and SSRF-exposed implementation. The shared handler
never reads a `url` field at all, closing finding #2 by construction,
not just validation, and genuinely honors `service` — closing finding
#1.

`app/agents/tools.py`'s `_HEALTH_CHECK_TOOL` now aliases the shared
`HEALTH_CHECK_TOOL` constant. No external direct-importers found.

## Tests

New file `tests/test_health_check_hardening.py`, 11 tests, all real
(no mocking, real `curl`/`pg_isready` subprocess calls) — schema
check (including a real assertion that no `url` property exists in
the schema), duplicate-registration check, real proof `service`
genuinely gates which checks run (`backend` excludes `Database`, `db`
excludes `Backend`, `all` includes both), a real proof
`mon_health_check` now genuinely attempts a database check (previously
impossible under any input), real proof an injected `url` field
(including a cloud-metadata-shaped SSRF payload) is never read on
either the interactive dispatch or the previously-vulnerable factory,
and legitimate-usage regression across all three real access paths.
Existing tests (`test_day1_tools.py::TestHealthCheck`) re-run and
confirmed passing unchanged (3 tests).

## Regression

This tool is the final one (5) of the current #109-#113 batch. Its own
new hardening tests (11/11 pass) and directly-referencing existing
tests (3/3 pass) are the per-tool verification gate. The full suite
was run to close out the batch (with the project's dev Postgres
confirmed reachable beforehand, avoiding the prior day's false-failure
pattern): **6046 passed, 52 skipped, 18 deselected, 0 failed**.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
health_check.py` sweep (98 files clean), an `importlib.import_module()`
sweep over all 97 `app/agents/` modules (all clean), a `ruff check` on
all 3 touched files (clean), and a `python -W error` docstring
escape-sequence check on the new module (clean) — BEFORE claiming
GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings — a broken implementation that
never checked the service it was asked to check, and a real
second-order SSRF surface reachable via an undocumented field — proved
and closed by fully adopting the already-correct, already-verified-
safe design; the tool now behaves consistently and safely regardless
of which agent calls it; no functionality lost; tool-specific and
directly-referencing regression tests clean.

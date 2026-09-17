# Tool #216 — `audit_log_read` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Single module-level function `audit_log_read()` in `app/agents/tools.py`,
shared by exactly 2 real agents — confirmed via direct grep:
`agent_advisor`, `agent_debugger` — matching `tool_inventory.json`'s
`agent_count: 2` exactly. Deliberately NOT in `CHAT_TOOLS` (confirmed
via membership check) — a batch/fleet-agent-only diagnostic tool, the
direct sibling of tool #215's `fleet_metrics_read` in the same
"SCAN phase (autonomous, read-only)" comment block.

Reads from `app.fleet.audit_log`'s real in-memory ring buffer
(`AuditLog.recent()`) — the fleet's action trail (what ran, for which
agent, with what outcome). No SQL, no subprocess, no filesystem access
— purely in-process, so no injection surface exists here.

## Problems found

The exact same finding class as tool #215's `fleet_metrics_read`: zero
`try`/`except` anywhere in the function body.
`n = int(inp.get("n", 50))` was a bare coercion with no guard. Proved
live, before any fix:

```
$ python -c "from app.agents.tools import audit_log_read; audit_log_read({'n': 'not-a-number'})"
Traceback (most recent call last):
  ...
ValueError: invalid literal for int() with base 10: 'not-a-number'
```

## Changes made

Extracted into `app/tools/agents/audit_log_read.py`
(`AUDIT_LOG_READ_TOOL`, `audit_log_read_handler`). Fixed by wrapping
the numeric coercion (`n = int(inp.get("n", 50))`) in its own
`try`/`except (TypeError, ValueError)`, returning
`"[ERROR] audit_log_read: invalid numeric argument for n: ..."`
instead of raising. All other behavior (agent-name filtering,
most-recent-N-entries windowing, formatted output lines) preserved
verbatim.

`app/agents/tools.py` now re-exports both names for backward
compatibility (`_AUDIT_LOG_READ_TOOL = AUDIT_LOG_READ_TOOL`,
`audit_log_read = audit_log_read_handler`) — both real consumer agent
files continue `from app.agents.tools import audit_log_read`
unchanged, verified by identity (`is`) in the new test file.

## Tests

Existing test: `tests/test_day9_fleet_agents.py::test_audit_log_read_filters_by_agent`
re-run and confirmed passing unchanged — doesn't exercise a malformed
`n`, so the fix doesn't affect it.

New file `tests/test_audit_log_read_hardening.py`, 9 tests: schema
check, `CHAT_TOOLS` non-membership, three malformed-`n` proofs
(string, `None`, list — all now return a clean `[ERROR]` string
instead of raising), legitimate-usage regression (unknown agent name,
agent-name filtering, default-`n`-omitted-vs-explicit equivalence),
and object-identity proof that `app.agents.tools.audit_log_read` and
both real consumer agents' `audit_log_read` attribute are the literal
same shared handler function.

## Regression

This tool's own new hardening tests (9/9 pass) plus
`tests/test_day9_fleet_agents.py` + `tests/test_new_tools.py` +
`tests/test_final_session.py` + `tests/test_batch16_scheduler_and_metrics.py`
+ `tests/test_fleet_metrics_read_hardening.py` (144 passed total, 1
pre-existing unrelated deprecation warning in `audit_log.py`, same one
already observed on tool #215's run).

Verified via `mypy` (4 touched files, clean) and `ruff check` (5
touched files, clean) BEFORE claiming GREEN_FLAG. Also verified
`CHAT_TOOLS` still has zero duplicate names (186 entries) and that
`app.agents.tools` reloads cleanly.

## Final verdict

**GREEN FLAG.** Real uncaught-crash bug found and fixed via evidence
(live reproduction before the fix, live proof of the clean error
string after) — the direct sibling of tool #215's finding, fixed
identically. No functionality lost — both real consumer agents
verified via identity to still use the exact same shared handler.
Agent alignment verified: PASS.

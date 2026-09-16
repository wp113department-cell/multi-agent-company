# Tool #215 — `fleet_metrics_read` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Single module-level function `fleet_metrics_read()` in
`app/agents/tools.py`, shared by exactly 3 real agents — confirmed via
direct grep: `agent_advisor`, `agent_performance_reviewer`,
`agent_debugger` — matching `tool_inventory.json`'s `agent_count: 3`
exactly. Deliberately NOT in `CHAT_TOOLS` (confirmed via membership
check) — this is a batch/fleet-agent-only diagnostic tool, part of the
SCAN-phase (autonomous, read-only) tool set documented in the comment
block above its old location: "SCAN phase (autonomous, read-only):
fleet_metrics_read, audit_log_read, task_history_query... — in-process,
no DB."

Reads from `app.fleet.metrics`'s real in-memory metrics collector —
recent runs fleet-wide, or per-agent p50/p95 latency and average tool
accuracy. No SQL, no subprocess, no filesystem access — purely
in-process, so no injection surface exists here.

## Problems found

One real, severe finding — **worse** than the uncaught-crash class
already found and fixed on tools #70/#72/#76/#127/#130/#135/#176/#210:
this function had **zero** `try`/`except` anywhere in its body (not
even a misplaced one, unlike tool #210's `capability_gap_scan`, which
at least had one around the wrong scope).

`n = int(inp.get("n", 20))` was a bare coercion with no guard. Proved
live, before any fix:

```
$ python -c "from app.agents.tools import fleet_metrics_read; fleet_metrics_read({'n': 'not-a-number'})"
Traceback (most recent call last):
  ...
ValueError: invalid literal for int() with base 10: 'not-a-number'
```

An uncaught exception here propagates straight out of the tool
handler. The agent framework's outer generic exception handling in
`base_graph.py`'s tool-execution node provides some mitigation, but
this tool's own contract — return a clean string, never raise — was
violated, exactly the class this initiative has repeatedly found and
fixed elsewhere.

## Changes made

Extracted into `app/tools/agents/fleet_metrics_read.py`
(`FLEET_METRICS_READ_TOOL`, `fleet_metrics_read_handler`). Fixed by
wrapping the numeric coercion (`n = int(inp.get("n", 20))`) in its own
`try`/`except (TypeError, ValueError)`, returning
`"[ERROR] fleet_metrics_read: invalid numeric argument for n: ..."`
instead of raising. All other behavior (fleet-wide recent-runs
listing, per-agent p50/p95 latency, average tool accuracy, failed-run
count) preserved verbatim.

`app/agents/tools.py` now re-exports both names for backward
compatibility (`_FLEET_METRICS_READ_TOOL = FLEET_METRICS_READ_TOOL`,
`fleet_metrics_read = fleet_metrics_read_handler`) — all 3 real
consumer agent files continue
`from app.agents.tools import fleet_metrics_read` unchanged, verified
by identity (`is`) in the new test file, not just by re-running them.

## Tests

Existing tests: `tests/test_day9_fleet_agents.py`'s
`test_fleet_metrics_read_empty()` and
`test_fleet_metrics_read_with_data()` re-run and confirmed passing
unchanged (2 passed) — neither exercises a malformed `n`, so the fix
doesn't affect them. `tests/test_batch16_scheduler_and_metrics.py`
only references the tool name in a comment (not a real test, matching
a known `tool_inventory.json` heuristic false-count already documented
for other tools).

New file `tests/test_fleet_metrics_read_hardening.py`, 10 tests:
schema check, `CHAT_TOOLS` non-membership, three malformed-`n` proofs
(string, `None`, list — all now return a clean `[ERROR]` string
instead of raising), legitimate-usage regression (empty collector,
unknown agent name, default-`n`-omitted-vs-explicit equivalence), and
object-identity proof that `app.agents.tools.fleet_metrics_read` and
all 3 real consumer agents' `fleet_metrics_read` attribute are the
literal same shared handler function.

## Regression

This tool's own new hardening tests (10/10 pass) plus
`tests/test_day9_fleet_agents.py` + `tests/test_new_tools.py` +
`tests/test_final_session.py` + `tests/test_batch16_scheduler_and_metrics.py`
(124 passed total, 1 pre-existing unrelated deprecation warning in
`audit_log.py`).

Verified via `mypy` (5 touched files, clean) and `ruff check` (6
touched files, clean) BEFORE claiming GREEN_FLAG. Also verified
`CHAT_TOOLS` still has zero duplicate names (186 entries) and that
`app.agents.tools` reloads cleanly with no circular-import issue.

## Final verdict

**GREEN FLAG.** Real uncaught-crash bug found and fixed via evidence
(live reproduction before the fix, live proof of the clean error
string after). No functionality lost — all 3 real consumer agents
verified via identity to still use the exact same shared handler.
Agent alignment verified: PASS.

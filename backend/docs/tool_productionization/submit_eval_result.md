# Tool #247 — `submit_eval_result` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_eval_result` lives entirely in `app/agents/evaluation_agent.py`.
Shared by exactly 1 real agent, confirmed via direct grep —
`evaluation_agent` itself — matching `tool_inventory.json`'s
`agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` (confirmed
via membership check). No `write_file` anywhere in this agent's tool
list — the write_file-scoping finding class from recent sibling tools
(#231/#232/etc.) does not apply here at all.

Also verified: `run_python_snippet` and `run_tests` are both
advertised in `_EVAL_TOOLS` and actually wired to real handlers via
`base = make_chat_handlers(repo_path)` — not an "advertised but never
dispatched" gap.

## Problems found

**Three** real, separate uncaught-crash paths, all from the same root
cause: `overall_score`/`cases`/`pass_count`/`fail_count` are never
schema-validated at runtime (the LLM's own submit call, or the
generic `submit_*` capture, can send anything the model produces,
despite the schema declaring specific types):

1. `submit_eval_h`'s own `f"score={score:.2f}"` raised an uncaught
   `ValueError` (*"Unknown format code 'f' for object of type
   'str'"*) when `overall_score` was a non-numeric string.
2. `run_evaluation_agent()`'s near-identical post-processing raised
   the exact same `ValueError` for the same reason.
3. `run_evaluation_agent()`'s findings-building list comprehension
   (`c.get("name", "?")` etc.) raised an uncaught `AttributeError` for
   a non-dict entry mixed into `cases`.

All 3 proved live, before any fix, via direct calls and a mocked
`run_agent_graph` return value.

## Changes made

Added a shared `_safe_float(value, default=0.0)` helper (`try:
return float(value) except (TypeError, ValueError): return default`),
used in both `submit_eval_h` (for `overall_score`) and
`run_evaluation_agent()` (for `overall_score`, `pass_count`, and
`fail_count` — the latter two also coerced via `int(_safe_float(...))`
so the `pass_count + fail_count` arithmetic can't raise a `TypeError`
either). In `run_evaluation_agent()`, filtered `cases` to dict entries
only (`[c for c in cases_raw if isinstance(c, dict)] if
isinstance(cases_raw, list) else []`) before building findings — the
same pattern already established for tool #242's `database_architect`.
All legitimate, well-formed submissions produce byte-identical output
to before.

## Tests

Existing tests across 4 files (`test_day4_agents.py`,
`test_day4_agent_contracts.py`, `test_gap_agents.py`,
`test_phase4_item4_record_learning_rollout.py`) re-run and confirmed
passing unchanged (36 evaluation_agent-related tests).

New file `tests/test_submit_eval_result_hardening.py`, 9 tests: schema
check, `CHAT_TOOLS` non-membership, a direct proof `write_file` isn't
in this agent's tool list at all, all 3 crash-path proofs (non-numeric
score at the handler level, non-numeric score at the
`AgentResult`-building level, non-dict `cases` entry, and non-numeric
`pass_count`/`fail_count`), and two legitimate well-formed-submission
regressions confirming exact output is unchanged.

## Regression

This tool's own new hardening tests (9/9 pass) plus the 4 existing
test files (36 tests) + `test_new_tools.py` + `test_final_session.py`
(424 passed total).

Verified via `mypy app/agents/evaluation_agent.py` (clean) and `ruff
check` (clean) BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Three real, empirically-verified crash paths, all
tracing to the same root cause (untrusted, unvalidated LLM submit
data), found and fixed via evidence (live reproduction before the
fix, live proof of graceful degradation and byte-identical legitimate
output after). No functionality lost. `run_python_snippet`/`run_tests`
wiring verified real, not advertised-but-dead. Agent alignment
verified: PASS.

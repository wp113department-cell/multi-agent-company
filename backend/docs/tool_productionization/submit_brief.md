# Tool #235 — `submit_brief` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_brief` lives entirely in `app/agents/pm.py`, structurally
near-identical to sibling tool #234's `submit_architect_plan` — `pm`
runs through a dedicated `app/pipeline/graph.py` node (`pm_node`), not
interactive chat at all. Deliberately NOT in `CHAT_TOOLS` (confirmed
via membership check). Confirmed single implementation.

## Problems found

None. No security vulnerability and no functional bug found — this
audit's real conclusion. The handler is a trivial no-op:

```python
handlers["submit_brief"] = lambda inp: "Brief submitted"
```

Confirmed intentional, correct design via direct inspection of
`pm_node`'s own body: `brief_result = final_state.get("result", {})`
reads directly from the generic `submit_*` capture mechanism in
`base_graph.py` — the same pattern already verified correct on sibling
tool #234. Proved the lambda cannot crash across 7 malformed input
shapes.

Also reviewed, no issues found:
- `pm_node`'s outer retry loop (AUDIT_Q_BATCH04 §6 gap-closure) —
  correctly uses `app.fleet.failure_ladder.should_retry`, matching the
  established pattern from `backend_dev.py`/`frontend_dev.py`/
  `coder.py`/`qa.py`.
- The confidence-surfacing line
  (`brief_with_confidence = {**brief_result, "confidence":
  final_state.get("confidence", 0.8)}`, AUDIT_Q_BATCH13 §43) —
  intentionally overwrites any model-claimed `confidence` field with
  the shared planner's real computed value; confirmed via a direct
  test that this dict-spread neither crashes nor drops other real
  fields.

## Changes made

None — verified correct as-is.

## Tests

Existing tests across 6 files (`test_day18_streaming_wiring.py`,
`test_fleet_tool_manifest.py`, `test_replanning_agent_wiring.py`,
`test_gap_closure_days0_18.py`, `test_session4_migration.py`,
`test_day1_agent_flags.py`) re-run and confirmed passing unchanged (29
pm-related tests).

New file `tests/test_submit_brief_hardening.py`, 5 tests: schema
check, `CHAT_TOOLS` non-membership, a direct proof that the handler's
own no-op lambda never crashes across 7 malformed input shapes, an
`AGENT_CONTRACT` wiring regression, and a confidence-surfacing
dict-spread regression.

## Regression

This tool's own new hardening tests (5/5 pass) plus the 6 existing
pm-adjacent test files (29 tests) + `test_new_tools.py` +
`test_final_session.py` (237 passed total, 1 pre-existing unrelated
`RuntimeWarning` about a mocked async coroutine in an unrelated
manager test).

## Final verdict

**GREEN FLAG.** Thorough audit found no security vulnerability and no
functional defect. The tool's apparent triviality was specifically
verified to be intentional correct design, matching the exact pattern
just confirmed on sibling tool #234. No functionality lost or changed.
Agent alignment verified: PASS.

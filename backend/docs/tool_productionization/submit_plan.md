# Tool #256 — `submit_plan` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_plan` lives entirely in `app/agents/planner.py`, structurally
identical to sibling tools #234 (`submit_architect_plan`) and #235
(`submit_brief`) — `planner` runs through a dedicated
`app/pipeline/graph.py` node, not interactive chat at all.
Deliberately NOT in `CHAT_TOOLS` (confirmed via membership check). No
`write_file` anywhere in this agent's tool list — the write_file-
scoping finding class from the recent run of sibling agents doesn't
apply here at all.

## Problems found

None. No security vulnerability and no functional bug found — this
audit's real conclusion. The handler is a trivial no-op:

```python
handlers["submit_plan"] = lambda inp: "Plan submitted"
```

Confirmed intentional, correct design via direct inspection of
`run_planner`'s own body: it reads
`final_state.get("result", {}).get("plan", "")` directly from the
generic `submit_*` capture mechanism in `base_graph.py` — the same
pattern already verified correct on sibling tools #234/#235. Proved
the lambda cannot crash across 5 malformed input shapes.

Also reviewed, no issues found: `_validate_plan()` — real,
deterministic markdown-section validation (minimum length + required
section headers) — coerces its input via `str()` before any string
operation, so it cannot crash regardless of what
`final_state["result"]["plan"]` actually contains. Confirmed correct
behavior on a too-short plan, a plan missing required sections, and a
well-formed plan.

## Changes made

None — verified correct as-is.

## Tests

Existing tests across 6 files (`test_batch12_coder_clarification.py`,
`test_day1_agent_flags.py`, `test_phase53_request_clarification.py`,
`test_session1_migration.py`,
`test_stage4_clustern_real_agent_run_heartbeat.py`,
`test_task_metadata_fields.py`) re-run and confirmed passing unchanged
(20 planner-related tests).

New file `tests/test_submit_plan_hardening.py`, 8 tests: schema check,
`CHAT_TOOLS` non-membership, a direct proof `write_file` isn't in this
agent's tool list, a direct proof the handler's own no-op lambda never
crashes across 5 malformed input shapes, an `AGENT_CONTRACT` wiring
regression, and three `_validate_plan()` regressions (too-short
rejection, missing-sections rejection, well-formed acceptance).

## Regression

This tool's own new hardening tests (8/8 pass) plus the 6 existing
planner-adjacent test files (20 tests) + `test_new_tools.py` +
`test_final_session.py` (177 passed total).

## Final verdict

**GREEN FLAG.** Thorough audit found no security vulnerability and no
functional defect. The tool's apparent triviality was specifically
verified to be intentional correct design, matching the exact pattern
already confirmed on sibling tools #234/#235. No functionality lost or
changed. Agent alignment verified: PASS.

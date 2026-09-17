# Tool #241 — `submit_data_pipeline_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_data_pipeline_agent` lives entirely in
`app/agents/data_pipeline_agent.py`, structurally similar to the
recent run of sibling agents fixed for an unrestricted `write_file`
(#231, #232, #237, #238, #239, #240). Shared by exactly 1 real agent,
confirmed via direct grep — `data_pipeline_agent` itself — matching
`tool_inventory.json`'s `agent_count: 1` exactly. Deliberately NOT in
`CHAT_TOOLS` (confirmed via membership check). This agent was **not**
in the 14-candidate reconnaissance list from tool #240's turn,
correctly, as this audit confirms below.

## Problems found

None. No security vulnerability and no functional bug found — this
audit's real conclusion, reached only after specifically checking the
finding class just fixed on 6 sibling tools.

**Investigated and RULED OUT**: unlike those sibling agents,
`roles/data_pipeline_agent.md` does **not** claim "read-only on code"
or "zero repo files modified" anywhere. Its own Non-Responsibilities
section frames the real scope boundary differently — *"Implementing
full production pipelines (workers implement; you design + stub)"* —
and its Output Contract explicitly lists a `"stubs"`:
*"implementation stub paths"* field. `AGENT_CONTRACT`'s own
`side_effects=["writes pipeline design .md or .yaml files"]` already
hints at broader output than pure docs. Confirmed live that writing a
real `.py` stub file (`pipelines/etl_stub.py`) succeeds — correct,
intended behavior for an agent whose job explicitly includes producing
implementation stubs, not just design documents. Applying the sibling
agents' `.md`/`docs/**` restriction here would have been a real
regression, matching the exact discernment already applied to sibling
tool #233's `submit_api_designer_agent` audit.

`submit_h` audited against the dead-accumulator distinction and found
correct: `run_data_pipeline_agent()`'s
`raw = final_state["result"] if final_state["result"] else result`
line already prioritizes the real, graph-enforced capture, matching
the exact pattern already confirmed live (not dead) on sibling agents.

## Changes made

None — verified correct as-is.

## Tests

Existing tests across 5 files (`test_analyzer_tier_confirmed.py`,
`test_day5b_agents.py`, `test_dead_contract_fix.py`,
`test_record_learning_rollout.py`, `test_role_file_tools_accuracy.py`)
re-run and confirmed passing unchanged (20 data_pipeline_agent-related
tests).

New file `tests/test_submit_data_pipeline_agent_hardening.py`, 5
tests: schema check, `CHAT_TOOLS` non-membership, the
legitimate-stub-file-write regression (the specific case that would
have broken if the sibling agents' fix had been blindly reapplied
here), a worktree-escape-still-blocked regression, and a
`submit_data_pipeline_agent` accumulation regression.

## Regression

This tool's own new hardening tests (5/5 pass) plus the 5 existing
test files (20 tests) + `test_new_tools.py` + `test_final_session.py`
(339 passed total).

## Final verdict

**GREEN FLAG.** Thorough audit found no security vulnerability and no
functional defect. Explicitly investigated the same finding class just
fixed on 6 sibling agents and correctly determined it does NOT apply
here — this agent's role prompt and contract genuinely intend broader
write access for its legitimate implementation-stub output, confirmed
via direct role-file reading, not assumption. No functionality lost or
changed. Agent alignment verified: PASS.

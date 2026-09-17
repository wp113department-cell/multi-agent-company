# Tool #251 — `submit_load_test_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_load_test_agent` lives entirely in `app/agents/load_test_agent.py`.
Shared by exactly 1 real agent, confirmed via direct grep —
`load_test_agent` itself — matching `tool_inventory.json`'s
`agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` (confirmed
via membership check).

`bash` is already correctly scoped to `make_load_test_bash_handler`
(k6/locust-only, rejects arbitrary shell commands — verified live that
`rm -rf /` is denied) — verified still in place, not touched.

`submit_h` audited against the dead-accumulator distinction and found
correct: `run_load_test_agent()`'s
`raw = final_state["result"] if final_state["result"] else result`
line already prioritizes the real, graph-enforced capture, matching
the exact pattern already confirmed live (not dead) on sibling agents.

## Problems found

None. No security vulnerability and no functional bug found — this
audit's real conclusion, reached only after specifically checking the
"unrestricted write_file contradicts a docs-only role promise" finding
class just fixed on 12 sibling agents (#231, #232, #237-#240, #243-#246,
#248-#250).

**Investigated and RULED OUT**: unlike those sibling agents,
`roles/load_test_agent.md` does **not** claim "read-only on code" or
"zero repo files modified" anywhere — this agent's whole job is
writing a real, runnable k6 or Locust load-test **script** (real
code), not a doc. Its own Failure Conditions instead scope writes
narrowly — *"Editing any file that was not read in this run"* and
*"Writing outside the assigned worktree/scope"* — a fundamentally
different, narrower kind of restriction than the blanket
read-only-on-code lockout the fixed sibling agents explicitly declare.
`AGENT_CONTRACT`'s own `side_effects=["writes load test scripts", "runs
a short smoke test of the script"]` already makes the intended scope
explicit. Confirmed live that writing a real `.js` k6 script
(`loadtest/k6_script.js`) succeeds — correct, intended behavior.
Applying the sibling agents' `.md`/`docs/**` restriction here would
have been a real regression, matching the exact discernment already
applied to sibling tools #233 (`submit_api_designer_agent`) and #241
(`submit_data_pipeline_agent`).

## Changes made

None — verified correct as-is.

## Tests

Existing tests across 7 files (`test_analyzer_tier_confirmed.py`,
`test_day6b_agents.py`, `test_dead_contract_fix.py`,
`test_executor_tier_bash.py`, `test_phase34_real_output_verification.py`,
`test_phase3_verification_audit.py`, `test_record_learning_rollout.py`)
re-run and confirmed passing unchanged (20 load_test_agent-related
tests).

New file `tests/test_submit_load_test_agent_hardening.py`, 6 tests:
schema check, `CHAT_TOOLS` non-membership, the legitimate-script-write
regression (the specific case that would have broken if the sibling
agents' fix had been blindly reapplied here), a
worktree-escape-still-blocked regression, a regression confirming
`bash` is still the scoped k6/locust-only handler, and a
`submit_load_test_agent` accumulation regression.

## Regression

This tool's own new hardening tests (6/6 pass) plus the 7 existing
test files (20 tests) + `test_new_tools.py` + `test_final_session.py`
(471 passed total; one pre-existing, already-documented unrelated
failure in `test_executor_tier_bash.py::test_allows_pytest` — a real
docker-version-precheck call-count mismatch in a different tool's own
test, first confirmed pre-existing during tool #243's turn — excluded
from this count per that established finding).

## Final verdict

**GREEN FLAG.** Thorough audit found no security vulnerability and no
functional defect. Explicitly investigated the same finding class just
fixed on 12 sibling agents and correctly determined it does NOT apply
here — this agent's role prompt and contract genuinely intend broader
write access for its legitimate load-test-script output, confirmed via
direct role-file reading, not assumption. `bash` scoping also verified
correct. No functionality lost or changed. Agent alignment verified:
PASS.

# Tool #269 — `submit_threat_model` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_threat_model` lives in `app/agents/security_architect.py`.
Deliberately NOT in `CHAT_TOOLS` (confirmed via membership check).
This agent is fully read-only: `AGENT_CONTRACT` declares
`permissions=["read_repo"]` only, `side_effects=[]`, and `write_file`
does not appear anywhere in its tool list — the write_file-scoping
finding class from the report-writer agents doesn't apply here at all.

## Problems found

Real, proven defect, identical class to sibling tools #258
(`submit_rag_design`) and #259 (`submit_release_notes`):
`run_security_architect`'s own `raw = submitted if submitted else
final_state["result"]` had the priority BACKWARDS relative to the
correct, established pattern used by every other `submit_*` agent in
this codebase. Because the local `submitted` closure dict is always
truthy once a submission happens, `raw` ALWAYS picked `submitted` and
NEVER `final_state["result"]` — silently dropping the graph-enforced
diagnostic trail (`_quality_gate`, `_citation_check`,
`_validation_warning`) from `AgentResult.raw`.

Proved live with `run_agent_graph` mocked to return a `final_state`
whose `result` carries a failed quality gate + unverified citation
check: before the fix, `AgentResult.raw` contained neither key.

## Changes made

Swapped the priority: `raw = final_state["result"] if
final_state["result"] else submitted`, matching the established
correct pattern. Verified live post-fix: the same reproduction now
correctly surfaces `_quality_gate` (with `passed: False`) and
`_citation_check`. Also verified the fallback still works when
`final_state["result"]` is genuinely empty, and that ordinary content
fields (`overall_risk`, `threats`) and `requires_human_approval` are
unaffected by the fix.

`ruff check` and `mypy` on the changed file: clean.

## Tests

Existing tests (`test_day4_agents.py`, `test_batch16_quality_gates.py`,
`test_gap_agents.py`, `test_phase4_item4_record_learning_rollout.py`,
`test_architecture_note_wiring.py`, `test_day4_agent_contracts.py`,
filtered to `security_architect`/`threat_model`/`threat`): 13 tests,
all still pass unchanged.

New file `tests/test_submit_threat_model_hardening.py`, 6 tests:
schema check, `CHAT_TOOLS` non-membership, a direct proof no
`write_file` exists in this agent's tools, the
graph-enforced-result-takes-priority proof (the real fix), the
local-dict-fallback-still-works regression, and a proof normal content
fields (including `requires_human_approval`) are unaffected.

## Regression

This tool's own new hardening tests (6/6 pass) plus the existing
security-architect-related tests (13) + `test_new_tools.py` — 424
passed total, 0 failed (one pre-existing, unrelated
`RuntimeWarning` about an un-awaited coroutine in
`test_batch16_quality_gates.py`, not a failure).

## Final verdict

**GREEN FLAG.** No security vulnerability (no write access at all on
this agent). Real, proven priority-order defect found and fixed —
graph-enforced diagnostics (including a failing quality gate) were
silently dropped from `AgentResult.raw`. Fix verified live to restore
the correct, established precedence used by every sibling agent while
leaving normal-case content unaffected. Zero functionality lost. Agent
alignment verified: PASS.

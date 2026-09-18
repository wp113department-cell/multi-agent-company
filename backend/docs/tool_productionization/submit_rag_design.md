# Tool #258 — `submit_rag_design` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_rag_design` lives in `app/agents/rag_engineer_agent.py`.
Deliberately NOT in `CHAT_TOOLS` (confirmed via membership check).

Checked and correctly RULED OUT the write_file-scoping finding class
already fixed on 15 sibling "read-only report writer" agents this run
(same discernment as tools #233/#241/#251/#253): `AGENT_CONTRACT`
explicitly declares `permissions=["read_repo", "write_repo",
"execute_code"]` and `side_effects=["may write pipeline implementation
files"]`, `risk_level: "medium"` — this agent's whole job is writing
real retrieval-pipeline code. Confirmed live that `write_file`
genuinely writing a real `.py` file (`app/retrieval.py`) succeeds —
correct, intended behavior; applying the sibling fix here would have
been a real regression.

## Problems found

Real, proven defect: `run_rag_engineer_agent`'s own
`raw = submitted if submitted else final_state["result"]` had the
priority BACKWARDS relative to the correct, established pattern used
by every other `submit_*` agent in this codebase (`final_state["result"]
if final_state["result"] else <local fallback>`).
`base_graph.py`'s `execute_tools()` builds `final_state["result"]`
starting from the exact same dict the LLM passed to
`submit_rag_design`, then extends it with graph-enforced diagnostics
(`_quality_gate`, `_citation_check`, `_validation_warning`) at the one
real `submit_*` chokepoint. Because the local `submitted` closure dict
is always truthy once a submission happens, `raw` ALWAYS picked
`submitted` and NEVER `final_state["result"]` — silently dropping that
diagnostic trail, including a genuinely FAILING quality gate
(`_quality_gate.passed=False`), from `AgentResult.raw`.

Proved live with `run_agent_graph` mocked to return a `final_state`
whose `result` carries a failed quality gate + unverified citation
check, while the real `submit_rag_design` handler was also invoked
(populating `submitted` with the plain content, no diagnostics): before
the fix, `AgentResult.raw` contained neither `_quality_gate` nor
`_citation_check` — the failed gate was invisible. Checked all current
production consumers of `AgentResult.raw` (`app/agents/manager.py`,
`app/api/fleet_dashboard.py`, `app/api/specialized_agents.py`) — none
currently read these specific diagnostic keys, so this was not
actively causing a downstream crash, but it was a genuine, silent
inconsistency versus the correct pattern already established (and
relied upon) across ~76 sibling agents in this codebase.

## Changes made

Swapped the priority: `raw = final_state["result"] if
final_state["result"] else submitted`, matching the established
correct pattern. Verified live post-fix: the same reproduction now
correctly surfaces `_quality_gate` (with `passed: False`) and
`_citation_check` in `AgentResult.raw`. Also verified the fallback
still works when `final_state["result"]` is genuinely empty, and that
ordinary content fields (`summary`, `vector_store`, `embedding_model`,
`retrieval_strategy`) are unaffected by the fix, since both dicts
share the same source content in the normal case.

`ruff check` and `mypy` on the changed file: clean.

## Tests

Existing tests (`test_day4_agents.py`, `test_gap_agents.py`,
`test_phase4_item4_record_learning_rollout.py`,
`test_day4_agent_contracts.py`, filtered to `rag`): 37 tests, all still
pass unchanged.

New file `tests/test_submit_rag_design_hardening.py`, 7 tests: schema
check, `CHAT_TOOLS` non-membership, an `AGENT_CONTRACT` proof
explaining why the write_file-scoping fix doesn't apply here, a
legitimate real-pipeline-code write-file regression, the
graph-enforced-result-takes-priority proof (the real fix), the
local-dict-fallback-still-works regression, and a proof normal content
fields are unaffected.

## Regression

This tool's own new hardening tests (7/7 pass) plus the existing
rag_engineer-related tests (37) + `test_new_tools.py` +
`test_final_session.py` — 422 passed total, 0 failed.

## Final verdict

**GREEN FLAG.** Real, proven priority-order defect found and fixed —
graph-enforced diagnostics (including a failing quality gate) were
silently dropped from `AgentResult.raw`. Fix verified live to restore
the correct, established precedence used by every sibling agent while
leaving normal-case content unaffected. write_file correctly confirmed
to need no scoping (this agent's genuine job is writing real pipeline
code). Zero functionality lost. Agent alignment verified: PASS.

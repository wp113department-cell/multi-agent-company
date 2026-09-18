# Tool #259 — `submit_release_notes` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_release_notes` lives in `app/agents/release_notes_agent.py`.
Deliberately NOT in `CHAT_TOOLS` (confirmed via membership check).

Checked and correctly RULED OUT the write_file-scoping finding class
already fixed on 15 sibling "read-only report writer" agents this run:
unlike those agents, `AGENT_CONTRACT` explicitly declares
`permissions=["read_repo", "write_repo"]` (not `write_docs`), and
`roles/release_notes_agent.md` has no "read-only on code" claim and no
Non-Responsibility against writing code. Confirmed live that
`write_file` to a real `.py` file succeeds — this is consistent with
the agent's own declared contract, not a contradiction, so no scoping
fix applies here.

## Problems found

Real, proven defect — identical class to sibling tool #258
(`submit_rag_design`): `run_release_notes_agent`'s own
`raw = submitted if submitted else final_state["result"]` had the
priority BACKWARDS relative to the correct, established pattern used
by every other `submit_*` agent in this codebase. Because the local
`submitted` closure dict is always truthy once a submission happens,
`raw` ALWAYS picked `submitted` and NEVER `final_state["result"]` —
silently dropping the graph-enforced diagnostic trail (`_quality_gate`,
`_citation_check`, `_validation_warning`) from `AgentResult.raw`.

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
fields (`version`, `highlights`) are unaffected.

`ruff check` and `mypy` on the changed file: clean.

## Tests

Existing tests (`test_day4_agents.py`, `test_gap52_doc_agent_auto_trigger.py`,
`test_gap_agents.py`, `test_phase4_item4_record_learning_rollout.py`,
`test_day2_tools.py`, `test_day4_agent_contracts.py`,
`test_generate_release_notes_hardening.py`, filtered to
`release_notes`/`release`): 54 tests, all still pass unchanged.

New file `tests/test_submit_release_notes_hardening.py`, 7 tests:
schema check, `CHAT_TOOLS` non-membership, an `AGENT_CONTRACT` proof
explaining why the write_file-scoping fix doesn't apply here, a
write_file regression matching the declared contract, the
graph-enforced-result-takes-priority proof (the real fix), the
local-dict-fallback-still-works regression, and a proof normal content
fields are unaffected.

## Regression

This tool's own new hardening tests (7/7 pass) plus the existing
release-notes-related tests (54) + `test_new_tools.py` +
`test_final_session.py` — 523 passed, 1 skipped, 2 failed.

The 2 failures
(`test_gap52_doc_agent_auto_trigger.py::test_run_once_dispatches_all_agents_on_first_run`
and `::test_run_once_skips_agent_whose_sha_is_unchanged`) are a
pre-existing environmental issue — `ConnectionRefusedError` on
`127.0.0.1:5432` (no local Postgres running in this environment).
Confirmed via `git stash` to fail identically on HEAD with zero local
changes — unrelated to this tool's fix.

## Final verdict

**GREEN FLAG.** Real, proven priority-order defect found and fixed —
identical class to sibling tool #258, graph-enforced diagnostics
(including a failing quality gate) were silently dropped from
`AgentResult.raw`. Fix verified live to restore the correct precedence
while leaving normal-case content unaffected. write_file correctly
confirmed to need no scoping (matches this agent's own declared
`write_repo` contract). Zero functionality lost. Agent alignment
verified: PASS.

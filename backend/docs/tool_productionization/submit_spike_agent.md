# Tool #264 — `submit_spike_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_spike_agent` lives in `app/agents/spike_agent.py`, same shape
as 20 sibling agents this run: `base = make_chat_handlers(repo_path)`
gives the agent's `write_file` full, unrestricted filesystem write
access. Deliberately NOT in `CHAT_TOOLS` (confirmed via membership
check). This is the config-driven confidence-gated-control-flow pilot
agent (`quality_gate_min_confidence_by_agent`) — unrelated to this
finding, left untouched.

`roles/spike_agent.md`'s Process section shares the same "reports,
specs, scripts, docs" write_file boilerplate already established (in
tool #261's `rollback_agent` report) to appear across 15 role files
and not be decisive on its own. This agent's own, non-boilerplate
signal: Non-Responsibilities say "Producing production code — spike
output is findings, not features", and `AGENT_CONTRACT` claims
`permissions=["read_repo", "write_docs"]` (never `"write_repo"`) with
`side_effects=["writes spike research reports"]` — the real, intended
output is a research report.

## Problems found

Real, severe finding, proved live before any fix:
`write_file({"path": "app/main.py", "content": "print(2)  # overwritten\n"})`
genuinely overwrote a real application `.py` file — full, unrestricted
filesystem write access, contradicting the agent's declared "findings,
not features" Non-Responsibility and its `write_docs`-only permission.

## Changes made

Added a `scoped_write_file` wrapper in `make_spike_agent_handlers()`
that only permits writes to paths ending in `.md` or starting with
`docs/`, returning a `[POLICY DENIED]` message otherwise — identical
pattern to the 20 sibling fixes this run.

Verified live, post-fix:
- `write_file({"path": "app/main.py", ...})` → `[POLICY DENIED]...`,
  file contents on disk confirmed unchanged.
- `write_file({"path": "SPIKE_REPORT.md", ...})` → `Written
  SPIKE_REPORT.md (8 bytes)` — legitimate report write succeeds.
- `write_file({"path": "docs/spike_report.md", ...})` → `Written
  docs/spike_report.md (8 bytes)` — legitimate docs write succeeds.

`ruff check` and `mypy` on the changed file: clean.

`submit_spike_agent` itself audited: `run_spike_agent` already has the
correct `raw = final_state["result"] if final_state["result"] else
result` priority, with its own dated comment from a prior audit pass
(MASTER_AGENT_v2.md Phase 3.4, 2026-07-28) — no change needed here.

## Tests

Existing tests (`test_role_file_tools_accuracy.py`,
`test_day6b_agents.py`, `test_confidence_gated_control_flow.py`,
`test_final_session.py`, `test_analyzer_tier_confirmed.py`,
`test_audit_q_batch09_large_project_file_tech.py`,
`test_record_learning_rollout.py`, `test_dead_contract_fix.py`,
`test_delegation.py`, `test_dynamic_tool_selection.py`, filtered to
`spike`): 27 tests, all still pass unchanged — including a real
end-to-end `test_real_delegation_to_spike_agent_end_to_end`, which
doesn't reference `write_file`.

New file `tests/test_submit_spike_agent_hardening.py`, 9 tests: schema
check, `CHAT_TOOLS` non-membership, an `AGENT_CONTRACT` write_docs-only
proof, real-code-file-write blocked with file-contents-unchanged
proof, arbitrary non-md/non-docs path blocked, legitimate
`SPIKE_REPORT.md` write regression, legitimate `docs/**` write
regression, worktree-escape-path still blocked, and a
`submit_spike_agent` accumulation regression.

## Regression

This tool's own new hardening tests (9/9 pass) plus the existing
spike-related tests (27) + `test_new_tools.py` — 534 passed, 2 failed.

The 2 failures
(`test_confidence_gated_control_flow.py::test_graph_low_confidence_creates_a_real_pending_approval_row`
and `::test_graph_default_threshold_creates_no_pending_approval_row`)
are the same pre-existing environmental issue already documented in
tool #259's turn — `ConnectionRefusedError` on `127.0.0.1:5432` (no
local Postgres running). Confirmed via `git stash` to fail identically
on HEAD with zero local changes — unrelated to this tool's fix.

## Final verdict

**GREEN FLAG.** Real, severe finding (unrestricted write_file
contradicting the agent's "findings, not features" Non-Responsibility
and declared `write_docs`-only permission) found and fixed. Fix
verified live to close the hole while preserving the agent's genuine
legitimate use case (spike report writes). Zero functionality lost.
Agent alignment verified: PASS.

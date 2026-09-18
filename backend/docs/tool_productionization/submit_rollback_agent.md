# Tool #261 — `submit_rollback_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_rollback_agent` lives in `app/agents/rollback_agent.py`, same
shape as 17 sibling agents this run: `base = make_chat_handlers(repo_path)`
gives the agent's `write_file` full, unrestricted filesystem write
access. Deliberately NOT in `CHAT_TOOLS` (confirmed via membership
check). Confirmed Analyzer-tier (no `edit_file`/`bash`) via
`tests/test_analyzer_tier_confirmed.py`.

`roles/rollback_agent.md`'s Process section says "Use write_file to
save any output files (reports, specs, scripts, docs)" — but this
exact phrase is shared boilerplate across 15 role files (checked via
grep), including several already correctly scoped down to `.md`/`docs/**`
this run (`pair_programmer_agent`, `localization_agent`,
`feature_flag_agent`, `env_checker_agent`, `incident_responder_agent`,
`infra_agent`) — so it is not, by itself, evidence of a genuine
agent-specific need to write code/scripts. The agent's own,
non-boilerplate signals point the other way: its Non-Responsibilities
list "Executing rollbacks — plans only, humans/ops execute", and
`AGENT_CONTRACT` claims `permissions=["read_repo", "write_docs"]`
(never `"write_repo"`) with `side_effects=["writes rollback plan
documents"]` — the real, intended output is a rollback PLAN document.

## Problems found

Real, severe finding, proved live before any fix:
`write_file({"path": "app/main.py", "content": "print(2)  # overwritten\n"})`
genuinely overwrote a real application `.py` file — full, unrestricted
filesystem write access, contradicting the agent's declared
`write_docs`-only permission and its "plans only" Non-Responsibility.

## Changes made

Added a `scoped_write_file` wrapper in `make_rollback_agent_handlers()`
that only permits writes to paths ending in `.md` or starting with
`docs/`, returning a `[POLICY DENIED]` message otherwise — identical
pattern to the 17 sibling fixes this run.

Verified live, post-fix:
- `write_file({"path": "app/main.py", ...})` → `[POLICY DENIED]...`,
  file contents on disk confirmed unchanged.
- `write_file({"path": "ROLLBACK_PLAN.md", ...})` → `Written
  ROLLBACK_PLAN.md (7 bytes)` — legitimate plan-document write
  succeeds.
- `write_file({"path": "docs/rollback_plan.md", ...})` → `Written
  docs/rollback_plan.md (16 bytes)` — legitimate docs write succeeds.

`ruff check` and `mypy` on the changed file: clean.

`submit_rollback_agent` itself audited: `run_rollback_agent` already
has the correct `raw = final_state["result"] if final_state["result"]
else result` priority, with its own dated comment from a prior audit
pass (MASTER_AGENT_v2.md Phase 3.4, 2026-07-28) — no change needed
here.

## Tests

Existing tests (`test_role_file_tools_accuracy.py`,
`test_day6b_agents.py`, `test_record_learning_rollout.py`,
`test_analyzer_tier_confirmed.py`, `test_dead_contract_fix.py`,
filtered to `rollback`): 20 tests, all still pass unchanged.

New file `tests/test_submit_rollback_agent_hardening.py`, 9 tests:
schema check, `CHAT_TOOLS` non-membership, an `AGENT_CONTRACT`
write_docs-only proof, real-code-file-write blocked with
file-contents-unchanged proof, a `.sh` script path blocked (the
boilerplate-implied but not actually intended output type),
legitimate `ROLLBACK_PLAN.md` write regression, legitimate `docs/**`
write regression, worktree-escape-path still blocked, and a
`submit_rollback_agent` accumulation regression.

## Regression

This tool's own new hardening tests (9/9 pass) plus the existing
rollback-related tests (20) + `test_new_tools.py` +
`test_final_session.py` — 451 passed total, 0 failed.

## Final verdict

**GREEN FLAG.** Real, severe finding (unrestricted write_file
contradicting the agent's declared `write_docs`-only permission and
"plans only" Non-Responsibility) found and fixed. Correctly
distinguished genuine per-agent intent from shared role-file
boilerplate before deciding to fix. Fix verified live to close the
hole while preserving the agent's genuine legitimate use case
(rollback-plan document writes). Zero functionality lost. Agent
alignment verified: PASS.

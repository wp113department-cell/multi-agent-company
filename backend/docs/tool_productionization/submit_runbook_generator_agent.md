# Tool #262 — `submit_runbook_generator_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_runbook_generator_agent` lives in
`app/agents/runbook_generator_agent.py`. Deliberately NOT in
`CHAT_TOOLS` (confirmed via membership check). This agent is "Editor
tier" per `tests/test_editor_tier.py` (alongside `onboarding_agent`,
tool #254) — it advertises BOTH `write_file` and `edit_file`, unlike
the single-tool sibling agents fixed earlier this run.

`roles/runbook_generator_agent.md`'s own Process says "Write the
runbook with write_file, or edit_file if updating an existing one",
and its Non-Responsibilities say "Executing operations — runbooks
only". `AGENT_CONTRACT` claims `permissions=["read_repo", "write_docs"]`
(never `"write_repo"`) with `side_effects=["writes operational
runbooks", "edits existing runbooks", "validates embedded YAML for
syntax"]` — every real output is a runbook document.

## Problems found

Real, severe finding, proved live before any fix: both a direct
`write_file({"path": "app/main.py", ...})` call AND a direct
`edit_file({"path": "app/main.py", ...})` call genuinely modified a
real application `.py` file — full, unrestricted filesystem write/edit
access on both tools, contradicting the agent's declared
`write_docs`-only permission and "runbooks only" Non-Responsibility.

## Changes made

Added `scoped_write_file` and `scoped_edit_file` wrappers in
`make_runbook_generator_agent_handlers()` (same dual-tool pattern as
tool #254's `onboarding_agent` fix) that only permit paths ending in
`.md` or starting with `docs/`, returning a `[POLICY DENIED]` message
otherwise on both tools.

Verified live, post-fix:
- `write_file({"path": "app/main.py", ...})` → `[POLICY DENIED]...`,
  file contents on disk confirmed unchanged.
- `edit_file({"path": "app/main.py", ...})` → `[POLICY DENIED]...`,
  file contents on disk confirmed unchanged.
- `write_file({"path": "docs/runbooks/deploy.md", ...})` → `Written
  docs/runbooks/deploy.md (17 bytes)` — legitimate runbook write
  succeeds.
- `edit_file({"path": "RUNBOOK_DEPLOY.md", ...})` → `Edited
  RUNBOOK_DEPLOY.md` — legitimate runbook edit succeeds.

`ruff check` and `mypy` on the changed file: clean.

`submit_runbook_generator_agent` itself audited: `run_runbook_generator_agent`
already has the correct `raw = final_state["result"] if
final_state["result"] else result` priority, with its own dated
comment from a prior audit pass (MASTER_AGENT_v2.md Phase 3.4,
2026-07-28) — no change needed here.

## Tests

Existing tests (`test_day6b_agents.py`, `test_analyzer_tier_confirmed.py`,
`test_final_session.py`, `test_phase3_verification_audit.py`,
`test_record_learning_rollout.py`, `test_dead_contract_fix.py`,
`test_phase35_per_tier_critique.py`, `test_editor_tier.py`, filtered to
`runbook`): 22 tests, all still pass unchanged —
`test_editor_tier.py`'s own assertions only check `edit_file` is
declared and callable, not that it's unrestricted, so the scoping fix
is fully compatible.

New file `tests/test_submit_runbook_generator_agent_hardening.py`, 9
tests: schema check, `CHAT_TOOLS` non-membership, an `AGENT_CONTRACT`
write_docs-only proof, real-code-file-write blocked (both tools) with
file-contents-unchanged proof, legitimate docs-runbook write
regression, legitimate runbook edit regression, worktree-escape-path
still blocked, and a `submit_runbook_generator_agent` accumulation
regression.

## Regression

This tool's own new hardening tests (9/9 pass) plus the existing
runbook-related tests (22) + `test_new_tools.py` — 458 passed total, 0
failed.

## Final verdict

**GREEN FLAG.** Real, severe finding (unrestricted write_file AND
edit_file contradicting the agent's declared `write_docs`-only
permission and "runbooks only" Non-Responsibility) found and fixed on
both tools. Fix verified live to close the hole while preserving the
agent's genuine legitimate use case (runbook document writes/edits).
Zero functionality lost. Agent alignment verified: PASS.

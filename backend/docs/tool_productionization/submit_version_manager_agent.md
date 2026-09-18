# Tool #272 — `submit_version_manager_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_version_manager_agent` lives in `app/agents/version_manager_agent.py`,
same shape as 25 sibling agents this run: `base =
make_chat_handlers(repo_path)` gives the agent's `write_file` full,
unrestricted filesystem write access. Deliberately NOT in `CHAT_TOOLS`
(confirmed via membership check). This agent also carries real
`git_tag`/`semver_bump` tools — already independently productionized
in earlier turns (tools #22 and #25, each with their own dedicated
audit report and hardening suite) — out of scope to re-touch here;
re-confirmed unaffected by this turn's fix.

`version_manager_agent` was on the earlier reconnaissance list of
candidate agents for this finding class — verified directly rather
than assumed. `roles/version_manager_agent.md`'s own Failure
Conditions state "Modifying, creating, or deleting any repo file (this
role is read-only on code)" and its Quality Gates require "Zero repo
files were modified" — the strongest, most explicit form of this
finding class, matching `localization_agent`'s/`test_coverage_agent`'s
exact phrasing. `AGENT_CONTRACT` claims `permissions=["read_repo",
"write_docs"]` with `side_effects=["writes version upgrade reports"]`.

## Problems found

Real, severe finding, proved live before any fix:
`write_file({"path": "app/main.py", "content": "print(2)  # overwritten\n"})`
genuinely overwrote a real application `.py` file — full, unrestricted
filesystem write access, directly contradicting the role's own
explicit "read-only on code" Failure Condition.

## Changes made

Added a `scoped_write_file` wrapper in
`make_version_manager_agent_handlers()` that only permits writes to
paths ending in `.md` or starting with `docs/`, returning a `[POLICY
DENIED]` message otherwise — identical pattern to the 25 sibling fixes
this run. `git_tag`/`semver_bump` are untouched.

Verified live, post-fix:
- `write_file({"path": "app/main.py", ...})` → `[POLICY DENIED]...`,
  file contents on disk confirmed unchanged.
- `write_file({"path": "requirements.txt", ...})` → `[POLICY
  DENIED]...` — a real dependency manifest file is correctly blocked
  too (directly relevant given this agent's whole job is reading
  requirements files, making it a plausible accidental-edit target).
- `write_file({"path": "UPGRADE_REPORT.md", ...})` → `Written
  UPGRADE_REPORT.md (11 bytes)` — legitimate report write succeeds.
- `write_file({"path": "docs/upgrade_report.md", ...})` → `Written
  docs/upgrade_report.md (11 bytes)` — legitimate docs write succeeds.
- `git_tag({"action": "list"})` still works exactly as before,
  confirming this fix didn't disturb it.

`ruff check` and `mypy` on the changed file: clean.

`submit_version_manager_agent` itself audited: `run_version_manager_agent`
already has the correct `raw = final_state["result"] if
final_state["result"] else result` priority, with its own dated
comment from a prior audit pass (MASTER_AGENT_v2.md Phase 3.4,
2026-07-28) — no change needed here.

## Tests

Existing tests (`test_role_file_tools_accuracy.py`,
`test_day6b_agents.py`, `test_final_session.py`,
`test_analyzer_tier_confirmed.py`, `test_record_learning_rollout.py`,
`test_dead_contract_fix.py`, `test_audit_q_batch14_extensibility_enterprise.py`,
`test_phase4_item5_git_awareness.py`, filtered to `version_manager`):
23 tests, all still pass unchanged.

New file `tests/test_submit_version_manager_agent_hardening.py`, 10
tests: schema check, `CHAT_TOOLS` non-membership, an `AGENT_CONTRACT`
write_docs-only proof, real-code-file-write blocked with
file-contents-unchanged proof, a real `requirements.txt` write blocked,
legitimate `UPGRADE_REPORT.md` write regression, legitimate `docs/**`
write regression, worktree-escape-path still blocked, a
`git_tag`-unaffected regression, and a `submit_version_manager_agent`
accumulation regression.

## Regression

This tool's own new hardening tests (10/10 pass) plus the existing
version-manager-related tests (23) + `test_new_tools.py` — 483 passed,
4 failed. The 4 failures
(`test_audit_q_batch14_extensibility_enterprise.py`'s repo-scoping and
credential-vault tests) are the same pre-existing `ConnectionRefusedError`
on `127.0.0.1:5432` environmental issue already documented on tools
#259/#264/#265/#267 (no local Postgres running). Confirmed via `git
stash` to fail identically on HEAD with zero local changes.

## Final verdict

**GREEN FLAG.** Real, severe finding (unrestricted write_file directly
contradicting the role's own explicit "read-only on code" Failure
Condition) found and fixed. Fix verified live to close the hole while
preserving the agent's genuine legitimate use case (upgrade-report
writes) and leaving the already-productionized `git_tag`/`semver_bump`
tools untouched. Zero functionality lost. Agent alignment verified:
PASS.

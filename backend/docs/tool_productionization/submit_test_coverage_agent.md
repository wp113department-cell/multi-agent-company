# Tool #267 — `submit_test_coverage_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_test_coverage_agent` lives in `app/agents/test_coverage_agent.py`,
same shape as 22 sibling agents this run: `base =
make_chat_handlers(repo_path)` gives the agent's `write_file` full,
unrestricted filesystem write access. Deliberately NOT in `CHAT_TOOLS`
(confirmed via membership check). This agent is the documented
"read-only Executor variant" — its `bash` tool is already correctly
scoped to `make_test_runner_bash_handler` (coverage-tooling-only, not
a general shell escape) — verified untouched by this fix.

`roles/test_coverage_agent.md`'s own Failure Conditions state
"Modifying, creating, or deleting any repo file (this role is
read-only on code)" and its Quality Gates require "Zero repo files
were modified" — the strongest, most explicit form of this finding
class, matching `localization_agent`'s exact phrasing. `AGENT_CONTRACT`
claims `permissions=["read_repo", "write_docs", "execute_tests"]` and
its own `side_effects` explicitly say "runs coverage tooling ... —
never writes code".

## Problems found

Real, severe finding, proved live before any fix:
`write_file({"path": "app/main.py", "content": "print(2)  # overwritten\n"})`
genuinely overwrote a real application `.py` file — full, unrestricted
filesystem write access, directly contradicting the role's own
explicit "read-only on code" Failure Condition.

## Changes made

Added a `scoped_write_file` wrapper in
`make_test_coverage_agent_handlers()` that only permits writes to
paths ending in `.md` or starting with `docs/`, returning a `[POLICY
DENIED]` message otherwise — identical pattern to the 22 sibling fixes
this run. `bash` (already correctly scoped to
`make_test_runner_bash_handler`) is untouched.

Verified live, post-fix:
- `write_file({"path": "app/main.py", ...})` → `[POLICY DENIED]...`,
  file contents on disk confirmed unchanged.
- `write_file({"path": "COVERAGE_GAPS.md", ...})` → `Written
  COVERAGE_GAPS.md (7 bytes)` — legitimate gap-report write succeeds.
- `write_file({"path": "docs/coverage_gaps.md", ...})` → `Written
  docs/coverage_gaps.md (7 bytes)` — legitimate docs write succeeds.

`ruff check` and `mypy` on the changed file: clean.

`submit_test_coverage_agent` itself audited: `run_test_coverage_agent`
already has the correct `raw = final_state["result"] if
final_state["result"] else result` priority, with its own dated
comment from a prior audit pass (MASTER_AGENT_v2.md Phase 3.4,
2026-07-28) — no change needed here.

## Tests

Existing tests (`test_day6b_agents.py`, `test_analyzer_tier_confirmed.py`,
`test_final_session.py`, `test_phase3_verification_audit.py`,
`test_phase34_real_output_verification.py`, `test_dead_contract_fix.py`,
`test_stage4_cluster_q_test_coverage_pct.py`,
`test_record_learning_rollout.py`, `test_executor_tier_bash.py`,
filtered to `test_coverage`): 31 tests pass unchanged, 2 fail
(`test_stage4_cluster_q_test_coverage_pct.py`'s two DB-dependent
end-to-end tests) — the same pre-existing `ConnectionRefusedError` on
`127.0.0.1:5432` environmental issue already documented on tools
#259/#264/#265 (no local Postgres running). Confirmed via `git stash`
to fail identically on HEAD with zero local changes.

New file `tests/test_submit_test_coverage_agent_hardening.py`, 10
tests: schema check, `CHAT_TOOLS` non-membership, an `AGENT_CONTRACT`
"never writes code" proof, real-code-file-write blocked with
file-contents-unchanged proof, arbitrary non-md/non-docs path blocked,
legitimate `COVERAGE_GAPS.md` write regression, legitimate `docs/**`
write regression, worktree-escape-path still blocked, a
bash-still-scoped-to-test-runner regression, and a
`submit_test_coverage_agent` accumulation regression.

## Regression

This tool's own new hardening tests (10/10 pass) plus the existing
test-coverage-related tests (31 pass, 2 pre-existing DB failures) +
`test_new_tools.py` — 475 passed, 1 failed
(`test_executor_tier_bash.py::TestTestRunnerBashHandler::test_allows_pytest`,
the same confirmed pre-existing docker-precheck call-count mismatch
first documented on tool #243's turn — unrelated to any of my changes).

## Final verdict

**GREEN FLAG.** Real, severe finding (unrestricted write_file directly
contradicting the role's own explicit "read-only on code" Failure
Condition) found and fixed. Fix verified live to close the hole while
preserving the agent's genuine legitimate use case (coverage-gap
report writes) and leaving the already-scoped `bash` tool untouched.
Zero functionality lost. Agent alignment verified: PASS.

# Tool #263 — `submit_slo_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_slo_agent` lives in `app/agents/slo_agent.py`, same shape as
19 sibling agents this run: `base = make_chat_handlers(repo_path)`
gives the agent's `write_file` full, unrestricted filesystem write
access. Deliberately NOT in `CHAT_TOOLS` (confirmed via membership
check). Confirmed Analyzer-tier (no `edit_file`/`bash`) via
`tests/test_analyzer_tier_confirmed.py`.

`roles/slo_agent.md`'s Process section shares the same "reports,
specs, scripts, docs" write_file boilerplate already established (in
tool #261's `rollback_agent` report) to appear across 15 role files
and not be decisive on its own. This agent's own, non-boilerplate
signals: Non-Responsibilities say "Modifying monitoring config" is out
of scope, and `AGENT_CONTRACT` claims `permissions=["read_repo",
"write_docs"]` (never `"write_repo"`) with `side_effects=["writes SLO
specification documents"]` — the real, intended output is a spec
document.

## Problems found

Real, severe finding, proved live before any fix:
`write_file({"path": "app/main.py", "content": "print(2)  # overwritten\n"})`
genuinely overwrote a real application `.py` file — full, unrestricted
filesystem write access, contradicting the agent's declared
`write_docs`-only permission.

## Changes made

Added a `scoped_write_file` wrapper in `make_slo_agent_handlers()`
that only permits writes to paths ending in `.md` or starting with
`docs/`, returning a `[POLICY DENIED]` message otherwise — identical
pattern to the 19 sibling fixes this run.

Verified live, post-fix:
- `write_file({"path": "app/main.py", ...})` → `[POLICY DENIED]...`,
  file contents on disk confirmed unchanged.
- `write_file({"path": "SLO_SPEC.md", ...})` → `Written SLO_SPEC.md (7
  bytes)` — legitimate spec-document write succeeds.
- `write_file({"path": "docs/slo_spec.md", ...})` → `Written
  docs/slo_spec.md (7 bytes)` — legitimate docs write succeeds.

`ruff check` and `mypy` on the changed file: clean.

`submit_slo_agent` itself audited: `run_slo_agent` already has the
correct `raw = final_state["result"] if final_state["result"] else
result` priority, with its own dated comment from a prior audit pass
(MASTER_AGENT_v2.md Phase 3.4, 2026-07-28) — no change needed here.

## Tests

Existing tests (`test_role_file_tools_accuracy.py`,
`test_day6b_agents.py`, `test_analyzer_tier_confirmed.py`,
`test_final_session.py`, `test_record_learning_rollout.py`,
`test_dead_contract_fix.py`, filtered to `slo`): 20 tests, all still
pass unchanged.

New file `tests/test_submit_slo_agent_hardening.py`, 9 tests: schema
check, `CHAT_TOOLS` non-membership, an `AGENT_CONTRACT` write_docs-only
proof, real-code-file-write blocked with file-contents-unchanged
proof, a monitoring-config-path blocked proof (the explicit
Non-Responsibility), legitimate `SLO_SPEC.md` write regression,
legitimate `docs/**` write regression, worktree-escape-path still
blocked, and a `submit_slo_agent` accumulation regression.

## Regression

This tool's own new hardening tests (9/9 pass) plus the existing
slo-related tests (20) + `test_new_tools.py` — 451 passed total, 0
failed.

## Final verdict

**GREEN FLAG.** Real, severe finding (unrestricted write_file
contradicting the agent's declared `write_docs`-only permission) found
and fixed. Fix verified live to close the hole while preserving the
agent's genuine legitimate use case (SLO spec document writes). Zero
functionality lost. Agent alignment verified: PASS.

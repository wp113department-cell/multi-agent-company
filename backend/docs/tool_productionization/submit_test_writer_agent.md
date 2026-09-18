# Tool #268 — `submit_test_writer_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_test_writer_agent` lives in `app/agents/test_writer_agent.py`.
Deliberately NOT in `CHAT_TOOLS` (confirmed via membership check).
This is an Executor-tier agent (per `MASTER_AGENT_v2.md`'s tier audit)
— `bash` is already correctly scoped to `make_test_runner_bash_handler`
(test-runner-only, not general shell), verified untouched.

`AGENT_CONTRACT` declares `permissions=["read_repo", "write_code",
"execute_tests"]` — unlike the 22 write_docs-only sibling agents fixed
earlier this run, this agent's whole job genuinely is writing NEW real
test code files, so a blanket `.md`/`docs/**` scope would be wrong
here. However, `roles/test_writer_agent.md`'s own Non-Responsibilities
explicitly forbid "Changing application code to make it testable —
report testability blockers instead."

## Problems found

A distinct variant of the write_file finding class: nothing enforced
the "don't change application code" Non-Responsibility. Proved live
before any fix: `write_file({"path": "app/main.py", "content": "def add(a, b): return 999\n"})`
genuinely overwrote real, non-test application source.

## Changes made

Added a `scoped_write_file` wrapper in `make_test_writer_agent_handlers()`
that only permits writes to actual test-file paths, grounded in this
repo's own real conventions (not an invented rule):
- Confirmed via `backend/pytest.ini`'s `testpaths = tests` (no
  `python_files` override) that pytest's default discovery applies:
  `test_*.py` / `*_test.py`, or anything under `tests/`.
- Confirmed via `apps/web/vitest.config.ts`'s own `include:
  ["**/*.test.{ts,tsx}"]` glob, plus Jest's well-known default
  `testMatch` (which also covers `.spec.*`), that `.test.[jt]sx?` and
  `.spec.[jt]sx?` are the real frontend test-naming conventions.

Verified live, post-fix:
- `write_file({"path": "app/main.py", ...})` → `[POLICY DENIED]...`,
  file contents on disk confirmed unchanged.
- `write_file({"path": "random_helper.py", ...})` → `[POLICY
  DENIED]...` — a random non-test `.py` file is correctly blocked too.
- `write_file({"path": "tests/test_main.py", ...})` → `Written` —
  legitimate.
- `write_file({"path": "test_something.py", ...})` → `Written` —
  legitimate (pytest prefix convention).
- `write_file({"path": "something_test.py", ...})` → `Written` —
  legitimate (pytest suffix convention).
- `write_file({"path": "apps/web/components/Button.test.tsx", ...})` →
  `Written` — legitimate (Vitest convention).
- `write_file({"path": "apps/web/components/Button.spec.ts", ...})` →
  `Written` — legitimate (Jest convention).

`ruff check` and `mypy` on the changed file: clean.

`submit_test_writer_agent` itself audited: `run_test_writer_agent`
already has the correct `raw = final_state["result"] if
final_state["result"] else result` priority, with its own dated
comment from a prior audit pass (MASTER_AGENT_v2.md Phase 3.4,
2026-07-28) — no change needed here.

## Tests

Existing tests (`test_analyzer_tier_confirmed.py`,
`test_day6b_agents.py`, `test_final_session.py`,
`test_phase3_verification_audit.py`, `test_record_learning_rollout.py`,
`test_executor_tier_bash.py`, `test_phase34_real_output_verification.py`,
`test_dead_contract_fix.py`, filtered to `test_writer`): 23 tests, all
still pass unchanged.

New file `tests/test_submit_test_writer_agent_hardening.py`, 13 tests:
schema check, `CHAT_TOOLS` non-membership, an `AGENT_CONTRACT`
write_code proof explaining why the blanket sibling fix doesn't apply,
application-code-write blocked with file-contents-unchanged proof, a
random non-test `.py` file blocked, five legitimate test-path-pattern
regressions (`tests/**`, `test_*.py`, `*_test.py`, `*.test.tsx`,
`*.spec.ts`), worktree-escape-path still blocked, a
bash-still-scoped-to-test-runner regression, and a
`submit_test_writer_agent` accumulation regression.

## Regression

This tool's own new hardening tests (13/13 pass) plus the existing
test-writer-related tests (23) + `test_new_tools.py` — 478 passed, 1
failed (`test_executor_tier_bash.py::TestTestRunnerBashHandler::test_allows_pytest`,
the same confirmed pre-existing docker-precheck call-count mismatch
first documented on tool #243's turn — unrelated to any of my
changes).

## Final verdict

**GREEN FLAG.** Real, provable defect (write_file could overwrite
application code, directly contradicting this agent's own
Non-Responsibility) found and fixed with a scope grounded in this
repo's actual test-discovery conventions rather than a blanket
restriction — fully preserving the agent's genuine, broad legitimate
use case (writing pytest/Jest/Vitest test files anywhere in the repo)
while blocking exactly the forbidden behavior. Zero functionality
lost. Agent alignment verified: PASS.

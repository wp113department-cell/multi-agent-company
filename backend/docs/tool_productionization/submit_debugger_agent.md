# Tool #243 — `submit_debugger_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_debugger_agent` lives entirely in `app/agents/debugger_agent.py`
(not to be confused with the fleet self-improvement agent
`agent_debugger.py`, a different file), structurally similar to
sibling agents already fixed for the same finding class:
`accessibility_agent.py` (#231), `agentic_ai_architect.py` (#232),
`code_explainer_agent.py` (#237), `code_quality_agent.py` (#238),
`compliance_agent.py` (#239), `cost_estimator_agent.py` (#240). Shared
by exactly 1 real agent, confirmed via direct grep —
`debugger_agent` itself — matching `tool_inventory.json`'s
`agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` (confirmed
via membership check).

`submit_h` audited against the dead-accumulator distinction and found
correct: `run_debugger_agent()`'s
`raw = final_state["result"] if final_state["result"] else result`
line already prioritizes the real, graph-enforced capture, matching
the exact pattern already confirmed live (not dead) on sibling agents.

`bash` was already correctly scoped to `make_test_runner_bash_handler`
(overriding the base's unrestricted chat-agent `bash` with a
pytest/npm-test/jest/vitest-only variant) — verified still in place,
not touched.

## Problems found

The exact same real, severe finding already found and fixed on 6
sibling tools: `roles/debugger_agent.md` states **"this role is
read-only on code"** as a Failure Condition (*"Modifying, creating, or
deleting any repo file"*) and Quality Gate (*"Zero repo files were
modified"*), and `AGENT_CONTRACT` claims `side_effects=["writes debug
analysis .md reports", "runs test commands to reproduce"]` and
`permissions=["read_repo", "write_docs", "execute_tests"]`. But
`make_debugger_agent_handlers()` built its handler dict from
`base = make_chat_handlers(repo_path)` without restricting
`write_file` — giving this agent the full, unrestricted chat-agent
`write_file`, able to write to **any** path in the repo, including
real source code.

Proved live, before any fix:

```python
handlers = make_debugger_agent_handlers(tmp)
handlers["write_file"]({"path": "app/main.py", "content": "print(2)  # overwritten\n"})
# → "Written app/main.py (24 bytes)" — the real .py file was overwritten
```

Also noted, not touched (confirmed pre-existing and unrelated via
`git stash` — reproduces identically at HEAD with zero local changes):
`tests/test_executor_tier_bash.py::TestTestRunnerBashHandler::test_allows_pytest`
fails because the real `_run_bash_command`'s Docker sandbox path
issues a `docker version` pre-check call the test's mock assertion
(`assert_called_once`) doesn't account for — a real, separate,
pre-existing test-vs-implementation mismatch in a different tool's
own test suite, out of scope for this turn.

## Changes made

Overrode `write_file` in `make_debugger_agent_handlers()` with the
same `scoped_write_file` pattern already established for the 6 sibling
agents: any path that doesn't end in `.md` or start with `docs/` is
rejected with a clean `"[POLICY DENIED] debugger_agent may only write
.md files or paths under docs/ — this role is read-only on code."`
message; legal paths delegate to the original, unscoped `write_file`
(captured before reassignment, avoiding self-recursion). Entirely
local to `debugger_agent.py` — no shared function touched, `bash`
untouched, no other agent affected. The underlying `write_file`'s own
worktree-escape protection still runs beneath the new scoping,
re-verified live.

## Tests

Existing tests across the relevant files (`test_day5b_agents.py`,
`test_phase35_per_tier_critique.py`, `test_dead_contract_fix.py`,
`test_record_learning_rollout.py`) re-run and confirmed passing
unchanged (18 debugger_agent-related tests).

New file `tests/test_submit_debugger_agent_hardening.py`, 9 tests:
schema check, `CHAT_TOOLS` non-membership, the
real-code-file-write-blocked proof (with file-contents-unchanged
assertion), a non-`.md`/non-`docs/` path rejection, two legitimate-write
regressions, a worktree-escape-still-blocked regression, a
regression confirming `bash` is still the scoped test-runner handler
(not the unrestricted chat-agent bash), and a
`submit_debugger_agent` accumulation regression.

## Regression

This tool's own new hardening tests (9/9 pass) plus the 4 relevant
existing test files (18 tests) + `test_new_tools.py` +
`test_final_session.py` (295 passed total).

Verified via `mypy app/agents/debugger_agent.py` (clean) and `ruff
check` (clean) BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The same real, severe scope-boundary violation class
found on 6 sibling tools found and fixed here too, via evidence (live
reproduction of an unrestricted code-file write before the fix, live
proof of correct scoping after). `submit_debugger_agent` itself and
the already-correct `bash` scoping both audited and confirmed correct.
No functionality lost — legitimate debug-report writing to
`.md`/`docs/**` paths still works exactly as before. Agent alignment
verified: PASS.

# Tool #237 — `submit_code_explainer_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_code_explainer_agent` lives entirely in
`app/agents/code_explainer_agent.py`, structurally near-identical to
sibling agents `accessibility_agent.py` (tool #231) and
`agentic_ai_architect.py` (tool #232), both fixed in earlier turns for
the same class of finding. Shared by exactly 1 real agent, confirmed
via direct grep — `code_explainer_agent` itself — matching
`tool_inventory.json`'s `agent_count: 1` exactly. Deliberately NOT in
`CHAT_TOOLS` (confirmed via membership check).

`submit_h` audited against the dead-accumulator distinction and found
correct: `run_code_explainer_agent()`'s
`raw = final_state["result"] if final_state["result"] else result`
line already prioritizes the real, graph-enforced capture, matching
the exact pattern already confirmed live (not dead) on sibling agents.

## Problems found

The exact same real, severe finding already found and fixed on
sibling tools #231/#232: `roles/code_explainer_agent.md` — this
agent's own system prompt — states **"this role is read-only on
code"** as a Failure Condition (*"Modifying, creating, or deleting any
repo file"*) and Quality Gate (*"Zero repo files were modified"*), and
`AGENT_CONTRACT` claims `side_effects=["writes .md explanation
files"]` and `permissions=["read_repo", "write_docs"]`. But
`make_code_explainer_agent_handlers()` built its handler dict from
`base = make_chat_handlers(repo_path)` without restricting
`write_file` — giving this agent the full, unrestricted chat-agent
`write_file`, able to write to **any** path in the repo, including
real source code.

Proved live, before any fix:

```python
handlers = make_code_explainer_agent_handlers(tmp)
handlers["write_file"]({"path": "app/main.py", "content": "print(2)  # overwritten\n"})
# → "Written app/main.py (24 bytes)" — the real .py file was overwritten
```

## Changes made

Overrode `write_file` in `make_code_explainer_agent_handlers()` with
the same `scoped_write_file` pattern already established for
`accessibility_agent`/`agentic_ai_architect`: any path that doesn't
end in `.md` or start with `docs/` is rejected with a clean
`"[POLICY DENIED] code_explainer_agent may only write .md files or
paths under docs/ — this role is read-only on code."` message; legal
paths delegate to the original, unscoped `write_file` (captured before
reassignment, avoiding self-recursion). Entirely local to
`code_explainer_agent.py` — no shared function touched, no other
agent affected. The underlying `write_file`'s own worktree-escape
protection still runs beneath the new scoping, re-verified live.

## Tests

Existing tests across 5 files
(`test_analyzer_tier_confirmed.py`, `test_day5b_agents.py`,
`test_dead_contract_fix.py`, `test_record_learning_rollout.py`,
`test_role_file_tools_accuracy.py`) re-run and confirmed passing
unchanged (20 code_explainer_agent-related tests).

New file `tests/test_submit_code_explainer_agent_hardening.py`, 8
tests: schema check, `CHAT_TOOLS` non-membership, the
real-code-file-write-blocked proof (with file-contents-unchanged
assertion), a non-`.md`/non-`docs/` path rejection, two legitimate-write
regressions, a worktree-escape-still-blocked regression, and a
`submit_code_explainer_agent` accumulation regression.

## Regression

This tool's own new hardening tests (8/8 pass) plus the 5 existing
test files (20 tests) + `test_new_tools.py` + `test_final_session.py`
(342 passed total).

Verified via `mypy app/agents/code_explainer_agent.py` (clean) and
`ruff check` (clean) BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The same real, severe scope-boundary violation class
found on tools #231/#232 found and fixed here too, via evidence (live
reproduction of an unrestricted code-file write before the fix, live
proof of correct scoping after). `submit_code_explainer_agent` itself
audited and confirmed correct. No functionality lost — legitimate
explanation-doc writing to `.md`/`docs/**` paths still works exactly
as before. Agent alignment verified: PASS.

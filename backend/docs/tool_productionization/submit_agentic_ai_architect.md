# Tool #232 — `submit_agentic_ai_architect` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_agentic_ai_architect` lives entirely in
`app/agents/agentic_ai_architect.py`, structurally near-identical to
sibling agent `accessibility_agent.py` (tool #231, fixed in the
immediately preceding turn). Shared by exactly 1 real agent, confirmed
via direct grep — `agentic_ai_architect` itself — matching
`tool_inventory.json`'s `agent_count: 1` exactly. Deliberately NOT in
`CHAT_TOOLS` (confirmed via membership check).

`submit_h` audited against the dead-accumulator distinction and found
correct: `run_agentic_ai_architect()`'s
`raw = final_state["result"] if final_state["result"] else result`
line already prioritizes the real, graph-enforced capture, matching
the exact pattern already confirmed live (not dead) on the sibling
agent's turn.

## Problems found

The exact same real, severe finding already found and fixed on
sibling tool #231 (`accessibility_agent`): `roles/agentic_ai_architect.md`
— this agent's own system prompt — states **"Zero repo files modified
(design-only role)"** as an explicit Quality Gate, and `AGENT_CONTRACT`
claims `side_effects=["writes agentic system design docs"]` and
`permissions=["read_repo", "write_docs"]`. But
`make_agentic_ai_architect_handlers()` built its handler dict from
`base = make_chat_handlers(repo_path)` without restricting
`write_file` — giving this agent the full, unrestricted chat-agent
`write_file`, able to write to **any** path in the repo, including
real source code.

Proved live, before any fix:

```python
handlers = make_agentic_ai_architect_handlers(tmp)
handlers["write_file"]({"path": "app/main.py", "content": "print(2)  # overwritten\n"})
# → "Written app/main.py (24 bytes)" — the real .py file was overwritten
```

## Changes made

Overrode `write_file` in `make_agentic_ai_architect_handlers()` with
the same `scoped_write_file` pattern just established for
`accessibility_agent`: any path that doesn't end in `.md` or start
with `docs/` is rejected with a clean
`"[POLICY DENIED] agentic_ai_architect may only write .md files or
paths under docs/ — this is a design-only role."` message; legal
paths delegate to the original, unscoped `write_file` (captured before
reassignment, avoiding self-recursion). Entirely local to
`agentic_ai_architect.py` — no shared function touched, no other agent
affected. The underlying `write_file`'s own worktree-escape protection
still runs beneath the new scoping, re-verified live.

## Tests

Existing tests across 2 files (`test_batch17_agents.py`,
`test_day8_role_prompts.py`) re-run and confirmed passing unchanged
(14 agentic_ai_architect-related tests).

New file `tests/test_submit_agentic_ai_architect_hardening.py`, 8
tests: schema check, `CHAT_TOOLS` non-membership, the
real-code-file-write-blocked proof (with file-contents-unchanged
assertion), a non-`.md`/non-`docs/` path rejection, two legitimate-write
regressions, a worktree-escape-still-blocked regression, and a
`submit_agentic_ai_architect` accumulation regression.

## Regression

This tool's own new hardening tests (8/8 pass) plus the 2 existing
test files (14 tests) + `test_submit_accessibility_agent_hardening.py`
+ `test_new_tools.py` + `test_final_session.py` (353 passed total).

Verified via `mypy app/agents/agentic_ai_architect.py` (clean) and
`ruff check` (clean) BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The same real, severe scope-boundary violation class
found on tool #231 found and fixed here too, via evidence (live
reproduction of an unrestricted code-file write before the fix, live
proof of correct scoping after). `submit_agentic_ai_architect` itself
audited and confirmed correct. No functionality lost — legitimate
design-doc writing to `.md`/`docs/**` paths still works exactly as
before. Agent alignment verified: PASS.

**Note for future turns**: this same "design/audit-only agent given
an unrestricted `write_file` via `make_chat_handlers()`, contradicting
its own role prompt's docs-only claim" pattern may exist on other
similarly-shaped agents not yet reached in the tracking table — worth
checking specifically when auditing any other `submit_*` tool whose
agent's role file makes a "read-only"/"design-only"/"docs-only" claim.

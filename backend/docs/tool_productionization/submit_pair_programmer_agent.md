# Tool #255 — `submit_pair_programmer_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_pair_programmer_agent` lives entirely in
`app/agents/pair_programmer_agent.py`. Shared by exactly 1 real agent,
confirmed via direct grep — `pair_programmer_agent` itself — matching
`tool_inventory.json`'s `agent_count: 1` exactly. Deliberately NOT in
`CHAT_TOOLS` (confirmed via membership check).

`submit_h` audited against the dead-accumulator distinction and found
correct: `run_pair_programmer_agent()`'s
`raw = final_state["result"] if final_state["result"] else result`
line already prioritizes the real, graph-enforced capture, matching
the exact pattern already confirmed live (not dead) on sibling agents.

## Problems found

Unlike the 14 already-fixed sibling agents, `roles/pair_programmer_agent.md`
does **not** contain the exact phrase "read-only on code" — this
required extra investigation before concluding the same finding class
applies here. The decisive evidence: `tests/test_analyzer_tier_confirmed.py`
— this codebase's own authoritative, already-locked-in classification
test (a real regression test, not documentation) — explicitly lists
`pair_programmer_agent` among its `ANALYZER_TIER_AGENTS`: agents whose
role "explicitly excludes editing/fixing/modifying real code,"
confirmed by that same test's own real assertion
(`test_analyzer_tier_agent_has_no_edit_or_bash`) that these agents
carry no `edit_file` or `bash` tool at all. `AGENT_CONTRACT` matches
that intent: `permissions=["read_repo", "write_docs"]` (never
`"write_repo"`), and `side_effects=["writes code suggestions and
implementation guides"]` — an output artifact, not a direct edit of
the driver's real files (this agent doesn't even have `edit_file`,
only a single-shot `write_file`).

But `make_pair_programmer_agent_handlers()` built its handler dict
from `base = make_chat_handlers(repo_path)` without restricting
`write_file` — giving this agent the full, unrestricted chat-agent
`write_file`, able to write to **any** path in the repo, including
real source code.

Proved live, before any fix:

```python
handlers = make_pair_programmer_agent_handlers(tmp)
handlers["write_file"]({"path": "app/main.py", "content": "print(2)  # overwritten\n"})
# → "Written app/main.py (24 bytes)" — the real .py file was overwritten
```

## Changes made

Overrode `write_file` in `make_pair_programmer_agent_handlers()` with
the same `scoped_write_file` pattern already established for the 14
sibling agents: any path that doesn't end in `.md` or start with
`docs/` is rejected with a clean `"[POLICY DENIED]
pair_programmer_agent may only write .md files or paths under docs/ —
this Analyzer-tier role guides implementation, it never edits the
driver's real files directly."` message; legal paths delegate to the
original, unscoped `write_file` (captured before reassignment,
avoiding self-recursion). Entirely local to
`pair_programmer_agent.py` — no shared function touched, no other
agent affected. The underlying `write_file`'s own worktree-escape
protection still runs beneath the new scoping, re-verified live.

## Tests

Existing tests across 5 files (`test_analyzer_tier_confirmed.py`,
`test_day6b_agents.py`, `test_dead_contract_fix.py`,
`test_record_learning_rollout.py`, `test_role_file_tools_accuracy.py`)
re-run and confirmed passing unchanged (20 pair_programmer_agent-related
tests, plus the full 35-test `test_analyzer_tier_confirmed.py` file
re-run separately to confirm the Analyzer-tier classification this fix
relies on is still locked in).

New file `tests/test_submit_pair_programmer_agent_hardening.py`, 9
tests: schema check, `CHAT_TOOLS` non-membership, a re-confirmation
that this agent's real tool list still has no `edit_file`/`bash`
(the authoritative classification this fix depends on), the
real-code-file-write-blocked proof (with file-contents-unchanged
assertion), a non-`.md`/non-`docs/` path rejection, two
legitimate-write regressions, a worktree-escape-still-blocked
regression, and a `submit_pair_programmer_agent` accumulation
regression.

## Regression

This tool's own new hardening tests (9/9 pass) plus the 5 existing
test files (20 tests) + the full `test_analyzer_tier_confirmed.py` (35
tests) + `test_new_tools.py` + `test_final_session.py` (451 passed
total).

Verified via `mypy app/agents/pair_programmer_agent.py` (clean) and
`ruff check` (clean) BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The same real, severe scope-boundary violation class
found on 14 sibling tools found and fixed here too — this time
requiring corroborating evidence from the codebase's own authoritative
classification test rather than an explicit phrase in the role file,
since this agent's prose alone was genuinely ambiguous. Fixed via
evidence (live reproduction of an unrestricted code-file write before
the fix, live proof of correct scoping after).
`submit_pair_programmer_agent` itself audited and confirmed correct.
No functionality lost — legitimate suggestion/guide writing to
`.md`/`docs/**` paths still works exactly as before. Agent alignment
verified: PASS.

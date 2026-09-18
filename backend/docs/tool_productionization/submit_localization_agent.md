# Tool #252 — `submit_localization_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_localization_agent` lives entirely in
`app/agents/localization_agent.py`, structurally near-identical to
sibling agents already fixed for the same finding class:
`accessibility_agent.py` (#231), `agentic_ai_architect.py` (#232),
`code_explainer_agent.py` (#237), `code_quality_agent.py` (#238),
`compliance_agent.py` (#239), `cost_estimator_agent.py` (#240),
`debugger_agent.py` (#243), `dependency_security_agent.py` (#244),
`devex_agent.py` (#245), `env_checker_agent.py` (#246),
`feature_flag_agent.py` (#248), `incident_responder_agent.py` (#249),
`infra_agent.py` (#250). Shared by exactly 1 real agent, confirmed via
direct grep — `localization_agent` itself — matching
`tool_inventory.json`'s `agent_count: 1` exactly. Deliberately NOT in
`CHAT_TOOLS` (confirmed via membership check).

`submit_h` audited against the dead-accumulator distinction and found
correct: `run_localization_agent()`'s
`raw = final_state["result"] if final_state["result"] else result`
line already prioritizes the real, graph-enforced capture, matching
the exact pattern already confirmed live (not dead) on sibling agents.

## Problems found

The exact same real, severe finding already found and fixed on 13
sibling tools: `roles/localization_agent.md` states, twice, **"this
role is read-only on code"** — once directly in its own Tools section
(*"No edit_file — this role is read-only on code (see
Non-Responsibilities)"*) and once as a Failure Condition
(*"Modifying, creating, or deleting any repo file"*) plus Quality Gate
(*"Zero repo files were modified"*) — and `AGENT_CONTRACT` claims
`side_effects=["writes i18n audit reports"]` and
`permissions=["read_repo", "write_docs"]`. But
`make_localization_agent_handlers()` built its handler dict from
`base = make_chat_handlers(repo_path)` without restricting
`write_file` — giving this agent the full, unrestricted chat-agent
`write_file`, able to write to **any** path in the repo, including
real source code.

Proved live, before any fix:

```python
handlers = make_localization_agent_handlers(tmp)
handlers["write_file"]({"path": "app/main.py", "content": "print(2)  # overwritten\n"})
# → "Written app/main.py (24 bytes)" — the real .py file was overwritten
```

## Changes made

Overrode `write_file` in `make_localization_agent_handlers()` with the
same `scoped_write_file` pattern already established for the 13
sibling agents: any path that doesn't end in `.md` or start with
`docs/` is rejected with a clean `"[POLICY DENIED]
localization_agent may only write .md files or paths under docs/ —
this role is read-only on code."` message; legal paths delegate to
the original, unscoped `write_file` (captured before reassignment,
avoiding self-recursion). Entirely local to `localization_agent.py` —
no shared function touched, no other agent affected. The underlying
`write_file`'s own worktree-escape protection still runs beneath the
new scoping, re-verified live.

## Tests

Existing tests across 6 files (`test_analyzer_tier_confirmed.py`,
`test_day6b_agents.py`, `test_dead_contract_fix.py`,
`test_editor_tier.py`, `test_record_learning_rollout.py`,
`test_structural_diff.py`) re-run and confirmed passing unchanged (19
localization_agent-related tests).

New file `tests/test_submit_localization_agent_hardening.py`, 8
tests: schema check, `CHAT_TOOLS` non-membership, the
real-code-file-write-blocked proof (with file-contents-unchanged
assertion), a non-`.md`/non-`docs/` path rejection, two
legitimate-write regressions, a worktree-escape-still-blocked
regression, and a `submit_localization_agent` accumulation
regression.

## Regression

This tool's own new hardening tests (8/8 pass) plus the 6 existing
test files (19 tests) + `test_new_tools.py` + `test_final_session.py`
(446 passed total).

Verified via `mypy app/agents/localization_agent.py` (clean) and
`ruff check` (clean) BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The same real, severe scope-boundary violation class
found on 13 sibling tools found and fixed here too, via evidence (live
reproduction of an unrestricted code-file write before the fix, live
proof of correct scoping after). `submit_localization_agent` itself
audited and confirmed correct. No functionality lost — legitimate
i18n-audit report writing to `.md`/`docs/**` paths still works exactly
as before. Agent alignment verified: PASS.

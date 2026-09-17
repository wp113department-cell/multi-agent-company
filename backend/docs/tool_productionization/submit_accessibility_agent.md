# Tool #231 — `submit_accessibility_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_accessibility_agent` lives entirely in
`app/agents/accessibility_agent.py`, a dedicated, self-contained agent
module. Shared by exactly 1 real agent, confirmed via direct grep —
`accessibility_agent` itself — matching `tool_inventory.json`'s
`agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` (confirmed
via membership check).

`submit_h` is a simple accumulator (`result.update(inp); return
"Submitted."`) — audited against this initiative's well-established
"dead accumulator vs. genuinely live" distinction and found to be the
**correct, live** case: `run_accessibility_agent()`'s own
`raw = final_state["result"] if final_state["result"] else result`
line (confirmed via direct inspection of line 143 pre-fix) already
prioritizes the real, graph-enforced `final_state["result"]`, falling
back to the closure's own `result` only if that's empty — the same
fix pattern MASTER_AGENT_v2.md Phase 3.4 already applied here. Not a
defect.

## Problems found

While auditing this agent's full tool wiring (as this tool's audit
naturally requires understanding everything the agent can do), a real,
severe finding surfaced: `roles/accessibility_agent.md` — this agent's
own system prompt — explicitly states **"this role is read-only on
code"** and lists **"Modifying, creating, or deleting any repo file"**
as an automatic Failure Condition. `AGENT_CONTRACT` itself claims
`side_effects=["writes accessibility audit .md files"]` and
`permissions=["read_repo", "write_docs"]`. But
`make_accessibility_agent_handlers()` built its handler dict from
`base = make_chat_handlers(repo_path)` without ever restricting
`write_file` — giving this agent the full, unrestricted chat-agent
`write_file`, able to write to **any** path in the repo, including
real source code.

Proved live, before any fix:

```python
handlers = make_accessibility_agent_handlers(tmp)
handlers["write_file"]({"path": "app/main.py", "content": "print(2)\n"})
# → "Written app/main.py (11 bytes)" — the real .py file was overwritten
```

This is the exact class of gap this initiative has already found and
fixed on the Day-53 doc-generator agents (`architecture_doc_agent`,
`agent_roster_doc_agent`, `tool_catalog_doc_agent`,
`migration_guide_doc_agent`, `deployment_guide_doc_agent`) via
`make_doc_generator_handlers`'s `dg_write_file` scoping — a real,
code-enforced gap between what an agent's role prompt/contract
promises and what its actual tool wiring allows.

## Changes made

Overrode `write_file` in `make_accessibility_agent_handlers()` with a
new `scoped_write_file` wrapper: any path that doesn't end in `.md` or
start with `docs/` is rejected with a clean
`"[POLICY DENIED] accessibility_agent may only write .md files or
paths under docs/ — this role is read-only on code."` message; legal
paths are delegated to the original, unscoped `write_file` (captured
in a local variable **before** reassignment, to avoid infinite
self-recursion). This mirrors the established
`make_doc_generator_handlers` pattern exactly, without touching that
shared function or any other agent — the fix is entirely local to
`accessibility_agent.py`. The underlying `write_file`'s own
`check_path_in_worktree()` protection still runs as a second,
defense-in-depth layer beneath the new scoping — re-verified live with
a `docs/../../../etc/evil.md` traversal attempt (rejected, since it
still resolves outside the worktree even though it superficially ends
in `.md`).

## Tests

Existing tests across 6 files (`test_day5b_agents.py`,
`test_dead_contract_fix.py`, `test_role_file_tools_accuracy.py`,
`test_batch17_agents.py`, `test_analyzer_tier_confirmed.py`,
`test_record_learning_rollout.py`) re-run and confirmed passing
unchanged (20 accessibility-related tests).

New file `tests/test_submit_accessibility_agent_hardening.py`, 8
tests: schema check, `CHAT_TOOLS` non-membership, the real-code-file
write-blocked proof (with a file-contents-unchanged assertion, not
just the return message), a non-`.md`/non-`docs/` path rejection, two
legitimate-write regressions (top-level `.md`, `docs/**` subpath), a
worktree-escape-still-blocked regression even for a `.md`-suffixed
traversal attempt, and a `submit_accessibility_agent` accumulation
regression confirming the tool itself works correctly.

## Regression

This tool's own new hardening tests (8/8 pass) plus the 6 existing
test files (20 tests) + `test_new_tools.py` + `test_final_session.py`
(437 passed total).

Verified via `mypy app/agents/accessibility_agent.py` (clean — caught
and fixed a `no-any-return` type issue on the delegated call) and
`ruff check` (clean) BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** A real, severe scope-boundary violation found and
fixed via evidence (live reproduction of an unrestricted code-file
write before the fix, live proof of correct scoping — blocked for
code, allowed for reports, worktree-escape still caught — after).
`submit_accessibility_agent` itself was audited and confirmed correct
(the accumulator is a legitimate fallback, not dead state). No
functionality lost — legitimate report-writing to `.md`/`docs/**`
paths still works exactly as before. Agent alignment verified: PASS.

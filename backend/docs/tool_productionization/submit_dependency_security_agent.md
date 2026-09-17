# Tool #244 — `submit_dependency_security_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_dependency_security_agent` lives entirely in
`app/agents/dependency_security_agent.py`, a richer file than most
recent sibling agents — it has **two** handler factories: the
task-triggered `make_dependency_security_agent_handlers()` (used by
`run_dependency_security_agent()`) and the autonomous SCAN-mode
`make_scan_handlers()` (used by `run_dependency_security_scan()`,
wired into `_fleet_agents_scan_loop()`). Shared by exactly 1 real
agent, confirmed via direct grep — `dependency_security_agent` itself
— matching `tool_inventory.json`'s `agent_count: 1` exactly.
Deliberately NOT in `CHAT_TOOLS` (confirmed via membership check).

`submit_h` audited against the dead-accumulator distinction and found
correct: `run_dependency_security_agent()`'s
`raw = final_state["result"] if final_state["result"] else result`
line already prioritizes the real, graph-enforced capture, matching
the exact pattern already confirmed live (not dead) on sibling agents.

## Problems found

The same real, severe finding class already found and fixed on 7
sibling tools, but specifically scoped to only the task-mode factory
here: `roles/dependency_security_agent.md` states **"this role is
read-only on code"** as a Failure Condition (*"Modifying, creating, or
deleting any repo file"*) and Quality Gate (*"Zero repo files were
modified"*), and `AGENT_CONTRACT` claims `side_effects=["writes
vulnerability reports"]` and `permissions=["read_repo",
"write_docs"]`. But `make_dependency_security_agent_handlers()` built
its handler dict from `base = make_chat_handlers(repo_path)` without
restricting `write_file` — giving the task-mode agent the full,
unrestricted chat-agent `write_file`, able to write to **any** path in
the repo, including real source code.

Proved live, before any fix:

```python
handlers = make_dependency_security_agent_handlers(tmp)
handlers["write_file"]({"path": "app/main.py", "content": "print(2)  # overwritten\n"})
# → "Written app/main.py (24 bytes)" — the real .py file was overwritten
```

**Important scope-boundary check specific to this tool**: the separate
autonomous `make_scan_handlers()` factory does **not** need this fix —
confirmed by direct inspection that its own `_SCAN_TOOLS` list never
includes `_WRITE`/`write_file` at all, so that schema is never offered
to the LLM in SCAN mode regardless of what the underlying (unscoped)
handlers dict contains. Applying the fix there would have been
unnecessary defensive-programming noise on an already-safe path.

## Changes made

Overrode `write_file` **only inside
`make_dependency_security_agent_handlers()`** (task mode) with the
same `scoped_write_file` pattern already established for the 7 sibling
agents: any path that doesn't end in `.md` or start with `docs/` is
rejected with a clean `"[POLICY DENIED] dependency_security_agent may
only write .md files or paths under docs/ — this role is read-only on
code."` message; legal paths delegate to the original, unscoped
`write_file` (captured before reassignment, avoiding self-recursion).
`make_scan_handlers()` left completely untouched. The underlying
`write_file`'s own worktree-escape protection still runs beneath the
new scoping, re-verified live.

## Tests

Existing tests across 11 files re-run and confirmed passing unchanged
(34 dependency_security_agent-related tests, minus the one
pre-existing, already-documented pip-audit data-drift failure —
`test_stage4_cluster_q_security_score.py::test_run_dependency_security_agent_end_to_end_persists_real_score`,
which asserts `total_vuln_count == 2` against a real, live
vulnerability database that now reports 4 for the same pinned test
package; unrelated to `write_file`, confirmed the same failure already
recorded in this initiative's #210-#215 and #227-#230 batch
confirmations).

New file `tests/test_submit_dependency_security_agent_hardening.py`,
9 tests: schema check, `CHAT_TOOLS` non-membership, a direct proof
that SCAN mode never advertises `write_file` at all (confirming the
scope-boundary decision above), the real-code-file-write-blocked proof
(with file-contents-unchanged assertion), a non-`.md`/non-`docs/` path
rejection, two legitimate-write regressions, a
worktree-escape-still-blocked regression, and a
`submit_dependency_security_agent` accumulation regression.

## Regression

This tool's own new hardening tests (9/9 pass) plus the 11 existing
test files (34 tests, 1 pre-existing unrelated failure documented
above) + `test_new_tools.py` + `test_final_session.py` (503 passed
total in the combined non-stage4 sweep; the standalone
`test_stage4_cluster_q_security_score.py` run separately confirmed
exactly 2 pre-existing failures, 10 passed).

Verified via `mypy app/agents/dependency_security_agent.py` (clean)
and `ruff check` (clean) BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The same real, severe scope-boundary violation class
found on 7 sibling tools found and fixed here too, via evidence (live
reproduction of an unrestricted code-file write before the fix, live
proof of correct scoping after) — precisely scoped to only the
handler factory that actually needed it, after confirming the other
one (SCAN mode) was already safe by design. `submit_dependency_security_agent`
itself audited and confirmed correct. No functionality lost —
legitimate vulnerability-report writing to `.md`/`docs/**` paths still
works exactly as before. Agent alignment verified: PASS.

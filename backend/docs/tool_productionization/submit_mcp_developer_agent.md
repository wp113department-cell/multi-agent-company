# Tool #253 — `submit_mcp_developer_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_mcp_developer_agent` lives entirely in
`app/agents/mcp_developer_agent.py`. Shared by exactly 1 real agent,
confirmed via direct grep — `mcp_developer_agent` itself — matching
`tool_inventory.json`'s `agent_count: 1` exactly. Deliberately NOT in
`CHAT_TOOLS` (confirmed via membership check).

## Problems found

None. No security vulnerability and no functional bug found — this
audit's real conclusion, reached only after specifically checking the
"unrestricted write_file/bash contradicts a read-only-role promise"
finding class just fixed on 13 recent sibling "read-only report
writer" agents (#231, #232, #237-#240, #243-#246, #248-#250, #252).

**Investigated and RULED OUT**: unlike those sibling agents,
`roles/mcp_developer_agent.md` does **not** claim "read-only on code"
anywhere — this agent's entire job is writing real MCP server/client
**code** and running it via `bash` to prove it actually works.
`AGENT_CONTRACT` itself explicitly declares
`permissions=["read_repo", "write_repo", "execute_bash"]` (deliberately
**not** `"write_docs"`) and `side_effects=["writes MCP server/client
code", "executes bash to test it"]` — the broad access is intentional
and clearly documented, not an oversight. Confirmed live that both
`write_file` (writing real `.py` server code) and `bash` (running a
real shell command) work exactly as intended.

Also confirmed, via a real live test: even with this agent's
intentionally broad `bash` access, the underlying real safety
measures still catch a genuinely catastrophic command —
`bash({"command": "rm -rf /"})` returns
`"[BLOCKED] This command is irreversible/catastrophic and cannot be
run even with confirmation: 'rm -rf /'"` (a stronger, more specific
guard than a mere `[POLICY DENIED]`/`[ERROR]`).

`submit_h` audited against the dead-accumulator distinction and found
correct: `run_mcp_developer_agent()`'s
`raw = final_state["result"] if final_state["result"] else result`
line already prioritizes the real, graph-enforced capture, matching
the exact pattern already confirmed live (not dead) on sibling agents.

## Changes made

None — verified correct as-is.

## Tests

Existing tests across 2 files (`test_batch17_agents.py`,
`test_day8_role_prompts.py`) re-run and confirmed passing unchanged
(15 mcp_developer_agent-related tests).

New file `tests/test_submit_mcp_developer_agent_hardening.py`, 8
tests: schema check, `CHAT_TOOLS` non-membership, a direct proof
`AGENT_CONTRACT` explicitly declares broad write/execute permissions
(not the "write_docs"-only pattern of the fixed sibling agents), the
legitimate-real-code-write regression, a real-`bash`-command
regression, a worktree-escape-still-blocked regression, a real
catastrophic-command-still-blocked proof (caught a wrong assumption in
this test's own first draft — the real response prefix is
`[BLOCKED]`, not `[POLICY DENIED]`/`[ERROR]`, fixed to match reality),
and a `submit_mcp_developer_agent` accumulation regression.

## Regression

This tool's own new hardening tests (8/8 pass) plus the 2 existing
test files (15 tests) + `test_new_tools.py` + `test_final_session.py`
(345 passed total).

## Final verdict

**GREEN FLAG.** Thorough audit found no security vulnerability and no
functional defect. Explicitly investigated the same finding class just
fixed on 13 sibling agents and correctly determined it does NOT apply
here — this agent's role prompt and contract genuinely and explicitly
intend broad write/execute access for its real code-implementation
purpose, confirmed via direct role-file and contract reading, not
assumption. Real safety measures (catastrophic-command blocking)
re-verified live and found stronger than initially assumed. No
functionality lost or changed. Agent alignment verified: PASS.

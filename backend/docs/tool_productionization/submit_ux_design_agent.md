# Tool #271 — `submit_ux_design_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_ux_design_agent` lives in `app/agents/ux_design_agent.py`, same
shape as 24 sibling agents this run: `base =
make_chat_handlers(repo_path)` gives the agent's `write_file` full,
unrestricted filesystem write access. Deliberately NOT in `CHAT_TOOLS`
(confirmed via membership check).

`ux_design_agent` was on the earlier reconnaissance list of candidate
agents for this finding class — verified directly rather than assumed.
`roles/ux_design_agent.md`'s own Quality Gate explicitly states "Zero
repo files modified (design-only role)", and its Non-Responsibilities
say "Writing implementation code (frontend_dev's scope)".
`AGENT_CONTRACT` claims `permissions=["read_repo", "write_docs"]`
(never `"write_repo"`) with `side_effects=["writes UI/UX design specs
and design-system audit docs"]`.

## Problems found

Real, severe finding, proved live before any fix:
`write_file({"path": "app/main.py", "content": "print(2)  # overwritten\n"})`
genuinely overwrote a real application `.py` file — full, unrestricted
filesystem write access, directly contradicting the role's own
"design-only role" Quality Gate and its "implementation code is
frontend_dev's scope" Non-Responsibility.

## Changes made

Added a `scoped_write_file` wrapper in `make_ux_design_agent_handlers()`
that only permits writes to paths ending in `.md` or starting with
`docs/`, returning a `[POLICY DENIED]` message otherwise — identical
pattern to the 24 sibling fixes this run.

Verified live, post-fix:
- `write_file({"path": "app/main.py", ...})` → `[POLICY DENIED]...`,
  file contents on disk confirmed unchanged.
- `write_file({"path": "UX_DESIGN_SPEC.md", ...})` → `Written
  UX_DESIGN_SPEC.md (7 bytes)` — legitimate design-spec write succeeds.
- `write_file({"path": "docs/ux_design_spec.md", ...})` → `Written
  docs/ux_design_spec.md (7 bytes)` — legitimate docs write succeeds.

`ruff check` and `mypy` on the changed file: clean.

`submit_ux_design_agent` itself audited: `run_ux_design_agent`'s
`raw = final_state["result"] if final_state["result"] else result`
line was already correct — no change needed here.

## Tests

Existing tests (`test_day8_role_prompts.py`, `test_batch17_agents.py`,
filtered to `ux_design`): 14 tests, all still pass unchanged.

New file `tests/test_submit_ux_design_agent_hardening.py`, 9 tests:
schema check, `CHAT_TOOLS` non-membership, an `AGENT_CONTRACT`
write_docs-only proof, real-code-file-write blocked with
file-contents-unchanged proof, a real `.tsx` component file blocked
(the specific implementation-code type this agent's Non-Responsibility
forbids), legitimate `UX_DESIGN_SPEC.md` write regression, legitimate
`docs/**` write regression, worktree-escape-path still blocked, and a
`submit_ux_design_agent` accumulation regression.

## Regression

This tool's own new hardening tests (9/9 pass) plus the existing
ux-design-related tests (14) + `test_new_tools.py` — 321 passed total,
0 failed.

## Final verdict

**GREEN FLAG.** Real, severe finding (unrestricted write_file
contradicting the agent's own "design-only role" Quality Gate and
"implementation code is out of scope" Non-Responsibility) found and
fixed. Fix verified live to close the hole while preserving the
agent's genuine legitimate use case (design-spec/audit-doc writes).
Zero functionality lost. Agent alignment verified: PASS.

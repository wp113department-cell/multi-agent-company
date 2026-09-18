# Tool #260 — `submit_roadmap_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_roadmap_agent` lives in `app/agents/roadmap_agent.py`, same
shape as 16 sibling agents this run: `base = make_chat_handlers(repo_path)`
gives the agent's `write_file` full, unrestricted filesystem write
access. Deliberately NOT in `CHAT_TOOLS` (confirmed via membership
check).

`roadmap_agent` was on the earlier reconnaissance list of candidate
agents for this finding class — verified directly rather than assumed.
`roles/roadmap_agent.md`'s own Quality Gate explicitly states "Zero
repo files modified (design-only role)", and `AGENT_CONTRACT` claims
`permissions=["read_repo", "write_docs"]` (never `"write_repo"`) with
`side_effects=["writes roadmap documents"]`.

## Problems found

Real, severe finding, proved live before any fix:
`write_file({"path": "app/main.py", "content": "print(2)  # overwritten\n"})`
genuinely overwrote a real application `.py` file — full, unrestricted
filesystem write access, directly contradicting the role's own
"design-only role" Quality Gate and its declared `write_docs`
permission.

## Changes made

Added a `scoped_write_file` wrapper in `make_roadmap_agent_handlers()`
that only permits writes to paths ending in `.md` or starting with
`docs/`, returning a `[POLICY DENIED]` message otherwise — identical
pattern to the 16 sibling fixes this run.

Verified live, post-fix:
- `write_file({"path": "app/main.py", ...})` → `[POLICY DENIED]...`,
  file contents on disk confirmed unchanged.
- `write_file({"path": "ROADMAP.md", ...})` → `Written ROADMAP.md (10
  bytes)` — legitimate roadmap-document write succeeds.
- `write_file({"path": "docs/roadmap.md", ...})` → `Written
  docs/roadmap.md (10 bytes)` — legitimate docs write succeeds.

`ruff check` and `mypy` on the changed file: clean.

`submit_roadmap_agent` itself audited: `run_roadmap_agent`'s
`raw = final_state["result"] if final_state["result"] else result`
line was already correct (unlike the backwards-priority bug just found
and fixed on sibling tools #258/#259) — no change needed here.

## Tests

Existing tests (`test_batch17_agents.py`, `test_day8_role_prompts.py`,
filtered to `roadmap`): 14 tests, all still pass unchanged.

New file `tests/test_submit_roadmap_agent_hardening.py`, 9 tests:
schema check, `CHAT_TOOLS` non-membership, an `AGENT_CONTRACT`
write_docs-only proof, real-code-file-write blocked with
file-contents-unchanged proof, arbitrary non-md/non-docs path blocked,
legitimate `ROADMAP.md` write regression, legitimate `docs/**` write
regression, worktree-escape-path still blocked, and a
`submit_roadmap_agent` accumulation regression.

## Regression

This tool's own new hardening tests (9/9 pass) plus the existing
roadmap-related tests (14) + `test_new_tools.py` +
`test_final_session.py` — 346 passed total, 0 failed.

## Final verdict

**GREEN FLAG.** Real, severe finding (unrestricted write_file
contradicting the agent's own "design-only role" Quality Gate) found
and fixed. Fix verified live to close the hole while preserving the
agent's genuine legitimate use case (roadmap document writes). Zero
functionality lost. Agent alignment verified: PASS.

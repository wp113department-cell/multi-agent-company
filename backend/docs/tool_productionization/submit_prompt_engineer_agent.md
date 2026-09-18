# Tool #257 — `submit_prompt_engineer_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_prompt_engineer_agent` lives in `app/agents/prompt_engineer_agent.py`.
`make_prompt_engineer_agent_handlers()` builds its tool handlers from
`base = make_chat_handlers(repo_path)`, which is the same shape already
found to carry the "unrestricted write_file" finding on 15 sibling
agents this run. Confirmed `submit_prompt_engineer_agent` is
deliberately NOT in `CHAT_TOOLS` (checked via membership test).

This tool differs from the pure "read-only agent" siblings, though:
`roles/prompt_engineer_agent.md` does not use the exact "read-only on
code" phrase used elsewhere. Instead its Quality Gate says "Zero
UNRELATED repo files modified" (narrower than the other agents'
absolute "Zero repo files modified"), and it lists "Implementing the
code that calls the prompt (that's coder/backend_dev's scope)" as an
explicit Non-Responsibility. `AGENT_CONTRACT["permissions"]` is
`["read_repo", "write_docs"]` (never `"write_repo"`) and
`side_effects` is `["writes prompt drafts and prompt-audit reports"]`
— this agent's genuine, intended output is real prompt/role-file
content (e.g. `roles/*.md`), not code.

## Problems found

Real, severe finding, proved live before any fix:
`write_file({"path": "app/main.py", "content": "print(2)  # overwritten\n"})`
genuinely overwrote a real application `.py` file — full,
unrestricted filesystem write access, contradicting the agent's own
declared `write_docs` permission and its Non-Responsibility for
implementing application code.

## Changes made

Added a `scoped_write_file` wrapper in
`make_prompt_engineer_agent_handlers()` that only permits writes to
paths ending in `.md` or starting with `docs/`, returning a
`[POLICY DENIED]` message otherwise. Unlike the pure read-only
siblings' fix, this scoping is not merely a safety net — it directly
matches the agent's real, intended output: every role file lives at
`roles/*.md`, which ends in `.md`, so the fix imposes zero loss of
legitimate functionality while closing the real-code-write hole.

Verified live, post-fix:
- `write_file({"path": "app/main.py", ...})` → `[POLICY DENIED]...`,
  file contents on disk confirmed unchanged.
- `write_file({"path": "roles/some_agent.md", "content": "# Revised prompt\n"})`
  → `Written roles/some_agent.md (17 bytes)` — legitimate role-file
  write succeeds.
- `write_file({"path": "docs/prompt_audit.md", "content": "# Audit\n"})`
  → `Written docs/prompt_audit.md (8 bytes)` — legitimate audit-report
  write succeeds.

`ruff check` and `mypy` on the changed file: clean.

`submit_prompt_engineer_agent` itself audited: `run_prompt_engineer_agent`'s
`raw = final_state["result"] if final_state["result"] else result` line
correctly prioritizes `base_graph.py`'s generic capture mechanism, with
the closure-local `result` dict as a legitimate fallback only — same
pattern already confirmed live/not-dead on every sibling agent this
run. No change needed here.

## Tests

Existing tests (`test_batch17_agents.py`, `test_day8_role_prompts.py`,
filtered to `prompt_engineer`): 14 tests, all still pass unchanged.

New file `tests/test_submit_prompt_engineer_agent_hardening.py`, 8
tests: schema check, `CHAT_TOOLS` non-membership, real-code-file-write
blocked with file-contents-unchanged proof, arbitrary non-md/non-docs
path blocked, legitimate `roles/*.md` write regression, legitimate
`docs/**` write regression, worktree-escape-path still blocked, and a
`submit_prompt_engineer_agent` accumulation regression.

## Regression

This tool's own new hardening tests (8/8 pass) plus the existing
prompt_engineer-related tests (14) + `test_new_tools.py` +
`test_final_session.py` — 345 passed total, 0 failed.

## Final verdict

**GREEN FLAG.** Real, severe finding (unrestricted write_file
contradicting the agent's declared `write_docs`-only permission and
its own Non-Responsibility for implementing code) found and fixed.
Fix verified live to close the hole while preserving 100% of the
agent's genuine legitimate use case (role-file and docs writes). Zero
functionality lost. Agent alignment verified: PASS.

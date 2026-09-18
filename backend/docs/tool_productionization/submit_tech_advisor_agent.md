# Tool #266 — `submit_tech_advisor_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_tech_advisor_agent` lives in `app/agents/tech_advisor_agent.py`,
same shape as 21 sibling agents this run: `base =
make_chat_handlers(repo_path)` gives the agent's `write_file` full,
unrestricted filesystem write access. Deliberately NOT in `CHAT_TOOLS`
(confirmed via membership check). This file also hosts `score_tech_options`
(tool #230, already fixed in an earlier turn — real deterministic
weighted-sum arithmetic, `blocking_until`-gated before submit).

`roles/tech_advisor_agent.md`'s own Non-Responsibilities say
"Implementing the chosen technology (the relevant coder/dev agent's
scope)", and `AGENT_CONTRACT` claims `permissions=["read_repo",
"write_docs"]` (never `"write_repo"`) with `side_effects=["writes
technology-comparison reports"]` — the real, intended output is a
comparison report.

## Problems found

Real, severe finding, proved live before any fix:
`write_file({"path": "app/main.py", "content": "print(2)  # overwritten\n"})`
genuinely overwrote a real application `.py` file — full, unrestricted
filesystem write access, contradicting the agent's declared
`write_docs`-only permission and its "implementing the technology is
out of scope" Non-Responsibility.

## Changes made

Added a `scoped_write_file` wrapper in
`make_tech_advisor_agent_handlers()` that only permits writes to paths
ending in `.md` or starting with `docs/`, returning a `[POLICY DENIED]`
message otherwise — identical pattern to the 21 sibling fixes this
run. `score_tech_options` and its real weighted-sum arithmetic are
completely untouched.

Verified live, post-fix:
- `write_file({"path": "app/main.py", ...})` → `[POLICY DENIED]...`,
  file contents on disk confirmed unchanged.
- `write_file({"path": "TECH_COMPARISON.md", ...})` → `Written
  TECH_COMPARISON.md (13 bytes)` — legitimate report write succeeds.
- `write_file({"path": "docs/tech_comparison.md", ...})` → `Written
  docs/tech_comparison.md (13 bytes)` — legitimate docs write
  succeeds.
- `score_tech_options({"options": [...]})` still produces the correct
  real weighted ranking, confirming this fix didn't disturb it.

`ruff check` and `mypy` on the changed file: clean.

`submit_tech_advisor_agent` itself audited: `run_tech_advisor_agent`
already has the correct `raw = dict(final_state["result"] if
final_state["result"] else result)` priority, plus the "trust the
code, not the model's claim" override that forces `ranked_options`/
`scoring_criteria`/`normalized_weights` from the handler's own real
computation — no change needed here.

## Tests

Existing tests (`test_day8_role_prompts.py`,
`test_score_tech_options_hardening.py`, `test_batch17_agents.py`,
`test_list_all_tool_specs_hardening.py`, filtered to `tech_advisor`/
`tech`): 30 tests, all still pass unchanged — including the prior
`score_tech_options` (tool #230) hardening suite, confirming zero
disruption to that already-fixed real arithmetic tool.

New file `tests/test_submit_tech_advisor_agent_hardening.py`, 10
tests: schema check, `CHAT_TOOLS` non-membership, an `AGENT_CONTRACT`
write_docs-only proof, real-code-file-write blocked with
file-contents-unchanged proof, arbitrary non-md/non-docs path blocked,
legitimate `TECH_COMPARISON.md` write regression, legitimate
`docs/**` write regression, worktree-escape-path still blocked, a
`score_tech_options`-unaffected regression, and a
`submit_tech_advisor_agent` accumulation regression.

## Regression

This tool's own new hardening tests (10/10 pass) plus the existing
tech-advisor-related tests (30) + `test_new_tools.py` — 335 passed
total, 0 failed.

## Final verdict

**GREEN FLAG.** Real, severe finding (unrestricted write_file
contradicting the agent's declared `write_docs`-only permission and
"implementing the technology is out of scope" Non-Responsibility)
found and fixed. Fix verified live to close the hole while preserving
the agent's genuine legitimate use case (comparison-report writes) and
leaving the already-fixed `score_tech_options` real arithmetic tool
completely untouched. Zero functionality lost. Agent alignment
verified: PASS.

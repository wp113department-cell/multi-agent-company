# Tool #233 — `submit_api_designer_agent` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_api_designer_agent` lives entirely in
`app/agents/api_designer_agent.py`, structurally similar to sibling
agents `accessibility_agent.py` (tool #231) and
`agentic_ai_architect.py` (tool #232), both fixed in the immediately
preceding turns for an unrestricted `write_file` contradicting their
own role prompts. Shared by exactly 1 real agent, confirmed via direct
grep — `api_designer_agent` itself — matching `tool_inventory.json`'s
`agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` (confirmed
via membership check).

## Problems found

None. No security vulnerability and no functional bug found — this
audit's real conclusion, reached only after specifically investigating
the same finding class just fixed on the two immediately preceding
sibling tools, per the "note for future turns" flagged on tool #232's
report.

**Investigated and RULED OUT**: unlike `accessibility_agent`/
`agentic_ai_architect`, `roles/api_designer_agent.md` does **not**
claim "read-only on code" or "zero repo files modified" anywhere.
Its own Process step 3 explicitly says *"Use write_file to save any
output files (reports, specs, scripts, docs)"*, and its
Non-Responsibilities section only excludes **implementing** the API
(that's `backend_dev`'s job) — never file-write scope generally.
`AGENT_CONTRACT`'s own `side_effects=["writes OpenAPI spec or contract
.yaml/.md files"]` explicitly confirms `.yaml` output at arbitrary
paths is a legitimate, intended deliverable, not an oversight.
Confirmed live that writing `openapi.yaml` (a non-`.md`,
non-`docs/`-prefixed path) succeeds — correct, expected behavior for
this specific agent. Applying the #231/#232-style `.md`/`docs/**`
restriction here would have been a real regression, not a fix.

Also confirmed via a targeted grep across `app/fleet/*.py` and
`app/agents/base_graph.py`: `AGENT_CONTRACT["permissions"]` is never
read or enforced anywhere in the codebase at runtime — `"write_docs"`
here is descriptive metadata shared by many agents (including ones
with genuinely broader write needs, like this one), not a
code-enforced, broken promise specific to this agent.

`submit_h` audited against the dead-accumulator distinction and found
correct: `run_api_designer_agent()`'s
`raw = final_state["result"] if final_state["result"] else result`
line already prioritizes the real, graph-enforced capture, matching
the exact pattern already confirmed live (not dead) on sibling agents'
turns.

Also noted, not fixed (no functional impact): the role file's own
"Output Contract" section lists `spec`/`conflict_check`/`decisions`/
`status` fields that aren't declared in `_SUBMIT`'s schema
`properties` (only `summary`/`findings`/`recommendations` are). Since
the schema doesn't set `additionalProperties: false` and `submit_h`
does an unconditional `result.update(inp)`, any extra fields the model
sends still flow through correctly — confirmed live. A documentation
polish item, not a functional defect worth touching.

## Changes made

None — verified correct as-is.

## Tests

Existing tests across 6 files (`test_analyzer_tier_confirmed.py`,
`test_architecture_note_wiring.py`, `test_day5b_agents.py`,
`test_dead_contract_fix.py`, `test_record_learning_rollout.py`,
`test_role_file_tools_accuracy.py`) re-run and confirmed passing
unchanged (21 api_designer_agent-related tests).

New file `tests/test_submit_api_designer_agent_hardening.py`, 6 tests:
schema check, `CHAT_TOOLS` non-membership, the legitimate-`.yaml`-write
regression (the specific case that would have broken if the sibling
tools' fix had been blindly reapplied here), a worktree-escape-still-blocked
regression, a `submit_api_designer_agent` accumulation regression, and
a proof that extra Output-Contract fields not in the formal schema
still flow through without crashing or being dropped.

## Regression

This tool's own new hardening tests (6/6 pass) plus the 6 existing
test files (21 tests) + `test_new_tools.py` + `test_final_session.py`
(357 passed total).

## Final verdict

**GREEN FLAG.** Thorough audit found no security vulnerability and no
functional defect. Explicitly investigated the same finding class just
fixed on two sibling agents and correctly determined it does NOT apply
here — this agent's role prompt and contract genuinely intend broader
write access for its legitimate `.yaml` spec output, confirmed via
direct role-file reading, not assumption. No functionality lost or
changed. Agent alignment verified: PASS.

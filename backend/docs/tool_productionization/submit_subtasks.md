# Tool #265 — `submit_subtasks` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_subtasks` lives entirely in `app/agents/decomposer.py`,
structurally similar to pipeline-only sibling tools #234
(`submit_architect_plan`), #235 (`submit_brief`), and #256
(`submit_plan`) — `decomposer_node` runs through
`app/pipeline/graph.py`, not interactive chat. Deliberately NOT in
`CHAT_TOOLS` (confirmed via membership check). No `write_file`/
`edit_file` anywhere in this agent's tool list
(`permissions=["read_repo"]` only, `side_effects=[]`) — the
write_file-scoping finding class from the report-writer agents doesn't
apply here at all.

## Problems found

Unlike siblings #234/#235/#256's pure no-op lambdas (which ignore
their input entirely and can never crash), decomposer's own
`handlers["submit_subtasks"]` lambda actually touches its input —
`len(inp.get('subtasks', []))` — and genuinely crashed with
`TypeError` on a malformed/schema-violating submission (e.g.
`subtasks=None` or a non-list value; the LLM's tool-use args aren't
runtime-enforced against the declared array-typed `input_schema`).
Proved live using the real `decomposer.py` code (not a reconstructed
copy), via `decomposer_node` with `run_agent_graph` stubbed to raise
immediately, capturing the real wired handler.

Investigated severity: confirmed via direct inspection of
`base_graph.py`'s `_run_tool_with_retry` chokepoint (the one universal
call site for every tool invocation, including `submit_subtasks`) that
this crash was ALREADY gracefully contained fleet-wide — any exception
is caught and converted to a clean `"[ERROR] ... raised: ..."` string,
never propagating to crash the pipeline. Further confirmed that
`decomposer_node`'s own real subtasks data comes from
`final_state["result"]`, captured independently at the same submit_*
chokepoint directly from the raw tool input (`raw_result = dict(tu_input)`)
— unconditionally, regardless of whether the confirmation-string
lambda itself crashed. So this was never a pipeline-breaking bug, only
a confusing/incorrect confirmation message shown back to the LLM.

## Changes made

Fixed anyway to match this codebase's established malformed-submit-data
hardening pattern (tools #236/#242/#247): coerce non-list `subtasks`
values to a safe length of 0 rather than letting `len()` raise.
Verified live with the real handler: `{}` / `{"subtasks": None}` /
`{"subtasks": 5}` / `{"subtasks": "notalist"}` all now return
`"Submitted 0 subtasks"` cleanly (no crash), and a real list still
counts correctly (`{"subtasks": [...]}` → `"Submitted 1 subtasks"`).

`ruff check` and `mypy` on the changed file: clean.

## Tests

Existing tests across 11 files (`test_benchmark_baseline_loop.py`,
`test_phase53_request_clarification.py`,
`test_architecture_note_wiring.py`, `test_day18_streaming_wiring.py`,
`test_day12_smoke_test.py`, `test_repo_scoping_race_fix.py`,
`test_approval_gate.py`, `test_day1_agent_flags.py`,
`test_session1_migration.py`, `test_gap11_14_topological_subtask_order.py`,
`test_day0_groq_integration.py`, filtered to `decomposer`): 19 tests,
all still pass unchanged. `tests/pending/test_decomposer_agent.py`
(3 tests) are deliberately skipped, unaffected.

New file `tests/test_submit_subtasks_hardening.py`, 5 tests: schema
check, `CHAT_TOOLS` non-membership, a direct proof no `write_file`/
`edit_file` exists in this agent's tools, the real
malformed-input-no-longer-crashes proof (extracting the actual wired
handler from `decomposer_node`), and a real-list-counts-correctly
regression.

## Regression

This tool's own new hardening tests (5/5 pass) plus the 11
decomposer-adjacent test files (19 tests) + `test_new_tools.py` — 169
passed, 21 failed. The 21 failures
(`test_benchmark_baseline_loop.py`, `test_day18_streaming_wiring.py`,
`test_day12_smoke_test.py`, `test_repo_scoping_race_fix.py`,
`test_approval_gate.py`) are a pre-existing environmental issue —
`ConnectionRefusedError` on `127.0.0.1:5432` (no local Postgres running
in this environment), same class already documented on tools #259/#264.
Confirmed via `git stash` to fail identically (same 21 tests) on HEAD
with zero local changes — unrelated to this tool's fix.

## Final verdict

**GREEN FLAG.** No security vulnerability (no write access at all on
this agent). One real, provable robustness defect found and fixed —
though contained by the fleet-wide chokepoint and never
pipeline-breaking, it's fixed to match this codebase's established
malformed-submit-data hardening pattern, producing a correct, clean
confirmation message instead of a confusing `[ERROR]` on
schema-violating input. Zero functionality lost. Agent alignment
verified: PASS.

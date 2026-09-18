# Tool #274 (final tool in tool_enhance_tracking.md) — `submit_scaffold_plan` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`submit_scaffold_plan` lives entirely in `app/pipeline/bootstrap.py`,
structurally identical to sibling tools #234 (`submit_architect_plan`),
#235 (`submit_brief`), and #256 (`submit_plan`). `run_scaffold_planning()`
reuses the `architect` agent's identity (`role_name="architect"`,
`roles/architect.md`, `settings.model_planner`) for a one-shot "blank
repo scaffold planning" call, wiring `tools=READ_ONLY_TOOLS +
[_SCAFFOLD_SUBMIT_TOOL]` — no `write_file`/`edit_file` at all, so the
write_file-scoping finding class from the report-writer agents doesn't
apply here.

`agent_count:0` in the tracking table is a heuristic false negative —
this tool isn't declared in any `AGENT_CONTRACT["allowed_tools"]"]`
because it's a standalone pipeline utility (used only via the
blank-repo bootstrap flow), not a registered fleet agent — the same
class of false negative already confirmed on tool #210
(`capability_gap_scan`).

## Problems found

None. No security vulnerability and no functional bug found — this
audit's real conclusion. The handler is a trivial no-op:

```python
handlers["submit_scaffold_plan"] = lambda inp: "Scaffold plan submitted"
```

Confirmed intentional, correct design via direct inspection of
`run_scaffold_planning`'s own body: it reads
`final_state.get("result", {})` directly from the generic `submit_*`
capture mechanism in `base_graph.py` — the same pattern already
verified correct on sibling tools #234/#235/#256. Proved the lambda
cannot crash across 6 malformed input shapes. No backwards-priority
bug is even possible here since there is no competing local dict —
`run_scaffold_planning` uses `final_state["result"]` as its one and
only source (unlike the real backwards-priority bug found and fixed on
tools #258/#259/#269/#270 this run, which had a competing local
`submitted` dict).

## Changes made

None — verified correct as-is.

## Tests

Existing tests across 8 files (`test_bootstrap_wiring.py`,
`test_audit04_orchestration_fixes.py`, `test_bootstrap.py`,
`test_gap_closure_days0_18.py`, `test_day18_streaming_wiring.py`,
`test_launch_coder_bootstrap.py`, `test_reindex_incremental_merge.py`,
`test_audit05_security_fixes.py`) always mock `run_scaffold_planning`
at its `bootstrap.py` import site — the real `submit_scaffold_plan`
handler logic had never been directly tested before.

New file `tests/test_submit_scaffold_plan_hardening.py`, 4 tests:
schema check, a direct proof no `write_file`/`edit_file` appears
anywhere in `run_scaffold_planning`'s own tool wiring, a direct proof
the handler's own no-op lambda never crashes across 6 malformed input
shapes, and a proof `run_scaffold_planning` reads
`final_state.get("result", {})` directly (the real, load-bearing data
path).

## Regression

This tool's own new hardening tests (4/4 pass) plus the existing
bootstrap-adjacent tests filtered to `bootstrap`/`scaffold` (15 passed,
5 pre-existing DB-connectivity failures) + `test_new_tools.py`.
A wider run across all 8 test files' full contents surfaced 34
failures — all confirmed to be the same pre-existing, environment-wide
`ConnectionRefusedError` on `127.0.0.1:5432` (no local Postgres server
running in this sandbox) already documented on tools
#259/#264/#265/#267/#272/#273 this run, spanning entirely unrelated
subsystems (orchestration guards, reindexing, password-change
endpoints) with zero code overlap with this tool. Since no source code
was changed for this tool's turn, these failures are baseline
environmental noise, not a regression.

## Final verdict

**GREEN FLAG.** Thorough audit found no security vulnerability and no
functional defect — the tool's apparent triviality was specifically
verified to be intentional correct design, matching the exact pattern
already confirmed on sibling tools #234/#235/#256. No functionality
lost or changed. Agent alignment verified: PASS.

This is the final row in `bhaskar_next/tool_enhance_tracking.md` — all
274 tracked tools have now been processed through the
AUDIT → RESEARCH → DESIGN → IMPLEMENT → TEST → REAL EXECUTION →
REGRESSION → AGENT ALIGNMENT → FINAL VERIFICATION workflow.

# Tool #181 — `submit_arch_review` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `ar_submit` inside `make_arch_reviewer_handlers()`.
Exactly 1 real agent declares this tool per `tool_inventory.json`:
`architecture_reviewer` (`app/agents/architecture_reviewer.py`, via
both `run_arch_review()` and `make_scan_handlers()`). Deliberately
NOT in `CHAT_TOOLS` — confirmed via membership check — same
correct-and-intentional absence already established for sibling tools
#66/#180.

Existing tests referencing this tool: `tests/test_day2_agents.py`'s
`TestArchReviewerHandlers` (4 tests), plus references in
`tests/test_gap48_architecture_reviewer_scan.py`,
`tests/test_gap49_dependency_scan.py`, and
`tests/test_stage4_cluster_q_architecture_score.py` — confirmed via
grep and re-run.

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`structure_summary`, `risks`,
`recommendations`, `blast_radius`, `import_graph_ran` are all
free-form structured data or a bool) — no injection surface. Also
re-verified the schema's `import_graph_ran` field, which is already
explicitly documented (a pre-existing, unrelated Gap-closure Day 48
fix) as "Overridden by the real VerificationConfig graph-execution
state, never trusted from the model's own claim" — confirmed live:
`run_arch_review()` reads
`final_state["verification"].get("import_graph_ran", False)`, NOT
`raw.get("import_graph_ran")`, so an LLM claiming
`import_graph_ran: true` without actually calling `import_graph`
cannot forge verification. Already correct; no fix needed.

## Problems found

One real finding, same class and shape as sibling tool #180's
`submit_ai_result`: **dead-code accumulator, never actually read.**
`ar_submit`'s original body did `arch_result.update(inp)`, and the
factory separately exported `handlers["_arch_result"] = arch_result`
— but grepping the entire production codebase found zero real
readers. Traced the actual, working result-capture mechanism: it
lives entirely in `app/agents/base_graph.py`'s generic
tool-execution node (`tool_name.startswith("submit_")` → captures
`dict(tu_input)` directly into `state["result"]`), confirmed by
reading `run_arch_review()`'s own `raw = final_state["result"]` line
— that is what real production code actually consumes, completely
independent of `arch_result`/`_arch_result`.

## Changes made

Extracted into `app/tools/agents/submit_arch_review.py`
(`SUBMIT_ARCH_REVIEW_TOOL`, `submit_arch_review_handler`; the schema
itself is unchanged, including its pre-existing Gap-closure Day 48
fix). The dead `arch_result` dict and `handlers["_arch_result"]`
export are removed entirely — `submit_arch_review_handler()` now does
exactly what the real, functioning mechanism actually needs: return
the same confirmation string as before
(`"Architecture review submitted"`), with zero behavior change to the
tool's real end-to-end effect.

## Tests

`tests/test_day2_agents.py::TestArchReviewerHandlers::
test_submit_stores_result` previously asserted directly on
`h["_arch_result"]["structure_summary"]` — an internal implementation
detail now confirmed dead and removed. Fixed by asserting on the
handler's real return value instead
(`"Architecture review submitted"`), preserving the test's actual
intent (a real submission with the correct schema succeeds) without
relying on dead internal state. All 4 tests in that class pass after
the fix.

New file `tests/test_submit_arch_review_hardening.py`, 8 tests:
schema check, duplicate-registration check (in `ARCH_REVIEWER_TOOLS`),
confirmation it is correctly absent from `CHAT_TOOLS`, re-confirmation
`_arch_result` is no longer exported, and legitimate-usage regression
(identical confirmation string returned regardless of input shape,
repeated calls don't accumulate or leak state).

Existing related tests
(`tests/test_gap48_architecture_reviewer_scan.py`, 7 tests;
`tests/test_gap49_dependency_scan.py` +
`tests/test_stage4_cluster_q_architecture_score.py`, 16 tests
combined) re-run clean.

## Regression

This tool is tool 3 of the #179-#183 batch. Its own new hardening
tests (8/8 pass) plus the fixed + swept existing tests (4 + 7 + 16 =
27/27 pass) are the per-tool verification gate; the full suite runs
once the batch completes.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/agents/
submit_arch_review.py` sweep (102 files clean), an `importlib`-reload
sweep over all `app.agents.*` modules including
`app.agents.architecture_reviewer` (all clean), a `ruff check` on all
touched files (clean), and a compile()-based source escape-sequence
check on the new module (clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding (dead-code state) was identified
and removed with zero change to the tool's real, working end-to-end
behavior; no functionality lost (the one existing test that needed a
change was adjusted to test real behavior instead of dead internal
state, not weakened); tool-specific regression tests clean (35/35
across new + fixed + swept existing tests).

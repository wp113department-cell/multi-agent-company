# Tool #200 — `submit_style_review` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `sr_submit` inside
`make_style_reviewer_handlers()`. Exactly 1 real agent declares this
tool per `tool_inventory.json`: `style_reviewer`
(`app/agents/style_reviewer.py`). Deliberately NOT in `CHAT_TOOLS` —
confirmed via membership check (count is 0) — same correct-and-
intentional absence already established for sibling tools
#66/#180-#186/#188-#192/#194/#196-#199.

`make_style_reviewer_handlers()`'s other handlers (`run_linter`,
`list_functions`, `list_classes`, `find_todos`) are each their own
separately-productionized concern (`run_linter`/`list_functions`/
`list_classes` already GREEN_FLAGGED as tools #101/#82/#87) —
deliberately untouched here, out of scope for this tool's own turn.

Existing tests referencing this tool:
`tests/test_day3_agents.py::TestStyleReviewerTools` and
`::TestStyleReviewerHandlers` — assert only tool-list membership and
handler-key presence, neither references the internal `_style_result`
dict, so no fix was required there (same shape as tool #184).

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`summary`, `violations`,
`auto_fixable` are all free-form structured/boolean data — any real
lint scan already happened via the agent's own separately gated
`run_linter` handler before this tool is ever called) — no injection
surface.

## Problems found

One real finding, same class and shape as sibling tools
#180-#186/#188-#192/#196-#199: **dead-code accumulator, never
actually read.** `sr_submit`'s original body did
`style_result.update(inp)`, and the factory separately exported
`handlers["_style_result"] = style_result` — but grepping the entire
production codebase found zero real readers. Traced the actual,
working result-capture mechanism: it lives entirely in
`app/agents/base_graph.py`'s generic tool-execution node
(`tool_name.startswith("submit_")` → captures `dict(tu_input)`
directly into `state["result"]`), confirmed by reading
`style_reviewer.py`'s own `raw = final_state["result"]` line — that
is what real production code actually consumes, completely
independent of `style_result`/`_style_result`.

## Changes made

Extracted into `app/tools/agents/submit_style_review.py`
(`SUBMIT_STYLE_REVIEW_TOOL`, `submit_style_review_handler`). The dead
`style_result` dict and `handlers["_style_result"]` export are removed
entirely — `submit_style_review_handler()` now does exactly what the
real, functioning mechanism actually needs: return the same
confirmation string as before (`"Style review submitted"`), with zero
behavior change to the tool's real end-to-end effect. All other
`make_style_reviewer_handlers()` handlers left byte-for-byte unchanged.

## Tests

No existing test required a fix (verified: neither
`TestStyleReviewerTools` nor `TestStyleReviewerHandlers` reads
`_style_result`). All 102 tests across
`tests/test_submit_style_review_hardening.py` +
`tests/test_day3_agents.py` pass.

New file `tests/test_submit_style_review_hardening.py`, 9 tests:
schema check, duplicate-registration check (in `STYLE_REVIEWER_TOOLS`),
confirmation it is correctly absent from `CHAT_TOOLS`,
re-confirmation `_style_result` is no longer exported, and
legitimate-usage regression (identical confirmation string returned
regardless of input shape, repeated calls don't accumulate or leak
state, sibling handlers unaffected).

## Regression

This tool is tool 1 of a new #200-#201 mini-batch (the tracking
sequence's final two `submit_*` agent-report tools before the
`NO_MANIFEST`-classified tail). Its own new hardening tests (9/9 pass)
plus the unaffected 93 existing `tests/test_day3_agents.py` tests are
the per-tool verification gate; the full suite runs after tool #201.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.style_reviewer` and `app.agents.tools` (both clean), a
`ruff check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_new_tools.py` + `tests/test_final_session.py` tool-count
regression tests (61/61 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding (dead-code state) was identified
and removed with zero change to the tool's real, working end-to-end
behavior; no functionality lost (no existing test needed to change);
tool-specific regression tests clean (102/102 across new + existing
tests). Agent alignment verified: PASS (`style_reviewer.py`'s real
`raw = final_state["result"]` consumption path is unaffected by the
removal of the dead accumulator).

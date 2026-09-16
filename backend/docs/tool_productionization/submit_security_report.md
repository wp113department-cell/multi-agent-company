# Tool #197 — `submit_security_report` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `sec_submit` inside
`make_security_reviewer_handlers()`. Exactly 1 real agent declares
this tool per `tool_inventory.json`: `security_reviewer`
(`app/agents/security_reviewer.py`, via `run_security_reviewer()`).
Deliberately NOT in `CHAT_TOOLS` — confirmed via membership check
(count is 0) — same correct-and-intentional absence already
established for sibling tools #66/#180-#186/#188-#192/#194/#196.

Also re-verified: `quality_auditor.py` builds a scan-scoped variant of
`SECURITY_REVIEWER_TOOLS` (`base = [t for t in SECURITY_REVIEWER_TOOLS
if t["name"] != "submit_security_report"]`) that explicitly excludes
this tool — a pre-existing, intentional design mirroring
`monitoring_agent.py`'s own scan-mode pattern (tool #189), not a bug.
Confirmed still correct, untouched.

Notable false-positive avoided: an unrelated agent,
`security_architect.py`, coincidentally exports its own local dict
under the identically-named key `handlers["_security_result"]` for
its own different tool (`submit_threat_model`, built on
`make_chat_handlers()` as its base) — a separate closure in a separate
factory function, verified NOT a reader of this tool's `security_result`
dict. A naive grep for `_security_result` also matches
`tests/test_day4_agents.py`, `tests/test_gap_agents.py`, and
`tests/test_day4_agent_contracts.py` — all three actually test
`security_architect.py`, not this tool (verified by reading each; all
258 of their combined tests re-run clean, unaffected by this turn).

`make_security_reviewer_handlers()`'s other handlers (`secrets_scan`,
`find_sql`, `find_config`, `find_api`, `find_route`) are each their own
separately-productionized tool (already GREEN_FLAGGED as tools
#89/#90/#91/#99/#102) — deliberately untouched here, out of scope for
this tool's own turn.

Existing tests referencing this tool:
`tests/test_day2_agents.py::TestSecurityReviewerHandlers::test_submit_stores_result`
asserted directly on the now-removed `_security_result` — see Tests
section.

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`severity` is an enum,
`findings`/`recommendations` are string arrays — the agent's real
security scanning already happened via its own separately gated
handlers before this tool is ever called) — no injection surface.

## Problems found

One real finding, same class and shape as sibling tools
#180-#186/#188-#192/#196: **dead-code accumulator, never actually
read.** `sec_submit`'s original body did `security_result.update(inp)`,
and the factory separately exported `handlers["_security_result"] =
security_result` — but grepping the entire production codebase found
zero real readers of THIS specific dict (the only same-named key
anywhere belongs to the unrelated `security_architect.py` agent — see
above). Traced the actual, working result-capture mechanism: it lives
entirely in `app/agents/base_graph.py`'s generic tool-execution node
(`tool_name.startswith("submit_")` → captures `dict(tu_input)`
directly into `state["result"]`), confirmed by reading
`security_reviewer.py`'s own `raw = final_state["result"]` lines —
used on BOTH its normal-completion path and its turn-limit-exhausted
retry-giveup path — that is what real production code actually
consumes, completely independent of
`security_result`/`_security_result`.

## Changes made

Extracted into `app/tools/agents/submit_security_report.py`
(`SUBMIT_SECURITY_REPORT_TOOL`, `submit_security_report_handler`). The
dead `security_result` dict and `handlers["_security_result"]` export
are removed entirely — `submit_security_report_handler()` now does
exactly what the real, functioning mechanism actually needs: return
the same confirmation string as before (`"Security report
submitted"`), with zero behavior change to the tool's real end-to-end
effect. All other `make_security_reviewer_handlers()` handlers left
byte-for-byte unchanged.

## Tests

`tests/test_day2_agents.py::TestSecurityReviewerHandlers::test_submit_stores_result`
previously asserted directly on `h["_security_result"]["severity"]` —
an internal implementation detail now confirmed dead and removed.
Fixed by asserting on the handler's real return value instead
(`"Security report submitted"`), preserving the test's actual intent
(a real submission succeeds) without relying on dead internal state.

New file `tests/test_submit_security_report_hardening.py`, 10 tests:
schema check, duplicate-registration check (in
`SECURITY_REVIEWER_TOOLS`), confirmation it is correctly absent from
`CHAT_TOOLS`, re-confirmation it is correctly excluded from
`quality_auditor.py`'s scan tools, re-confirmation `_security_result`
is no longer exported, and legitimate-usage regression (identical
confirmation string returned regardless of input shape, repeated
calls don't accumulate or leak state, sibling handlers unaffected).

## Regression

This tool is tool 3 of the #195-#199 batch. Its own new hardening
tests (10/10 pass) plus the fixed existing test (84 total across
`test_submit_security_report_hardening.py` + `test_day2_agents.py`)
are the per-tool verification gate. Also confirmed the 3
false-positive-matched test files (`test_day4_agents.py`,
`test_gap_agents.py`, `test_day4_agent_contracts.py`, 258 tests
combined) are genuinely unaffected. The full batch suite runs after
tool #199.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.security_reviewer`, `app.agents.quality_auditor`, and
`app.agents.tools` (all clean), a `ruff check` on all touched files
(clean), a `CHAT_TOOLS` duplicate-registration check (clean), and
`tests/test_new_tools.py` + `tests/test_final_session.py` tool-count
regression tests (61/61 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding (dead-code state) was identified
and removed with zero change to the tool's real, working end-to-end
behavior; no functionality lost (the one existing test that needed a
change was adjusted to test real behavior instead of dead internal
state, not weakened); tool-specific regression tests clean (84/84
across new + fixed existing tests, plus 258/258 in the confirmed-
unaffected false-positive-matched files). Agent alignment verified:
PASS (`security_reviewer.py`'s real `raw = final_state["result"]`
consumption path, on both its success and retry-giveup branches, and
`quality_auditor.py`'s separate scan-tool exclusion, are both
unaffected by the removal of the dead accumulator).

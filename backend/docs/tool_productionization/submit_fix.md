# Tool #214 — `submit_fix` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

FOUR separate, independently-maintained implementations, one inline in
each of `app/agents/agent_performance_reviewer.py`,
`app/agents/knowledge_curator.py`, `app/agents/agent_debugger.py`, and
`app/agents/quality_auditor.py` — matching `tool_inventory.json`'s
`agent_count: 4` exactly. Deliberately NOT in `CHAT_TOOLS` — confirmed
via membership check; this is an APPLY-phase-only, human-approval-
gated "I'm done" signal, not exposed to interactive chat.

## Problems found

No security vulnerability and no functional bug found — the real
finding here is **duplication**, not a defect. All 4 real
implementations were already 100% functionally identical:
`def submit_h(inp): return "done"`, byte-for-byte the same in every
file, and all 4 schemas share the identical `{summary: string}` shape
(`required: ["summary"]`) — differing only in cosmetic `description`
text ("Signal the fix is complete and committed." / "Signal the
curation action is complete." / "Signal the fix is complete, tested,
and committed." twice). No input validation, state, or side effect
exists in any of the 4 to diverge on.

This is NOT a dead-accumulator finding (the class documented for tools
#180-#186/#188-#192/#194/#196-#201/#211): there is no local dict to go
stale here at all. The real, functioning result-capture mechanism is
`app/agents/base_graph.py`'s generic `submit_*` handling exactly as
for those siblings — confirmed directly by reading each of the 4 real
callers' `raw = final_state.get("result", {})` line, which is what
genuinely carries the LLM's `summary` field forward into the returned
`AgentResult.raw`.

## Changes made

Unified purely for consistency and to eliminate duplicate code,
matching the precedent already established for tool #85's
`submit_docs` (4 implementations, unified into one shared
`make_submit_docs_handler`). Extracted into
`app/tools/agents/submit_fix.py` (`SUBMIT_FIX_TOOL`,
`submit_fix_handler`), standardized on one description ("Signal the
approved change (fix or knowledge-curation action) is complete.")
that accurately covers all 4 real contexts, since none of the 4
original description variants carried any behavior-affecting meaning.
All 4 agent files now import `SUBMIT_FIX_TOOL as _SUBMIT_FIX_TOOL_SHARED`
and `submit_fix_handler`, replacing their own local schema dict and
`submit_h` closure — `handlers["submit_fix"] = submit_fix_handler`
directly, no wrapper.

## Tests

No existing test named `submit_fix` specifically (matching
`tool_inventory.json`'s "0"), but `tests/test_day9_fleet_agents.py`'s
parametrized `test_apply_fn_returns_agent_result`/
`test_apply_fn_blocked_when_not_verified` (8 tests, 2 per agent) already
exercise all 4 real apply-phase functions end-to-end via a mocked
`run_agent_graph` — re-run and confirmed passing unchanged.

New file `tests/test_submit_fix_hardening.py`, 7 tests: schema check,
direct handler behavior, a real object-identity proof that all 4
agents declare the literal SAME shared schema dict (not 4 copies that
merely look alike), and 4 legitimate-usage regression tests (one per
agent) that capture the real `tool_handlers` dict passed to
`run_agent_graph` and confirm `handlers["submit_fix"] is
submit_fix_handler` — proving genuine de-duplication, not just visual
similarity.

## Regression

This tool's own new hardening tests (7/7 pass) plus the full
`tests/test_day9_fleet_agents.py` suite (56 tests, including the 8
apply-phase tests directly covering this change).

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean) and a `ruff check` on all 5 touched files
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** No security or functional defect found — 4
byte-for-byte-identical implementations consolidated into one shared
schema and handler, matching established precedent. No functionality
lost — all 4 real apply-phase functions verified end-to-end (mocked
LLM call) to still wire and use the tool correctly, with real
object-identity proof of de-duplication. Agent alignment verified:
PASS (all 4 real consumer agents independently confirmed via live
import + mocked-graph execution).

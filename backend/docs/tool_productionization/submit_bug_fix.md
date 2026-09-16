# Tool #211 — `submit_bug_fix` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `bf_submit` inside `make_bug_fix_handlers()`.
Exactly 1 real agent per `BUG_FIX_TOOLS` (the tools list actually
passed to `run_agent_graph()` for `bug_fix`) — `bug_fix`
(`app/agents/bug_fix.py`). Deliberately NOT in `CHAT_TOOLS` — confirmed
via membership check (count is 0) — same correct-and-intentional
absence already established for sibling tools
#66/#180-#186/#188-#192/#194/#196-#201.

`tool_inventory.json` reports `agent_count: 0` — investigated directly
rather than trusted, and this is where the real finding surfaced (see
Problems found #2).

## Problems found

Two real findings.

1. **Dead-code accumulator, never actually read — same class as
   sibling tools #180-#186/#188-#192/#194/#196-#201.** `bf_submit`'s
   original body did `bug_fix_result.update(inp)`, and the factory
   separately exported `handlers["_bug_fix_result"] = bug_fix_result`
   — but grepping the entire production codebase found zero real
   readers. Traced the actual, working result-capture mechanism: it
   lives entirely in `app/agents/base_graph.py`'s generic
   tool-execution node, confirmed by `bug_fix.py`'s own `raw =
   final_state["result"]` line.
2. **`AGENT_CONTRACT["allowed_tools"]` declared tools `bug_fix` cannot
   actually call, and omitted the one it actually does.** The contract
   listed `"submit_patch"` and `"bash"` — but `make_bug_fix_handlers()`
   has no handler for either (grepped: only `submit_bug_fix`/
   `bf_submit` exists; `bash` is absent from both the handler dict and
   the real `BUG_FIX_TOOLS` runtime tool list — independently
   confirmed by an existing test, `test_day2_agents.py`'s `assert
   "bash" not in _tool_names(BUG_FIX_TOOLS)`). The REAL runtime tool
   list (`BUG_FIX_TOOLS`, what `run_bug_fix()` actually passes to
   `run_agent_graph()`) was always correct — the agent's own
   role-prompt text already correctly names `submit_bug_fix`. Only the
   separate, secondary `AGENT_CONTRACT["allowed_tools"]` metadata (used
   for fleet capability-registry registration via
   `app/fleet/capability_registry.py`'s `_register()` call — consumed
   by `delegate_to_agent`'s target-agent lookups, dashboards, and
   `filter_runtime_tools()`'s high-risk-tool gate) was stale. Confirmed
   live: the registered `AgentCapability.tools` for `"bug_fix"`
   mirrored this same stale list before the fix.
   `submit_bug_fix` is not a high-risk tool, so
   `filter_runtime_tools()`'s declared-tools gate was never actually
   triggered by this mismatch — no functional runtime breakage via
   that path, but real, externally-visible wrong metadata about this
   agent's actual capabilities.

**Separately noted, NOT fixed here (explicitly out of scope for this
tool's own turn, documented rather than hidden per tool_enhance.md
§21):** `bug_fix`'s role prompt instructs "Run run_tests to verify the
fix — this is MANDATORY before submit," and its
`_VERIFICATION_CFG.enforce_in_result` overrides the submitted
`tests_passed` field based on whether a real `run_tests` call fired
during the run — but `run_tests` is not actually in `BUG_FIX_TOOLS`,
so this verification can structurally never fire, and `tests_passed`
is permanently forced to `False` regardless of what actually happened.
A real, significant gap — but about `run_tests`'s own agent-wiring
completeness (a different tool's integration into this agent), not
`submit_bug_fix` itself. Flagged in
`bhaskar_next/tool_enhance_tracking.md` for a dedicated future turn.

## Changes made

Extracted into `app/tools/agents/submit_bug_fix.py`
(`SUBMIT_BUG_FIX_TOOL`, `submit_bug_fix_handler`). The dead
`bug_fix_result` dict and `handlers["_bug_fix_result"]` export are
removed entirely — closing finding #1. `app/agents/bug_fix.py`'s
`AGENT_CONTRACT["allowed_tools"]` now lists `"submit_bug_fix"` in
place of the stale `"submit_patch"`, and the false `"bash"` claim is
removed entirely — closing finding #2.

## Tests

`tests/test_day2_agents.py::TestBugFixHandlers::test_submit_stores_result`
previously asserted directly on `h["_bug_fix_result"]["root_cause"]` —
fixed to assert on the handler's real return value instead.
`tests/test_fleet_tool_manifest.py::test_bug_fix_contract_declares_all_tools_in_manifest`
and the `bug_fix`-specific subset of `tests/test_day2_agent_contracts.py`
(6 tests) both re-run and confirmed passing with the corrected
contract.

New file `tests/test_submit_bug_fix_hardening.py`, 15 tests: schema
check, duplicate-registration check, confirmation it is correctly
absent from `CHAT_TOOLS`, re-confirmation `_bug_fix_result` is no
longer exported, direct proof the contract now declares
`submit_bug_fix` (not `submit_patch`) and no longer falsely claims
`bash`, a sweep confirming every contract-declared tool has a real
handler, re-confirmation of manifest coverage, and legitimate-usage
regression.

## Regression

This tool's own new hardening tests (15/15 pass) plus
`tests/test_day2_agents.py` + `tests/test_fleet_tool_manifest.py` (129
total across all three files). Also confirmed live via
`importlib`-reload that `app.fleet.capability_registry`'s registered
`bug_fix` capability now correctly lists `submit_bug_fix` instead of
`submit_patch`/`bash`, and re-ran the `bug_fix`-specific subset of
`tests/test_day2_agent_contracts.py` (6 tests, all pass).

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.bug_fix` and `app.agents.tools` (both clean), a `ruff
check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_new_tools.py` + `tests/test_final_session.py` tool-count
regression tests (61/61 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Two real findings (dead-code state, and a stale
agent-contract declaration that misrepresented this agent's actual
capabilities to the fleet's capability registry) identified and fixed.
No functionality lost — the one existing test that needed a change was
adjusted to test real behavior instead of dead internal state. A
significant, separate `run_tests`-wiring gap was discovered and
explicitly documented rather than silently expanded into this turn's
scope. Tool-specific and contract-related regression tests clean.
Agent alignment verified: PASS (`bug_fix.py`'s real `raw =
final_state["result"]` consumption path is unaffected by the removal
of the dead accumulator, and the fleet capability registry now
accurately reflects this agent's real tool capabilities).

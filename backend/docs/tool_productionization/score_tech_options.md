# Tool #230 — `score_tech_options` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`score_tech_options` lives entirely in `app/agents/tech_advisor_agent.py`
— a dedicated, self-contained agent module, not part of the
`app.agents.tools` monolith this initiative has been incrementally
breaking apart. Shared by exactly 1 real agent, confirmed via direct
grep — `tech_advisor_agent` itself — matching `tool_inventory.json`'s
`agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` (confirmed
via membership check). Interesting discovery history: this tool was
originally found via tool #219's audit of `list_all_tool_specs`, which
proved it was silently invisible to that introspection tool (a
completely separate, unrelated finding, already fixed on that turn) —
this is its own dedicated audit turn.

Runs genuine, deterministic weighted-sum arithmetic
(`_compute_weighted_scores()`) rather than trusting the LLM's own
claimed math — the entire point of this agent, per its own module
docstring ("the ARITHMETIC must be real, deterministic Python, never
delegated to the model's own claimed math"). `score_h`'s existing
`except (ValueError, TypeError)` guard already converts most malformed
input into clean errors.

Also verified: `handlers["_score_state"]` and `handlers["_result"]`
are **genuinely read** by `run_tech_advisor_agent()` (confirmed by
direct inspection of lines 360/366 — `raw = dict(final_state["result"]
if final_state["result"] else result)` and
`handlers["_score_state"].get("computed")`) — this is NOT the
"dead accumulator" pattern found on many other tools in this
initiative; the state capture here is real and load-bearing.

Existing tests: `tests/test_batch17_agents.py::TestTechAdvisorScoring`
(5 tests) already covers deterministic ranking, out-of-range scores,
missing criteria, empty options, and the error-string-not-raise
contract.

## Problems found

Two real, uncaught crash paths — both `AttributeError`s not covered by
`score_h`'s existing `except (ValueError, TypeError)` guard:

1. A non-dict entry in `options` (e.g. a bare string mixed into an
   otherwise well-formed list) raised an uncaught `AttributeError`
   from `opt.get(...)`. Proved live:
   ```
   options=[{"name": "A", "criteria_scores": {"x": 3}}, "not-a-dict"]
   → AttributeError: 'str' object has no attribute 'get'
   ```
2. A non-dict `weights` value (e.g. a list) raised an uncaught
   `AttributeError` from `raw_weights.get(...)`. Proved live:
   ```
   weights=["not", "a", "dict"]
   → AttributeError: 'list' object has no attribute 'get'
   ```

## Changes made

Added explicit `isinstance` validation at the top of
`_compute_weighted_scores()`: each entry in `options` must be a dict
(raises `ValueError` naming the actual offending type otherwise), and
`weights` (if provided) must be a dict. Both new checks raise a clean
`ValueError`, already caught by `score_h`'s existing except clause —
no broadening of that clause was needed, keeping error handling
precise rather than catching an overly broad exception class.

Left in place rather than force-modularized into `app/tools/` —
this is a self-contained, single-consumer, agent-local tool with no
duplication to eliminate and no `app.agents.tools` monolith
involvement, matching the judgment already applied to tool #211's
similarly self-contained `bug_fix.py` contract fix.

## Tests

Existing `TestTechAdvisorScoring` (5 tests) re-run and confirmed
passing unchanged.

New file `tests/test_score_tech_options_hardening.py`, 7 tests:
`CHAT_TOOLS` non-membership, both crash-path proofs via the real
`score_tech_options` handler, both crash-path proofs via a direct call
to `_compute_weighted_scores()` (confirming the clean `ValueError`
message), a legitimate-scoring-still-works regression, and an
equal-weighting-default regression.

## Regression

This tool's own new hardening tests (7/7 pass) plus
`test_batch17_agents.py` + `test_day8_role_prompts.py` +
`test_list_all_tool_specs_hardening.py` + `test_new_tools.py` +
`test_final_session.py` (350 passed total).

Verified via `mypy app/agents/tech_advisor_agent.py` (clean) and
`ruff check` (clean) BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Two real, empirically-verified `AttributeError` crash
paths found and fixed via evidence (live reproduction before the fix,
live proof of clean error messages after). Confirmed the tool's own
state-capture mechanism is genuinely live, not dead — no accumulator
finding here. No functionality lost — legitimate scoring, ranking, and
equal-weighting defaults all re-verified correct. Agent alignment
verified: PASS (sole consumer is `tech_advisor_agent` itself).

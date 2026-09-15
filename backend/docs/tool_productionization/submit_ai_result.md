# Tool #180 — `submit_ai_result` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `ae_submit` inside `make_ai_engineer_handlers()`.
Exactly 1 real agent declares this tool per `tool_inventory.json`:
`ai_engineer` (`app/agents/ai_engineer.py`). Deliberately NOT in
`CHAT_TOOLS` — confirmed via membership check — this is a
one-shot-agent submission tool with no interactive-chat use case,
same correct-and-intentional absence already established for sibling
tool #66's `record_learning`.

Existing tests referencing this tool: `tests/test_day3_agents.py` (2
membership-check assertions) — confirmed via grep and re-run.

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`summary`, `files_created`,
`eval_results`, `next_steps` are all free-form structured data) — no
injection surface.

## Problems found

One real finding: **dead-code accumulator, never actually read.**
`ae_submit`'s original body did `ai_result.update(inp)`, and the
factory separately exported `handlers["_ai_result"] = ai_result` — but
grepping the entire codebase found **zero real readers** of
`handlers["_ai_result"]` anywhere. Traced the actual, working
result-capture mechanism: it lives entirely in
`app/agents/base_graph.py`'s generic tool-execution node — any
`tool_name.startswith("submit_")` call sets `submitted = True` and
captures `raw_result = dict(tu_input)` (the tool call's own
LLM-supplied ARGUMENTS) directly into `state["result"]`, completely
independent of what the handler itself does internally or returns.
`ae_submit`'s local `ai_result` dict was therefore genuinely
vestigial. Also checked the separate, TEMPORARY Groq-bypass path
(`run_agent_graph`'s own generic `submit_*` wrapper, which populates
its own `tool_handlers["_result"]` key directly from `tu_input`) —
also never touches `_ai_result`.

This exact same dead-accumulator shape recurs across essentially
every sibling `*_submit` handler in `app/agents/tools.py`
(`ar_submit`, `ba_submit`, `ci_submit`, etc. — confirmed via grep,
~18 factory functions follow the identical historical pattern). Each
will be addressed on its own turn in this initiative (tools
#181/#182/#183/... for the ones still pending) rather than fixed in
bulk here, to keep each tool's own audit and verification
independently real per this initiative's "zero blind assumptions"
rule — a pattern observed in one sibling is not proof of the same
finding in another until independently confirmed.

## Changes made

Extracted into `app/tools/agents/submit_ai_result.py`
(`SUBMIT_AI_RESULT_TOOL`, `submit_ai_result_handler`). The dead
`ai_result` dict and `handlers["_ai_result"]` export are removed
entirely — `submit_ai_result_handler()` now does exactly what the
real, functioning mechanism actually needs: return the same
confirmation string as before (`"AI engineering result submitted"`),
with zero behavior change to the tool's real end-to-end effect (the
LLM's submitted arguments still flow correctly into
`state["result"]` via `base_graph.py`'s own, untouched mechanism).

## Tests

New file `tests/test_submit_ai_result_hardening.py`, 8 tests: schema
check, duplicate-registration check (in `AI_ENGINEER_TOOLS`),
confirmation it is correctly absent from `CHAT_TOOLS`, re-confirmation
`_ai_result` is no longer exported, and legitimate-usage regression
(identical confirmation string returned regardless of input shape,
repeated calls don't accumulate or leak state).

Existing tests (`tests/test_day3_agents.py`, 10 tests in the
AiEngineer-related classes, including the 2 that directly reference
`submit_ai_result`) re-run clean.

## Regression

This tool is tool 2 of the #179-#183 batch. Its own new hardening
tests (8/8 pass) plus the 10 pre-existing related tests (10/10 pass)
are the per-tool verification gate; the full suite runs once the
batch completes.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/agents/
submit_ai_result.py` sweep (102 files clean), an `importlib`-reload
sweep over all `app.agents.*` modules including `app.agents.ai_engineer`
(all clean), a `ruff check` on all touched files (clean), and a
compile()-based source escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding (dead-code state) was identified
and removed with zero change to the tool's real, working end-to-end
behavior; no functionality lost; tool-specific regression tests clean
(18/18 across new + swept existing tests).

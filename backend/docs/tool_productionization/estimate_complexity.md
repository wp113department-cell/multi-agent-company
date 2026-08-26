# Tool #110 — `estimate_complexity` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two real, byte-identical implementations: `sp_estimate_complexity`
(`make_sprint_planner_handlers`) and `estimate_complexity_h` (inside
`make_chat_handlers()`). `chat_agent.py` had ZERO dispatch branch
despite the tool being fully advertised in `CHAT_TOOLS` — the same
"advertised but never dispatched" class already established for tools
#4/#6/#22/#25/#33/#44/#45/#46/#48/#100/#103.

Per `tool_inventory.json`, agents declaring `estimate_complexity` go
through one of the two factories above. `CHAT_TOOLS.count(
"estimate_complexity") == 1` verified. 2 existing test files
reference this tool — 1 (`test_cost_controller.py`) is an unrelated
function with a similar name in a different concept, not a real
match; the other (`test_day3_agents.py`) genuinely exercises the real
handler, re-run and confirmed passing unchanged.

No LLM-controlled input can cause any real effect beyond the returned
text: `description` is only measured with `str.split()` (word count),
and `context_paths` is only measured with `len()` — the actual path
strings are never read from disk, resolved, or passed to any
subprocess, so the usual worktree-escape/injection classes established
throughout this initiative are structurally impossible here regardless
of what a caller puts in that list.

## Problems found

**Finding — "advertised but never dispatched."** Every real
interactive call would have hit "Unknown tool". The underlying
heuristic (word count + `10 * file count`, bucketed into XS/S/M/L/XL)
was already correct and identical across both implementations — this
is not a placeholder, and required no fix itself.

## Changes made

Extracted the existing, already-correct heuristic into
`estimate_complexity_handler()` in
`app/tools/execution/estimate_complexity.py` (no behavior change), and
wired a new, real `chat_agent.py` dispatch to it — closing the only
real finding. `app/agents/tools.py`'s `_ESTIMATE_COMPLEXITY_TOOL` now
aliases the shared `ESTIMATE_COMPLEXITY_TOOL` constant. No external
direct-importers found.

## Tests

New file `tests/test_estimate_complexity_hardening.py`, 11 tests, all
real (no mocking — this is a pure function) — schema check,
duplicate-registration check, proof the dispatch now exists at all, 5
pure-heuristic correctness tests (XS/XL bucketing, context-path
counting, a real proof that nonexistent/sensitive paths like
`/etc/shadow` in `context_paths` are never read or resolved — only
counted, missing-description default), and legitimate-usage regression
across all three real access paths. Existing tests
(`test_day3_agents.py::TestSprintPlannerHandlers`) re-run and
confirmed passing unchanged (2 tests).

## Regression

This tool is tool 2 of the current #109-#113 batch. Its own new
hardening tests (11/11 pass) and directly-referencing existing tests
(2/2 pass) are the per-tool verification gate; the full suite runs
once the batch completes, per `feedback_tool_enhance_batch_full_suite`
memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
estimate_complexity.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all 97 `app/agents/` modules
(all clean), a `ruff check` on all 3 touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The only real finding — a completely missing
interactive dispatch — proved and closed; the underlying heuristic was
already correct and is verified to never touch disk regardless of
`context_paths` content; no functionality lost; tool-specific and
directly-referencing regression tests clean.

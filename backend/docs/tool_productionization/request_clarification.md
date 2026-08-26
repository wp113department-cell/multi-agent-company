# Tool #117 — `request_clarification` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `make_request_clarification_handler(agent_name,
task_id)`, a single factory function used by exactly two real call
sites — `app/agents/coder.py:161` and `app/agents/planner.py:157` —
both `run_agent_graph`-based one-shot worker agents. Confirmed by
reading both call sites' actual arguments, not just their count.

Deliberately absent from `CHAT_TOOLS` — verified `chat_agent.py` has
zero reference to it at all. This is intentional: the tool is scoped
to worker-agent graphs (`base_graph.py`) that have no
checkpointer/`interrupt()`/`Command(resume=...)` machinery of their
own (that only exists in `app/pipeline/graph.py`'s separate
pm→architect→decomposer pipeline). The "advertised but never
dispatched" bug class found repeatedly this initiative does not apply
here since it was never advertised to chat in the first place.

6 existing test files reference this tool
(`test_confidence_gated_control_flow.py`,
`test_batch12_coder_clarification.py`,
`test_phase53_request_clarification.py`,
`test_audit_q_batch07_guardian_human_interaction.py`,
`test_status_transitions.py`,
`test_gap_stage16_hard_constraint_clarification.py`) — 67 tests total,
re-run and confirmed passing unchanged.

## Problems found

**None.** Audited for every finding class established so far in this
initiative:

- **Shell/flag injection**: no filesystem path, no subprocess call,
  no external program invocation anywhere in this tool's input schema
  or handler.
- **Worktree-boundary escape / SSRF**: no filesystem path or network
  destination anywhere in the schema (`question`, `context`,
  `options`, `recommended_option` are all free-form structured text,
  never used to build a path or URL).
- **SQL injection**: `question`/`context`/`options`/
  `recommended_option` reach `request_human_input()` as plain
  structured data, stored via the ORM (`PendingApproval.details`, a
  JSONB column) through `record_pending()` — never string-interpolated
  into raw SQL.
- **Attribution/spoofing**: `agent_name`/`task_id` are never
  LLM-controlled — both real call sites pass the calling agent's own
  fixed name and the graph's own numeric task id as
  `make_request_clarification_handler(agent_name, task_id)`
  constructor arguments, not through the LLM-controlled `inp` dict.
- **Asyncio/shared-engine violation**: `record_pending()`'s sync/async
  bridge (`app/fleet/approval_gate.py::_record_pending`) already uses
  `_new_isolated_db_engine()`, matching this initiative's own
  established "never `asyncio.run()` against the shared
  `app.db.session` engine from sync code" rule — already correct.
- **Unhandled crash**: handler failures are already caught and
  reported as an `[ERROR]` string, never raised — verified via the
  existing `test_handler_failure_is_reported_not_raised` test and a
  new equivalent in this turn's own hardening file.

## Changes made

Pure modularization — moved `REQUEST_CLARIFICATION_TOOL` and
`make_request_clarification_handler()` verbatim into
`app/tools/agents/request_clarification.py`, matching the identical
"single factory, no fix required" precedent already established by
tool #66 (`record_learning`). `app/agents/tools.py` re-exports both
names unchanged (`as`-aliased self-re-export, same pattern as every
other moved name, required for `mypy --strict`'s "explicitly exported"
check to follow through to `coder.py`/`planner.py`'s direct imports).

## Tests

New file `tests/test_request_clarification_hardening.py`, 6 tests:
schema check, `CHAT_TOOLS`-absence check (confirming the deliberate
scoping decision, not a missed dispatch), missing/blank-question
rejection, a failure-is-reported-not-raised proof, and a real
end-to-end test that writes to the real approval-gate store and
verifies via a direct DB query (skipped without a real `DATABASE_URL`,
matching this codebase's existing convention).

Existing tests re-run and confirmed passing: all 6 referencing test
files, 67 tests total.

## Regression

This tool is tool 4 of the #114-#118 batch. Its own new hardening
tests (6/6 pass) and all 6 directly-referencing existing test files
(67/67 pass) are the per-tool verification gate; the full suite runs
once the batch completes, per `feedback_tool_enhance_batch_full_suite`
memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/agents/
request_clarification.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** No vulnerability found after a full audit against
every finding class this initiative has established — the single real
implementation was already correct by construction. Pure
modularization with real, empirical verification that the safe design
holds (not assumed from reading alone); no functionality lost;
tool-specific and directly-referencing regression tests clean.

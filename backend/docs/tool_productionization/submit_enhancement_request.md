# Tool #212 — `submit_enhancement_request` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: the `make_submit_enhancement_request_handler()`
factory in `app/agents/tools.py`, shared by every real caller.
`tool_inventory.json` reports `agent_count: 5`, but a direct grep of
every real `make_submit_enhancement_request_handler(` call site found
**8** real agents genuinely using this tool: `agent_advisor`,
`agent_debugger`, `agent_performance_reviewer`, `architecture_reviewer`
(its SCAN phase), `dependency_security_agent`, `knowledge_curator`,
`monitoring_agent` (its SCAN phase), and `quality_auditor`. The
inventory's "5" matches a stale comment still sitting in `tools.py`
("Shared by the 5 self-improvement agents...") that predates 3 of
these 8 real callers being added — a documentation lag, not a
functional bug. Deliberately NOT in `CHAT_TOOLS` — confirmed via
membership check.

## Audit of injection surface (checked, no issue found)

- The DB write (`EnhancementRequest(...)`) goes through the SQLAlchemy
  ORM exclusively — no raw SQL string interpolation anywhere.
- The best-effort impact simulation
  (`app.fleet.enhancement_impact.simulate_enhancement_impact`)
  extracts `file:line` citations from the LLM-controlled
  `description`/`evidence` fields via a regex whose character class is
  restricted to `[A-Za-z0-9_./-]` — no regex metacharacters can appear
  in an extracted citation, ruling out a `grep -E` ReDoS/regex-injection
  via `_find_referencing_files()`'s pattern construction. Also
  confirmed directly: `_find_referencing_files()` never opens a file
  at the extracted `rel_path` itself — it only derives a search term
  (the file's basename stem) and greps the *fixed* `repo_root`
  argument, so no worktree-escape read is possible even with a
  traversal-shaped citation string.
- Both the DB write and the dashboard push are already wrapped in
  their own `try`/`except`; a missing required `inp` key inside either
  block is already caught by its enclosing `except Exception`.
- `agent_name`/`trace_id`/`repo_path` are factory-time arguments each
  real caller hardcodes at construction time — never LLM-controlled.

## Problems found

One real, narrow finding: the DB write used a local, less-completely-
configured duplicate of the canonical isolated-engine helper.
`_new_isolated_db_engine()` (still defined in `app/agents/tools.py`,
used by 4 OTHER tools — `memory_search`, `memory_curate_read`,
`memory_curate_write`, `git_commit_change` — each with its own future
tool_enhance.md turn, deliberately NOT touched here) creates its
engine with only `pool_pre_ping=True`, omitting the explicit
`pool_size`/`max_overflow`/`connect_args` the canonical
`app.db.session.new_isolated_async_engine()` sets — the same
throwaway-engine helper `capability_gap_scan_handler()` (tool #210)
already uses. Per that canonical function's own docstring, omitting
these "silently fall[s] back to SQLAlchemy's smaller async defaults"
and skips whatever `connect_args` a real deployment's settings
require.

## Changes made

Extracted into `app/tools/agents/submit_enhancement_request.py`
(`SUBMIT_ENHANCEMENT_REQUEST_TOOL`,
`make_submit_enhancement_request_handler`), switching the DB write to
the canonical `new_isolated_async_engine()` helper, closing the
finding. `app/agents/tools.py` re-exports the schema and factory under
their old names (using a self-aliasing import to keep both mypy's
explicit-reexport check and ruff's unused-import check satisfied) — all
8 real consumer files continue `from app.agents.tools import
make_submit_enhancement_request_handler` completely unchanged,
deliberately not individually edited, to minimize blast radius across
8 files for a tool this widely shared.

## Tests

7 existing test files already exercise this tool across its real call
sites (124 tests combined) — all re-run and confirmed passing
unchanged, no fix needed.

New file `tests/test_submit_enhancement_request_hardening.py`, 6
tests: schema check, confirmation it is correctly absent from
`CHAT_TOOLS`, a real end-to-end DB write with verification and cleanup
(no mocking), a real impact-simulation proof using a genuine file
citation against this actual repo, a clean `[ERROR]` proof on missing
required input, and a regex/ReDoS regression guard confirming
crafted metacharacter-shaped citation text cannot reach `grep -E` as
live metacharacters.

## Regression

This tool's own new hardening tests (6/6 pass) plus all 7 existing
test files (124 tests) plus `tests/test_final_session.py` (25 tests) —
**155 passed** combined. Also directly `importlib`-reload-verified all
8 real consumer agent modules (`agent_advisor`, `agent_debugger`,
`agent_performance_reviewer`, `architecture_reviewer`,
`dependency_security_agent`, `knowledge_curator`, `monitoring_agent`,
`quality_auditor`) still import cleanly and resolve the re-exported
factory correctly.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean — required a self-aliasing import fix for the
re-exported factory name to satisfy mypy's explicit-reexport check)
and a `ruff check` on all touched files (clean) and a `CHAT_TOOLS`
duplicate-registration check (clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** No injection surface found after a thorough audit of
the full real call graph (DB write, impact simulation, and dashboard
push); one real, narrow finding (a less-completely-configured
duplicate connection-pool helper) identified and fixed for this tool
specifically. No functionality lost — all 8 real consumer agents
verified to still resolve the tool correctly after modularization, all
existing tests pass unchanged. Agent alignment verified: PASS (all 8
real callers' imports independently re-confirmed via live
`importlib` reload).

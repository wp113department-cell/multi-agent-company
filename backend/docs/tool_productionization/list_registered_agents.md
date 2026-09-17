# Tool #222 — `list_registered_agents` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Module-level function `list_registered_agents()` in
`app/agents/tools.py`, the last of the 3 Day-53 "real introspection,
never a guess" tools to be audited in this initiative (`list_all_tool_specs`
was tool #219, `list_migrations` was tool #221). Shared by exactly 1
real agent, confirmed via direct grep — `agent_roster_doc_agent` —
matching `tool_inventory.json`'s `agent_count: 1` exactly. Deliberately
NOT in `CHAT_TOOLS` (confirmed via membership check). Takes no
meaningful input at all (`inp` is unused; schema declares no
properties).

Calls `ensure_all_agents_registered()` (imports every real agent
module under `app/agents/`, scanning the directory at runtime rather
than a hardcoded name list, so its own `_register()` hook fires for
each) before reading `get_capability_registry().all()` — real,
directly-introspected agent contracts for `agent_roster_doc_agent` to
write an accurate agent roster from.

Already has thorough test coverage in
`tests/test_gap53_doc_generators.py::TestListRegisteredAgents` (3
tests, including a fleet-wide duplicate-capability-tag regression
guard — CLAUDE.md's own rule that no two agents may claim the same
capability tag) — re-read and re-verified as still passing before
making any change.

## Problems found

None. No security vulnerability and no functional bug found — this
audit's real conclusion. Specifically investigated:

- **Completeness** (the exact class of defect just found and fixed on
  tool #219's sibling `list_all_tool_specs`, which only scanned one
  module): this tool is already correct — `ensure_all_agents_registered()`
  is a genuine full-codebase scan (every `.py` file under `app/agents/`,
  excluding known non-agent modules), confirmed by comparing its real
  output count (85 real registered agents) against direct inspection.
- **Crash risk**: `ensure_all_agents_registered()` never raises by its
  own contract and implementation — a `try`/`except Exception` wraps
  each individual module import, so one broken agent module cannot
  break registration for every other agent.
- **Thread-safety / injection surface**: `CapabilityRegistry.all()` is
  a simple, lock-protected read of an in-memory dict; no external I/O,
  no user input reaches any part of this call.
- **Idempotency**: registration is write-once-per-name/update-in-place
  (a dict keyed by agent name) — repeated calls in the same process
  (e.g. multiple doc-generation runs) don't duplicate-accumulate,
  proved live via two consecutive calls returning identical name sets.

## Changes made

Extracted into `app/tools/agents/list_registered_agents.py`
(`LIST_REGISTERED_AGENTS_TOOL`, `list_registered_agents_handler`) with
zero behavior change. `app/agents/tools.py` now re-exports both names
for backward compatibility — the real consumer agent
(`agent_roster_doc_agent`) continues
`from app.agents.tools import list_registered_agents` unchanged,
verified by identity.

## Tests

Existing `TestListRegisteredAgents` (3 tests) re-run and confirmed
passing unchanged — full file (32 tests) also re-run clean.

New file `tests/test_list_registered_agents_hardening.py`, 6 tests:
schema check, `CHAT_TOOLS` non-membership, real-agents-with-full-contract-fields
regression, an idempotency proof (two consecutive calls return
identical name sets), and two object-identity proofs (the re-exported
handler in `tools.py`, and the real consumer agent's wired handler)
that the move introduced no behavior change.

## Regression

This tool's own new hardening tests (6/6 pass) plus
`test_gap53_doc_generators.py` + `test_new_tools.py` +
`test_final_session.py` (99 passed total).

Verified via `mypy` (2 touched files, clean) and `ruff check` (2
touched files, clean) BEFORE claiming GREEN_FLAG. Also verified
`CHAT_TOOLS` still has zero duplicate names (186 entries) and that
`app.agents.tools` reloads cleanly.

## Final verdict

**GREEN FLAG.** Thorough audit found no security vulnerability and no
functional defect — this tool's completeness (the exact class of issue
found on its sibling `list_all_tool_specs`) was specifically checked
and confirmed already correct. No functionality lost — the real
consumer agent verified via identity to still use the exact same
shared handler; idempotency and full-contract-field coverage
re-verified. Agent alignment verified: PASS.

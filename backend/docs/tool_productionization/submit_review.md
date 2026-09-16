# Tool #195 — `submit_review` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: the `submit_review` closure inside
`make_reviewer_handlers()`. Exactly 1 real agent declares this tool
per `tool_inventory.json`: `reviewer` (`app/agents/reviewer.py`, via
`run_reviewer()`). Deliberately NOT in `CHAT_TOOLS` — confirmed via
membership check (count is 0) — a batch agent, never exposed to
interactive chat.

**Important difference from sibling tools #180-#186/#188-#190/#192,
same class as tools #187/#191/#193**: this is NOT a dead accumulator.
`run_reviewer()` does not use `run_agent_graph`'s generic
`final_state["result"]` submit_* capture mechanism at all for this
agent — instead it reads `handlers.get("_review_result", {})`
directly (confirmed by reading the full function body), and builds
its returned `ReviewResult` dataclass entirely from that dict's
`findings`/`verdict`/`summary` keys. `run_reviewer()`'s own exception
path (a real agent-run failure) never touches `_review_result` at
all, producing a synthetic "blocking" finding instead. This is a
real, live, genuinely necessary result sink — the opposite of tools
#180-#186/#188-#190/#192's finding class.

`make_reviewer_handlers()` has no other real entries besides the
inherited read-only handlers (`make_read_only_handlers()`) — the
agent is explicitly read-only, no bash/write/edit capability.

Existing tests referencing this tool: `tests/test_session3_migration.py`
(patches `_review_result` directly and verifies `run_reviewer()`'s
consumption of it, on both a populated and an empty dict — already
correct; also explicitly tracks `submit_review` in its own
`_SUBMIT_PRIVATE` set alongside `submit_qa_result`/
`submit_health_report`, the same real-accumulator class),
`tests/test_tool_scoping.py` (tool-name membership, unaffected), and
`tests/test_fleet_tool_manifest.py` (manifest entry name, unaffected).
None required a change.

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`findings` is free-form
structured data, `verdict`/`summary` are strings — the agent is
read-only, no filesystem/network/SQL capability exists anywhere in
`make_reviewer_handlers()` for this input to reach) — no injection
surface.

## Problems found

None. No security vulnerability and no functional bug found in the one
real implementation.

## Changes made

Modularized purely for consistency with the already-established
`make_submit_docs_handler`/`make_submit_health_report_handler`/
`make_submit_qa_result_handler`/`make_submit_research_handler` pattern
(tools #85/#187/#191/#193): extracted into
`app/tools/agents/submit_review.py` (`SUBMIT_REVIEW_TOOL`,
`make_submit_review_handler`). The factory takes the externally-owned
`review_result` dict (still created and exported by
`make_reviewer_handlers()` exactly as before) rather than owning it
itself — preserving the exact existing contract `run_reviewer()`
relies on.

## Tests

No existing test required a fix — `test_session3_migration.py`,
`test_tool_scoping.py`, and `test_fleet_tool_manifest.py` all already
assert on real, correctly-preserved behavior.

New file `tests/test_submit_review_hardening.py`, 10 tests: schema
check, duplicate-registration check (in `REVIEWER_TOOLS`),
confirmation it is correctly absent from `CHAT_TOOLS`, and — unlike
the dead-accumulator siblings — direct proof the factory mutates the
exact dict object it was given (not a copy), that
`make_reviewer_handlers()` exports that same object, that repeated
calls accumulate via `update()` exactly as before, and that
independent handler instances don't share state.

## Regression

Full `test_submit_review_hardening.py` + `test_tool_scoping.py` +
`test_fleet_tool_manifest.py` + `test_session3_migration.py`: 152
passed, 0 failed.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.reviewer` and `app.agents.tools` (both clean), a `ruff
check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_new_tools.py` + `tests/test_final_session.py` tool-count
regression tests (61/61 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** No security or functional defect found; the tool was
already correctly wired and genuinely consumed by its one real caller.
Modularized for structural consistency only, with zero behavior
change and zero existing test needing a fix. Tool-specific regression
tests clean (152/152). Agent alignment verified: PASS
(`reviewer.py`'s real `handlers.get("_review_result", {})`
consumption path is unaffected — the factory still mutates the same
dict object `make_reviewer_handlers()` exports).

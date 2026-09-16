# Tool #193 — `submit_research` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: the `submit_research` closure inside
`make_research_handlers()`. Exactly 1 real agent declares this tool
per `tool_inventory.json`: `research` (`app/agents/research.py`, via
`run_research()`). Deliberately NOT in `CHAT_TOOLS` — confirmed via
membership check (count is 0) — a batch agent, never exposed to
interactive chat.

**Important difference from sibling tools #180-#186/#188-#190/#192,
same class as tools #187/#191**: this is NOT a dead accumulator.
`run_research()` does not use `run_agent_graph`'s generic
`final_state["result"]` submit_* capture mechanism at all for this
agent — instead it reads `handlers.get("_research_result", {})`
directly (confirmed by reading the full function body), and builds
its returned `ResearchReport` dataclass entirely from that dict's
`findings`/`relevantLibraries`/`recommendedApproach`/`risks` keys,
with an explicit "Research agent did not call submit_research"
fallback error path when it's empty. `run_research()` also separately
tracks whether the tool was called at all via
`VerificationConfig.set_by={"submit_research": "research_submitted"}`
— an independent verification signal from the result-content dict
itself, unaffected by this change. This is a real, live, genuinely
necessary result sink — the opposite of tools
#180-#186/#188-#190/#192's finding class.

`make_research_handlers()`'s other real entry (`web_search`) is
already its own separately-productionized tool (GREEN_FLAGGED as tool
#88) — deliberately untouched here, out of scope for this tool's own
turn.

Existing tests referencing this tool: `tests/test_session4_migration.py`
(patches `make_research_handlers` to return `{"_research_result":
...}` and verifies `run_research()`'s consumption of it, on both a
populated and an empty dict — already correct). No change required.

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`findings`, `relevantLibraries`,
`recommendedApproach`, `risks` are all free-form structured/string
data — the agent's real research already happened via its own
separately gated `read_file`/`search_code`/`web_search` handlers
before this tool is ever called) — no injection surface.

## Problems found

None. No security vulnerability and no functional bug found in the one
real implementation.

## Changes made

Modularized purely for consistency with the already-established
`make_submit_docs_handler`/`make_submit_health_report_handler`/
`make_submit_qa_result_handler` pattern (tools #85/#187/#191):
extracted into `app/tools/agents/submit_research.py`
(`SUBMIT_RESEARCH_TOOL`, `make_submit_research_handler`). The factory
takes the externally-owned `research_result` dict (still created and
exported by `make_research_handlers()` exactly as before) rather than
owning it itself — preserving the exact existing contract
`run_research()` relies on. The shared `web_search` entry in the same
factory function is untouched, out of scope for this tool's own turn.

## Tests

No existing test required a fix — `test_session4_migration.py`
already asserts on real, correctly-preserved behavior
(`handlers["_research_result"]`).

New file `tests/test_submit_research_hardening.py`, 11 tests: schema
check, duplicate-registration check (in `RESEARCH_TOOLS`),
confirmation it is correctly absent from `CHAT_TOOLS`, and — unlike
the dead-accumulator siblings — direct proof the factory mutates the
exact dict object it was given (not a copy), that
`make_research_handlers()` exports that same object, that repeated
calls accumulate via `update()` exactly as before, and that
independent handler instances don't share state.

## Regression

This tool is tool 5 of the #189-#193 batch — **BATCH COMPLETE**. Its
own new hardening tests (11/11 pass) plus the unaffected 86 total
tests across `test_submit_research_hardening.py` +
`test_session4_migration.py` are the per-tool verification gate; the
full batch suite runs next.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.research` and `app.agents.tools` (both clean), a `ruff
check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_new_tools.py` + `tests/test_final_session.py` tool-count
regression tests (61/61 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** No security or functional defect found; the tool was
already correctly wired and genuinely consumed by its one real caller.
Modularized for structural consistency only, with zero behavior
change and zero existing test needing a fix. Tool-specific regression
tests clean (86/86). Agent alignment verified: PASS
(`research.py`'s real `handlers.get("_research_result", {})`
consumption path, and its separate `research_submitted` verification
signal, are both unaffected by this change).

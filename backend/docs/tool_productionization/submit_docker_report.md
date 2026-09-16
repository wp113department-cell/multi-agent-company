# Tool #186 — `submit_docker_report` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `dk_submit` inside
`make_docker_agent_handlers()`. Exactly 1 real agent declares this
tool per `tool_inventory.json`: `docker_agent`
(`app/agents/docker_agent.py`). Deliberately NOT in `CHAT_TOOLS` —
confirmed via membership check (count is 0) — same correct-and-
intentional absence already established for sibling tools
#66/#180/#181/#182/#183/#184/#185.

`make_docker_agent_handlers()`'s other handlers (`docker_ps`,
`docker_logs`, `docker_exec`, `docker_compose`, `docker_build`,
`docker_restart`, `diagnose_deployment_failure`, `write_file`) are
each their own separately-productionized tool (several already
GREEN_FLAGGED as tools #18/#19/#20/#106/#108/#109/#12) — deliberately
untouched here, out of scope for this tool's own turn.

Existing tests referencing this tool:
`tests/test_day2_agents.py::TestDockerAgentHandlers` (4 tests, one of
which directly asserted on the now-removed `_docker_result` — see
Tests section).

## Audit of injection surface (checked, no issue found)

No filesystem path, network destination, or subprocess/SQL target
anywhere in this tool's input schema (`action`, `outcome`,
`files_written` are all free-form strings/structured data — any real
docker action already happened via the agent's own separately gated
docker_* handlers before this tool is ever called) — no injection
surface.

## Problems found

One real finding, same class and shape as sibling tools
#180/#181/#182/#183/#184/#185: **dead-code accumulator, never actually
read.** `dk_submit`'s original body did `docker_result.update(inp)`,
and the factory separately exported `handlers["_docker_result"] =
docker_result` — but grepping the entire production codebase found
zero real readers. Traced the actual, working result-capture
mechanism: it lives entirely in `app/agents/base_graph.py`'s generic
tool-execution node (`tool_name.startswith("submit_")` → captures
`dict(tu_input)` directly into `state["result"]`), confirmed by
reading `docker_agent.py`'s own `raw = final_state["result"]` line —
that is what real production code actually consumes, completely
independent of `docker_result`/`_docker_result`.

## Changes made

Extracted into `app/tools/agents/submit_docker_report.py`
(`SUBMIT_DOCKER_REPORT_TOOL`, `submit_docker_report_handler`). The
dead `docker_result` dict and `handlers["_docker_result"]` export are
removed entirely — `submit_docker_report_handler()` now does exactly
what the real, functioning mechanism actually needs: return the same
confirmation string as before (`"Docker report submitted"`), with
zero behavior change to the tool's real end-to-end effect. All other
`make_docker_agent_handlers()` handlers left byte-for-byte unchanged.

## Tests

`tests/test_day2_agents.py::TestDockerAgentHandlers::test_submit_stores_result`
previously asserted directly on `h["_docker_result"]["outcome"]` — an
internal implementation detail now confirmed dead and removed. Fixed
by asserting on the handler's real return value instead (`"Docker
report submitted"`), preserving the test's actual intent (a real
submission succeeds) without relying on dead internal state. All 4
tests in that class pass after the fix.

New file `tests/test_submit_docker_report_hardening.py`, 9 tests:
schema check, duplicate-registration check (in `DOCKER_AGENT_TOOLS`),
confirmation it is correctly absent from `CHAT_TOOLS`, re-confirmation
`_docker_result` is no longer exported, legitimate-usage regression
(identical confirmation string returned regardless of input shape,
repeated calls don't accumulate or leak state), and a sweep confirming
every sibling handler in the same factory is still wired.

## Regression

This tool is tool 3 of the #184-#188 batch. Its own new hardening
tests (9/9 pass) plus the fixed 4 existing tests (4/4 pass, 83 total
across both files) are the per-tool verification gate; the full batch
suite runs after tool #188.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.docker_agent` and `app.agents.tools` (both clean), a
`ruff check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_new_tools.py` + `tests/test_final_session.py` tool-count
regression tests (61/61 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding (dead-code state) was identified
and removed with zero change to the tool's real, working end-to-end
behavior; no functionality lost (the one existing test that needed a
change was adjusted to test real behavior instead of dead internal
state, not weakened); tool-specific regression tests clean (83/83
across new + fixed existing tests). Agent alignment verified: PASS
(`docker_agent.py`'s real `raw = final_state["result"]` consumption
path is unaffected by the removal of the dead accumulator).

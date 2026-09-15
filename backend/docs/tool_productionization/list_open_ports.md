# Tool #164 — `list_open_ports` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `list_open_ports_h` inside
`make_chat_handlers()`.

The input schema is empty (no properties at all) — no LLM-controlled
input reaches this tool, so the worktree-boundary-escape and injection
classes established repeatedly this initiative do not apply. Both
commands (`ss -tlnp`, falling back to `netstat -tlnp`) are fixed
literal argv lists run via list-args `subprocess.run()`, never
`shell=True` — no command-injection surface exists either, checked
directly.

`list_open_ports` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see the finding
below.

Zero existing tests referenced this tool — confirmed via grep, no
sweep needed.

## Problems found

One real, empirically-verified finding.

**Advertised but never dispatched on the interactive chat agent, same
class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163.**
`list_open_ports` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: list_open_ports"`.

## Changes made

New shared `list_open_ports_handler()` in
`app/tools/execution/list_open_ports.py`, containing the unchanged
`ss`/`netstat` fallback logic. A new `chat_agent.py` dispatch branch
delegates to this shared handler, closing the finding —
`list_open_ports` is now genuinely reachable from interactive chat for
the first time. `app/agents/tools.py`'s `_LIST_OPEN_PORTS_TOOL` now
aliases the shared `LIST_OPEN_PORTS_TOOL` constant.

## Tests

New file `tests/test_list_open_ports_hardening.py`, 6 tests: schema
check, duplicate-registration check, a proof the new dispatch no
longer returns "Unknown tool", and legitimate-usage regression (real
live `ss`/`netstat` output on all 3 real access paths, nothing
mocked).

Zero existing tests referenced this tool — confirmed, no sweep
needed.

## Regression

This tool is tool 1 of a new #164-#168 batch. Its own new hardening
tests (6/6 pass) are the per-tool verification gate; the full suite
runs once the batch completes, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
list_open_ports.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), a
`python -W error` docstring escape-sequence check on the new module
(clean), and a `CHAT_TOOLS.count("list_open_ports") == 1` check
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding was proved live and closed; the
tool is now genuinely reachable from interactive chat for the first
time — a strict capability increase, not a narrowing; no functionality
lost; tool-specific regression tests clean (6/6).

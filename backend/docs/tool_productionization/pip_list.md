# Tool #172 — `pip_list` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `pip_list_h` inside `make_chat_handlers()`.

`pip_list` is in `CHAT_TOOLS` and registered in `make_chat_handlers()`'s
handlers dict, but `chat_agent.py`'s `_execute_tool()` had zero
dispatch branch for it — see finding below.

Existing tests referencing this tool: `tests/test_new_tools.py`'s
`test_pip_list` and `test_pip_list_filter` (2 tests) — confirmed via
grep and re-run.

## Audit of the flag-collision class (checked, NOT vulnerable)

`filter` was checked for the same shell/CLI-flag-collision class
found in sibling tools this initiative (e.g. #5/#32/#148/#149/#158).
It is **not vulnerable**: `filter` never reaches a subprocess or
shell at all. The one real `subprocess.run([sys.executable, "-m",
"pip", "list", "--format=columns"], ...)` call has zero
LLM-controlled arguments — `filter` is applied afterward as a pure
in-memory Python substring check (`name_filter.lower() in
ln.lower()`) against the already-captured stdout lines. Proved live:
`pip_list({"filter": "-n"})` and `pip_list({"filter": "; touch
/tmp/PWNED_pip_list_test ;"})` both behaved as ordinary (harmless)
substring filters — no argv reinterpretation, no shell metacharacter
execution, no marker file created. Same no-injection-surface shape as
sibling tool #165's `list_processes`.

## Problems found

One real finding.

**Advertised but never dispatched on the interactive chat agent, same
class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168/#169/#170/#171.**
`pip_list` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: pip_list"`.

## Changes made

New shared `pip_list_handler()` in `app/tools/execution/pip_list.py`
— logic unchanged (no security fix needed; the audit above confirmed
it already safe). A new `chat_agent.py` dispatch branch delegates to
this shared handler, closing the finding — `pip_list` is now
genuinely reachable from interactive chat for the first time.

`app/agents/tools.py`'s `_PIP_LIST_TOOL` now aliases the shared
`PIP_LIST_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_pip_list_hardening.py`, 9 tests: schema check,
duplicate-registration check, re-confirmation that flag-shaped and
shell-metacharacter-shaped `filter` values are inert (no injection),
a proof the new dispatch no longer returns "Unknown tool" and
respects `filter`, and legitimate-usage regression (real installed
packages listed and correctly filtered on both access paths).

Existing tests (`tests/test_new_tools.py`'s `test_pip_list` /
`test_pip_list_filter`, 2 tests) re-run clean.

## Regression

This tool is tool 4 of the #169-#173 batch. Its own new hardening
tests (9/9 pass) plus the 2 pre-existing tests (2/2 pass) are the
per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/pip_list.py`
sweep (102 files clean), an `importlib`-reload sweep over all
`app.agents.*` modules (all clean), a `ruff check` on all touched
files (clean), a compile()-based source escape-sequence check on the
new module (clean), and a `CHAT_TOOLS.count("pip_list") == 1` check
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding was proved live and closed; the
tool is now genuinely reachable from interactive chat for the first
time — a strict capability increase, not a narrowing; no
functionality lost; tool-specific regression tests clean (11/11
across new + swept existing tests).

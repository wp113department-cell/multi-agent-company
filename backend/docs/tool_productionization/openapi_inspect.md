# Tool #169 — `openapi_inspect` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `openapi_inspect_h` inside
`make_chat_handlers()`.

`openapi_inspect` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

Existing tests referencing this tool: `tests/
test_audit_q_batch09_large_project_file_tech.py`'s
`TestOpenapiInspect` (3 tests) plus a parametrized manifest-coverage
check — confirmed via grep and re-run.

## Problems found

Two real, empirically-verified findings.

**Finding #1 — a worktree-boundary escape that is a genuine
STRUCTURED FILE CONTENT DISCLOSURE oracle.** `openapi_inspect_h`
built `root / path` without ever validating it stayed inside the
worktree — the same `pathlib`-silently-discards-`root`-for-an-
absolute-right-operand class already documented for tools
#99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144/#146/#154/#158/#166.
Proved live: `openapi_inspect({"path": "/tmp/<outside file>"})`
genuinely disclosed the real title, API version, endpoint paths, HTTP
methods, and operation summaries of a file entirely outside the
intended worktree. Distinct from this tool's sibling
`inspect_openapi_spec` (#157), which fetches from a URL or accepts
`spec_text` directly — this tool's whole purpose is reading a LOCAL
file, so the worktree boundary is the entire real-world protection
this class of tool has.

**Finding #2 — advertised but never dispatched on the interactive
chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168.**
`openapi_inspect` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: openapi_inspect"`.

## Changes made

New shared `openapi_inspect_handler()` in `app/tools/filesystem/
openapi_inspect.py`: `path` is now validated with
`check_path_in_worktree()` (checked for both relative traversal and
absolute-path escapes) before the file is ever read, closing finding
#1. A new `chat_agent.py` dispatch branch delegates to this same
shared handler, closing finding #2 — `openapi_inspect` is now
genuinely reachable from interactive chat for the first time.

`app/agents/tools.py`'s `_OPENAPI_INSPECT_TOOL` now aliases the
shared `OPENAPI_INSPECT_TOOL` constant. No external direct-importers
of the old names were found.

## Tests

New file `tests/test_openapi_inspect_hardening.py`, 11 tests: schema
check, duplicate-registration check, worktree-escape-blocked proof
(absolute and relative traversal, across all 3 real access paths)
with an assertion the outside spec's real title/endpoints never leak
into the result, a proof the new dispatch no longer returns "Unknown
tool", and legitimate-usage regression (real spec parsing, missing-
file error, non-OpenAPI-file rejection).

Existing tests (`tests/test_audit_q_batch09_large_project_file_tech.py`'s
`TestOpenapiInspect`, 3 tests, plus a parametrized manifest test) re-run
clean.

## Regression

This tool is tool 1 of a new #169-#173 batch. Its own new hardening
tests (11/11 pass) plus the 4 pre-existing tests (4/4 pass) are the
per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
openapi_inspect.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), a
`python -W error` docstring escape-sequence check on the new module
(clean), and a `CHAT_TOOLS.count("openapi_inspect") == 1` check
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed; the tool
is now genuinely reachable from interactive chat for the first time —
a strict capability increase, not a narrowing; no functionality lost;
tool-specific regression tests clean (15/15 across new + swept
existing tests).

# Tool #144 — `generate_api_docs_text` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `generate_api_docs_text_h` inside
`make_chat_handlers()`.

`generate_api_docs_text` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

Zero existing tests referenced this tool — confirmed via grep, no
sweep needed.

## Problems found

Two real, empirically-verified findings.

**Finding #1 — a worktree-boundary escape that is a genuine
ROUTE/FUNCTION-NAME disclosure oracle.** `generate_api_docs_text_h`
built `root / route_path` without checking whether `route_path` was
already absolute — the same `pathlib`-silently-discards-`root`-for-an-
absolute-right-operand class already documented for tools
#99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143
this initiative. Proved live:
`generate_api_docs_text({"route_path": "/tmp/<outside file>"})`
genuinely disclosed a real route decorator's path AND the handler
function's name from a file entirely outside the intended worktree —
a real capability/structure-disclosure primitive, even though it is
not full raw file content.

**Finding #2 — advertised but never dispatched on the interactive chat
agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142.**
`generate_api_docs_text` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch — every real interactive-chat
call fell through to `"[ERROR] Unknown tool: generate_api_docs_text"`.

## Changes made

New shared `generate_api_docs_text_handler()` in
`app/tools/filesystem/generate_api_docs_text.py`: `route_path` is
validated via `check_path_in_worktree()` before any filesystem access,
closing finding #1. A new `chat_agent.py` dispatch branch delegates to
this same shared handler, closing finding #2 —
`generate_api_docs_text` is now genuinely reachable from interactive
chat for the first time.

`app/agents/tools.py`'s `_GENERATE_API_DOCS_TEXT_TOOL` now aliases the
shared `GENERATE_API_DOCS_TEXT_TOOL` constant. No external
direct-importers of the old names were found.

## Tests

New file `tests/test_generate_api_docs_text_hardening.py`, 11 tests:
schema check, duplicate-registration check, worktree-escape-blocked
proof (across `make_chat_handlers`, the new `chat_agent.py` dispatch,
and a direct handler call) with an assertion the outside file's route/
function names never leak into the result, a proof the new dispatch
no longer returns "Unknown tool", and legitimate-usage regression
(single endpoint extraction, multiple endpoints, no-routes-found case,
missing-file error) across both real access paths.

Zero existing tests referenced this tool — confirmed, no sweep needed.

## Regression

This tool is tool 1 of a new #144-#148 batch. Its own new hardening
tests (11/11 pass) are the per-tool verification gate; the full suite
runs once the batch completes, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
generate_api_docs_text.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed; the tool is
now genuinely reachable from interactive chat for the first time — a
strict capability increase, not a narrowing; no functionality lost;
tool-specific regression tests clean.

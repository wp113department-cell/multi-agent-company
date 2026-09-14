# Tool #151 — `git_stash_list` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `git_stash_list_h` inside
`make_chat_handlers()`.

The input schema is empty (no properties at all) — no LLM-controlled
input reaches this tool, so the worktree-boundary-escape and
shell-injection classes established repeatedly this initiative do not
apply, checked directly.

`git_stash_list` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see the finding
below.

Existing tests referencing this tool: `tests/test_new_tools.py`'s
`test_git_stash_list` (1 test) — confirmed via grep and re-run.

## Problems found

One real, empirically-verified finding.

**Advertised but never dispatched on the interactive chat agent, same
class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150.**
`git_stash_list` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
git repo with a real stash on it, called through the real
`chat_agent.py` dispatch, returned `"[ERROR] Unknown tool:
git_stash_list"` instead of listing the stash.

## Changes made

New shared `git_stash_list_handler()` in
`app/tools/git/stash_list.py`, containing the unchanged `git stash
list` logic. A new `chat_agent.py` dispatch branch delegates to this
shared handler, closing the finding — `git_stash_list` is now
genuinely reachable from interactive chat for the first time.
`app/agents/tools.py`'s `_GIT_STASH_LIST_TOOL` now aliases the shared
`GIT_STASH_LIST_TOOL` constant. No external direct-importers of the
old names were found.

## Tests

New file `tests/test_git_stash_list_hardening.py`, 6 tests: schema
check, duplicate-registration check, a proof the new dispatch no
longer returns "Unknown tool", and legitimate-usage regression (real
stash listing on both real access paths, "(no stashes)" for a clean
repo).

Existing test (`tests/test_new_tools.py::test_git_stash_list`, 1 test)
re-run clean.

## Regression

This tool is tool 3 of the #149-#153 batch. Its own new hardening
tests (6/6 pass) plus the 1 pre-existing test (1/1 pass) are the
per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/git/stash_list.py`
sweep (102 files clean), an `importlib.import_module()` sweep over
all `app/agents/` modules (all clean), a `ruff check` on all touched
files (clean), a `python -W error` docstring escape-sequence check on
the new module (clean), and a
`CHAT_TOOLS.count("git_stash_list") == 1` check (clean) — BEFORE
claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding was proved live and closed; the
tool is now genuinely reachable from interactive chat for the first
time — a strict capability increase, not a narrowing; no
functionality lost; tool-specific regression tests clean (7/7 across
new + swept existing tests).

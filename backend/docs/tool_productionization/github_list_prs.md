# Tool #153 — `github_list_prs` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `github_list_prs_h` inside
`make_chat_handlers()`.

`state` reaches `gh pr list --state <state>` via list-args
`subprocess.run()` (no `shell=True`).

`github_list_prs` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see the finding
below.

Zero existing tests referenced this tool — confirmed via grep, no
sweep needed.

## Problems found

Checked and CONFIRMED already safe (no fix needed): the flag-collision
class established repeatedly this initiative for other git/gh tools
(#5, #32, #148, #149) does not apply here. Proved live directly
against the real `gh` binary: `gh pr list --state --json ...` and `gh
pr list --state -x ...` were both rejected with `invalid argument
"..." for "-s, --state" flag: valid values are {open|closed|merged|
all}` — `gh`'s own cobra-based argument parser strictly enforces a
hard enum on `--state` before any network call happens, so a
flag-shaped `state` can never be misinterpreted as a different flag.

One real, empirically-verified finding.

**Advertised but never dispatched on the interactive chat agent, same
class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152.**
`github_list_prs` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: github_list_prs"`.

## Changes made

New shared `github_list_prs_handler()` in
`app/tools/git/github_list_prs.py`, containing the unchanged `gh pr
list` invocation. A new `chat_agent.py` dispatch branch delegates to
this shared handler, closing the finding — `github_list_prs` is now
genuinely reachable from interactive chat for the first time.
`app/agents/tools.py`'s `_GITHUB_LIST_PRS_TOOL` now aliases the shared
`GITHUB_LIST_PRS_TOOL` constant. No external direct-importers of the
old names were found.

## Tests

New file `tests/test_github_list_prs_hardening.py`, 8 tests (skipped
if `gh` is not installed): schema check, duplicate-registration check,
re-confirmation that a flag-shaped `state` is rejected by `gh` itself
(both `--json` and `-x`), a proof the new dispatch no longer returns
"Unknown tool", and legitimate-usage regression (real `gh` invocation
on both real access paths, default state, graceful `gh`-not-found
handling).

Zero existing tests referenced this tool — confirmed, no sweep needed.

## Regression

This tool is tool 5 of the #149-#153 batch — the batch is now
complete. Its own new hardening tests (8/8 pass) are the per-tool
verification gate; the full batch suite runs next, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/git/
github_list_prs.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), a
`python -W error` docstring escape-sequence check on the new module
(clean), and a `CHAT_TOOLS.count("github_list_prs") == 1` check
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding was proved live and closed; the
tool is now genuinely reachable from interactive chat for the first
time — a strict capability increase, not a narrowing; existing `gh`
enum-enforcement confirmed sufficient; no functionality lost;
tool-specific regression tests clean (8/8).

# Tool #150 — `git_log_file` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `git_log_file_h` inside `make_chat_handlers()`.

`git_log_file` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

Zero existing tests referenced this tool — confirmed via grep (one
unrelated substring match on the sibling `git_log` tool's own `file`
parameter test), no sweep needed.

## Problems found

Two real, empirically-verified findings.

**Finding #1 — a worktree-boundary escape that is a genuine
COMMIT-HISTORY DISCLOSURE oracle.** `git_log_file_h` passed `path`
straight to `git log -- <path>` with zero validation that it stayed
inside the intended worktree. This is not the usual `pathlib` `root /
path` pattern — `path` is a plain git pathspec, resolved by git itself
against the repository root, which can differ from the tool's own
intended worktree boundary whenever `repo_path` is a subdirectory of a
larger git repository. Proved live: with the intended worktree set to
a subdirectory of a larger real repo, `git_log_file({"path":
"../secret.txt"})` genuinely disclosed real commit hashes AND commit
messages for a file entirely outside the intended worktree — a real
history/metadata disclosure primitive; commit messages routinely
describe what changed (e.g. "remove leaked API key"), making this a
genuinely sensitive leak class, not just harmless filenames.

**Finding #2 — advertised but never dispatched on the interactive chat
agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146.**
`git_log_file` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all — every real
interactive-chat call fell through to `"[ERROR] Unknown tool:
git_log_file"`.

## Changes made

New shared `git_log_file_handler()` in `app/tools/git/log_file.py`:
`path` is now validated with `check_path_in_worktree()` (checked for
both relative traversal and absolute-path escapes) before the `git
log` subprocess ever runs, closing finding #1. A new `chat_agent.py`
dispatch branch delegates to this same shared handler, closing finding
#2 — `git_log_file` is now genuinely reachable from interactive chat
for the first time.

`app/agents/tools.py`'s `_GIT_LOG_FILE_TOOL` now aliases the shared
`GIT_LOG_FILE_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_git_log_file_hardening.py`, 10 tests: schema
check, duplicate-registration check, worktree-escape-blocked proof
(across the direct handler, `make_chat_handlers`, and the new
`chat_agent.py` dispatch, for both relative-traversal and absolute-path
escapes) with an assertion the outside file's commit messages never
leak into the result, a proof the new dispatch no longer returns
"Unknown tool", and legitimate-usage regression (real commit history,
`limit` respected, "no commits found" for an untracked file).

Zero existing tests referenced this tool — confirmed, no sweep needed.

## Regression

This tool is tool 2 of the #149-#153 batch. Its own new hardening tests
(10/10 pass) are the per-tool verification gate; the full suite runs
once the batch completes, per `feedback_tool_enhance_batch_full_suite`
memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/git/log_file.py` sweep
(102 files clean), an `importlib.import_module()` sweep over all
`app/agents/` modules (all clean), a `ruff check` on all touched files
(clean), a `python -W error` docstring escape-sequence check on the
new module (clean), and a `CHAT_TOOLS.count("git_log_file") == 1`
check (clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed; the tool is
now genuinely reachable from interactive chat for the first time — a
strict capability increase, not a narrowing; no functionality lost;
tool-specific regression tests clean (10/10).

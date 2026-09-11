# Tool #139 — `find_queue` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `find_queue_h` inside `make_chat_handlers()`.

`find_queue` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

1 existing test file references this tool (`test_day2_tools.py`,
`TestFindQueueHandler` + a `CHAT_TOOLS` membership check) — 4 tests,
re-run and confirmed passing unchanged.

## Problems found

Two real, empirically-verified findings.

**Finding #1 (most severe) — a worktree-boundary escape via
`repo_path`, a genuine FULL FILE CONTENT disclosure oracle, worse than
a plain filename leak.** `_rp = str(inp.get("repo_path", repo_path))`
used the LLM-controlled value COMPLETELY UNJOINED to the real worktree
root — unlike the usual `root / field` pattern seen elsewhere in this
initiative (which at least anchors a relative value before an absolute
one can override it), here there was no anchoring at all: any
`repo_path` value, relative or absolute, was handed straight to `grep
-rn ... <repo_path>` as the search root. Proved live:
`find_queue({"repo_path": "/tmp/<outside dir>"})` genuinely returned
real matching CONTENT LINES (not just filenames) from a file entirely
outside the intended worktree.

**Finding #2 — advertised but never dispatched on the interactive chat
agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138.**
`find_queue` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch — every real interactive-chat
call fell through to `"[ERROR] Unknown tool: find_queue"`.

**Note (found, documented, NOT fixed here — out of scope for this
tool's own turn)**: the sibling `find_worker` tool (#142, still
PENDING) has the exact same unanchored `repo_path` pattern in its own,
separate implementation — left alone here for that tool's own turn,
matching this initiative's established "found but explicitly did not
fix a sibling tool's identical bug" precedent (e.g. tool #14).

## Changes made

New shared `find_queue_handler()` in
`app/tools/filesystem/find_queue.py`: `repo_path` is validated via
`check_path_in_worktree()` before being used as the `grep` search
root, closing finding #1. A new `chat_agent.py` dispatch branch
delegates to this same shared handler, closing finding #2. The dead,
never-used `patterns` list (marked `# noqa: F841` in the original)
was dropped — the actually-used `pat` regex is kept unchanged. As a
side effect, a relative `repo_path` override is now correctly anchored
to the real worktree root — the original never joined it to anything
at all, so its behavior depended on the running process's own current
working directory rather than the intended repo, a real (if minor)
correctness gap this fix also closes, proved live.

`app/agents/tools.py`'s `_FIND_QUEUE_TOOL` now aliases the shared
`FIND_QUEUE_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_find_queue_hardening.py`, 11 tests: schema check,
duplicate-registration check, worktree-escape-blocked proof (across
`make_chat_handlers`, the new `chat_agent.py` dispatch, and a direct
handler call) with an assertion the outside file's content never
leaks into the result, a proof the new dispatch no longer returns
"Unknown tool", and legitimate-usage regression (default `repo_path`,
no-matches case, `.venv`/`node_modules` exclusion, and the relative-
`repo_path`-now-correctly-scopes-to-a-subdirectory correctness proof)
across both real access paths.

Existing tests re-run and confirmed passing: `test_day2_tools.py`'s
`TestFindQueueHandler` (3/3) plus its `CHAT_TOOLS` membership check
(1/1) — the full file (88/89, 1 unrelated skip) also re-run clean to
be safe given the identical-path (`repo_path` input matching the
factory's own worktree) usage those tests happen to exercise.

## Regression

This tool is tool 4 of the #136-#140 batch. Its own new hardening
tests (11/11 pass) and the directly-referencing existing test file
(4/4 pass, full file 88/89 with 1 unrelated skip) are the per-tool
verification gate; the full suite runs once the batch completes, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
find_queue.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed; the tool is
now genuinely reachable from interactive chat for the first time, and
a relative `repo_path` now correctly scopes searches instead of
depending on ambient process state — both strict capability increases,
not narrowings; no functionality lost; tool-specific and
directly-referencing regression tests clean.

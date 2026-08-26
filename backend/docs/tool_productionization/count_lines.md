# Tool #129 — `count_lines` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `count_lines_h` inside `make_chat_handlers()`.

`count_lines` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

1 existing test file references this tool (`test_new_tools.py`,
`test_count_lines_file`/`test_count_lines_directory`) — re-run and
confirmed passing unchanged.

## Problems found

Two real, empirically-verified findings.

**Finding #1 — a worktree-boundary escape that is a genuine ARBITRARY
FILE/DIRECTORY READ.** `count_lines_h` built `root / path` without
checking whether `path` was already absolute — the same
`pathlib`-silently-discards-`root`-for-an-absolute-right-operand class
already documented for tools #99/#107/#116/#120/#122/#127 this
initiative. Proved live: `count_lines({"path": "/tmp/<outside
file>"})` genuinely read a file outside the intended worktree and
returned its real line count — a real disclosure oracle. In directory
mode, this is worse: an absolute directory `path` combined with
`pattern` would glob and read line counts for every matching file
under an arbitrary host directory, confirmed live against a real
outside directory too.

**Finding #2 — advertised but never dispatched on the interactive chat
agent, same class as tools #100/#103/#110/#112/#118/#120/#122/#126.**
`count_lines` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch — every real interactive-chat
call fell through to `"[ERROR] Unknown tool: count_lines"`.

## Changes made

New shared `count_lines_handler()` in
`app/tools/filesystem/count_lines.py`:
- `path` is validated via `check_path_in_worktree()` before any
  filesystem access, closing finding #1 for both file and directory
  mode.
- A new `chat_agent.py` dispatch branch delegates to this same shared
  handler, closing finding #2 — `count_lines` is now genuinely
  reachable from interactive chat for the first time.

`app/agents/tools.py`'s `_COUNT_LINES_TOOL` now aliases the shared
`COUNT_LINES_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_count_lines_hardening.py`, 10 tests: schema
check, duplicate-registration check, worktree-escape-blocked proof for
both file mode and directory mode (across `make_chat_handlers`, the
new `chat_agent.py` dispatch, and a direct handler call), a proof the
new dispatch no longer returns "Unknown tool", and legitimate-usage
regression (real file count, real directory count-by-extension) across
both real access paths.

Existing tests re-run and confirmed passing: `test_new_tools.py`'s
`test_count_lines_file`/`test_count_lines_directory` (2/2).

## Regression

This tool is tool 4 of the #126-#130 batch (tools #124-#125, the
remaining `browser_*` tools, were already GREEN_FLAG from an earlier
batch). Its own new hardening tests (10/10 pass) and the
directly-referencing existing test file (2/2 pass) are the per-tool
verification gate; the full suite runs once the batch completes, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
count_lines.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed in both
file and directory mode; the tool is now genuinely reachable from
interactive chat for the first time — a strict capability increase,
not a narrowing; no functionality lost; tool-specific and
directly-referencing regression tests clean.

# Tool #138 — `find_file` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two real, byte-identical implementations:

1. `find_file` inside `make_chat_handlers()`.
2. `chat_agent.py`'s own interactive dispatch — an exact copy of the
   same logic.

Per `tool_inventory.json`, agents declaring `find_file` go through one
of these. `CHAT_TOOLS.count("find_file") == 1` verified. 1 existing
test file references this tool (`test_chat_tools.py::TestFindFile`, 3
tests) — re-run and confirmed passing unchanged.

## Problems found

One real, severe finding — a worktree-boundary escape via `directory`
on both real implementations, a genuine FILENAME/DIRECTORY-STRUCTURE
DISCLOSURE oracle (not file content, but the existence and full paths
of files anywhere on the host the process can read). `ff_root = root /
ff_dir if ff_dir else root` never checked whether `ff_dir` was already
absolute — the same `pathlib`-silently-discards-`root`-for-an-
absolute-right-operand class already documented for tools
#99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137 this initiative.
Proved live: `find_file({"name": "<marker>", "directory": "/tmp/<
outside dir>"})` genuinely returned the real, full absolute path of a
marker file placed entirely outside the intended worktree.

## Changes made

New shared `find_file_handler()` in
`app/tools/filesystem/find_file.py`: `directory` is validated via
`check_path_in_worktree()` before being used to build the `find`
search root, closing the finding. Both real call sites now delegate to
this one handler. `chat_agent.py`'s dispatch previously had a slightly
different (less friendly) timeout error message than
`make_chat_handlers()`'s own implementation — unifying onto the shared
handler also fixes this minor drift as a side effect.

`app/agents/tools.py`'s `_FIND_FILE_TOOL` now aliases the shared
`FIND_FILE_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_find_file_hardening.py`, 9 tests: schema check,
duplicate-registration check, worktree-escape-blocked proof (across
`make_chat_handlers`, the `chat_agent.py` dispatch, and a direct
handler call) with an assertion the outside marker filename never
leaks into the result, and legitimate-usage regression (file found at
repo root, file found in a subdirectory via an explicit `directory`,
no-matches case) across both real access paths.

Existing tests re-run and confirmed passing:
`test_chat_tools.py::TestFindFile` (3/3).

## Regression

This tool is tool 3 of the #136-#140 batch. Its own new hardening
tests (9/9 pass) and the directly-referencing existing test file (3/3
pass) are the per-tool verification gate; the full suite runs once the
batch completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
find_file.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The real finding proved live and closed across both
real implementations; no functionality lost — legitimate file lookups
(at repo root and in subdirectories) are proven to still work;
tool-specific and directly-referencing regression tests clean.

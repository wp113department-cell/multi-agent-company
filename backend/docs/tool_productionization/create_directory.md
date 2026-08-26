# Tool #131 — `create_directory` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `create_directory_h` inside
`make_chat_handlers()`.

`create_directory` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see the finding
below.

1 existing test file references this tool (`test_new_tools.py`,
`test_create_directory`/`test_create_directory_protected`) — re-run
and confirmed passing unchanged.

**Note**: worktree-boundary validation was already correct
(`_is_protected_path(path, repo_path)`, which — given `worktree_path`
— already performs full worktree-containment checking). Confirmed
still correct here by direct inspection and re-verified live, not
assumed.

## Problems found

One real finding — advertised but never dispatched on the interactive
chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130. `create_directory`
is in `CHAT_TOOLS` and registered in `make_chat_handlers()`'s handlers
dict, but `chat_agent.py`'s `_execute_tool()` had no dispatch branch —
every real interactive-chat call fell through to `"[ERROR] Unknown
tool: create_directory"`.

## Changes made

Modularized into `app/tools/filesystem/create_directory.py` —
`CREATE_DIRECTORY_TOOL`, `create_directory_handler` (logic unchanged,
worktree validation reused verbatim from the already-correct
implementation). A new `chat_agent.py` dispatch branch delegates to
this shared handler, closing the finding — `create_directory` is now
genuinely reachable from interactive chat for the first time.

`app/agents/tools.py`'s `_CREATE_DIRECTORY_TOOL` now aliases the
shared `CREATE_DIRECTORY_TOOL` constant. No external direct-importers
of the old names were found.

## Tests

New file `tests/test_create_directory_hardening.py`, 8 tests: schema
check, duplicate-registration check, a proof the new dispatch no
longer returns "Unknown tool", a re-verification that protected-path
rejection still works on both real access paths, and legitimate-usage
regression (nested directory creation, idempotency) across both real
access paths.

Existing tests re-run and confirmed passing: `test_new_tools.py`'s
`test_create_directory`/`test_create_directory_protected` (2/2).

## Regression

This tool is tool 1 of a new #131-#135 batch. Its own new hardening
tests (8/8 pass) and the directly-referencing existing test file (2/2
pass) are the per-tool verification gate; the full suite runs once the
batch completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
create_directory.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The real finding proved live and closed; the tool is
now genuinely reachable from interactive chat for the first time — a
strict capability increase, not a narrowing; no functionality lost;
tool-specific and directly-referencing regression tests clean.

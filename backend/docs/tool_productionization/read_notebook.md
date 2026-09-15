# Tool #175 — `read_notebook` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `read_notebook_h` inside
`make_chat_handlers()`.

`read_notebook` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

Existing tests referencing this tool: `tests/
test_audit_q_batch09_large_project_file_tech.py` (4 tests) —
confirmed via grep and re-run.

## Problems found

Two real, empirically-verified findings, identical class shape to
many prior filesystem-reading tools.

**Finding #1 — a worktree-boundary escape that is a genuine
STRUCTURED FILE CONTENT DISCLOSURE oracle.** `read_notebook_h` built
`root / path` without ever validating it stayed inside the worktree —
the same `pathlib`-silently-discards-`root`-for-an-absolute-right-
operand class already documented for tools
#99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144/#146/#154/#158/#166/#169/#170/#171/#174.
Proved live: `read_notebook({"path": "/tmp/<outside .ipynb>"})`
genuinely disclosed real code-cell source (including a hardcoded
secret-shaped string `sk-supersecretinnotebook...`) and markdown-cell
content (`# Internal admin credentials`) of a notebook entirely
outside the intended worktree.

**Finding #2 — advertised but never dispatched on the interactive
chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168/#169/#170/#171/#172/#173/#174.**
`read_notebook` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: read_notebook"`.

## Changes made

New shared `read_notebook_handler()` in `app/tools/filesystem/
read_notebook.py`: `path` is now validated with
`check_path_in_worktree()` (checked for both relative traversal and
absolute-path escapes) before the file is ever read, closing finding
#1. A new `chat_agent.py` dispatch branch delegates to this same
shared handler, closing finding #2 — `read_notebook` is now genuinely
reachable from interactive chat for the first time.

`app/agents/tools.py`'s `_READ_NOTEBOOK_TOOL` now aliases the shared
`READ_NOTEBOOK_TOOL` constant. No external direct-importers of the
old names were found.

## Tests

New file `tests/test_read_notebook_hardening.py`, 12 tests: schema
check, duplicate-registration check, worktree-escape-blocked proof
(absolute and relative traversal, across all 3 real access paths)
with an assertion the outside notebook's real secret-shaped content
and markdown never leak into the result, a proof the new dispatch no
longer returns "Unknown tool", and legitimate-usage regression (real
notebook parsing including cell output rendering, missing-file error,
invalid-JSON error, and `max_cells` truncation).

Existing tests (`tests/test_audit_q_batch09_large_project_file_tech.py`,
4 tests) re-run clean.

## Regression

This tool is tool 2 of the #174-#178 batch. Its own new hardening
tests (12/12 pass) plus the 4 pre-existing tests (4/4 pass) are the
per-tool verification gate; the full suite runs once the batch
completes.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
read_notebook.py` sweep (102 files clean), an `importlib`-reload
sweep over all `app.agents.*` modules (all clean), a `ruff check` on
all touched files (clean), a compile()-based source escape-sequence
check on the new module (clean), and a
`CHAT_TOOLS.count("read_notebook") == 1` check (clean) — BEFORE
claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed; the tool
is now genuinely reachable from interactive chat for the first time —
a strict capability increase, not a narrowing; no functionality lost;
tool-specific regression tests clean (16/16 across new + swept
existing tests).

# Tool #132 — `csv_preview` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `csv_preview_h` inside `make_chat_handlers()`.

`csv_preview` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #3.

1 existing test file references this tool (`test_new_tools.py`,
`test_csv_preview`) — re-run and confirmed passing unchanged.

## Problems found

Three real, empirically-verified findings.

**Finding #1 — a worktree-boundary escape that is a genuine ARBITRARY
FILE READ.** `csv_preview_h` built `root / str(inp["path"])` without
checking whether `path` was already absolute — the same
`pathlib`-silently-discards-`root`-for-an-absolute-right-operand class
already documented for tools #99/#107/#116/#120/#122/#127/#129 this
initiative. Proved live: a `path` value outside the intended worktree
was genuinely read, its header and row content returned verbatim.

**Finding #2 — a real robustness gap: an uncaught crash on a
non-numeric `rows`.** `int(inp.get("rows", 5))` was never wrapped in a
`try/except`, matching the class already fixed for tools
#78/#127/#130. Proved live: `rows="not_a_number"` raised an unhandled
`ValueError`.

**Finding #3 — advertised but never dispatched on the interactive chat
agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131.** `csv_preview`
is in `CHAT_TOOLS` and registered in `make_chat_handlers()`'s handlers
dict, but `chat_agent.py`'s `_execute_tool()` had no dispatch branch —
every real interactive-chat call fell through to `"[ERROR] Unknown
tool: csv_preview"`.

## Changes made

New shared `csv_preview_handler()` in
`app/tools/filesystem/csv_preview.py`:
- `path` is validated via `check_path_in_worktree()` before any
  filesystem access, closing finding #1.
- `rows` conversion is now wrapped in `try/except` and clamped to
  `[1, 200]`, closing finding #2.
- A new `chat_agent.py` dispatch branch delegates to this same shared
  handler, closing finding #3 — `csv_preview` is now genuinely
  reachable from interactive chat for the first time.

`app/agents/tools.py`'s `_CSV_PREVIEW_TOOL` now aliases the shared
`CSV_PREVIEW_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_csv_preview_hardening.py`, 12 tests: schema
check, duplicate-registration check, worktree-escape-blocked proof
(across `make_chat_handlers`, the new `chat_agent.py` dispatch, and a
direct handler call), non-numeric-`rows` crash-fix proof,
out-of-range-`rows` clamp proof, a proof the new dispatch no longer
returns "Unknown tool", and legitimate-usage regression (real preview,
empty CSV, missing file) across both real access paths.

Existing tests re-run and confirmed passing: `test_new_tools.py`'s
`test_csv_preview` (1/1).

## Regression

This tool is tool 2 of the #131-#135 batch. Its own new hardening
tests (12/12 pass) and the directly-referencing existing test file
(1/1 pass) are the per-tool verification gate; the full suite runs
once the batch completes, per `feedback_tool_enhance_batch_full_suite`
memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
csv_preview.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** All three real findings proved live and closed; the
tool is now genuinely reachable from interactive chat for the first
time — a strict capability increase, not a narrowing; no functionality
lost; tool-specific and directly-referencing regression tests clean.

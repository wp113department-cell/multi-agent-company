# Tool #122 — `base64_encode` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `base64_encode_h` inside `make_chat_handlers()`.

`base64_encode` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

1 existing test file references this tool (`test_new_tools.py`,
`test_base64_encode_text`/`test_base64_encode_file`) — re-run and
confirmed passing unchanged.

## Problems found

Two real, empirically-verified findings.

**Finding #1 — a worktree-boundary escape that is a genuine ARBITRARY
FILE READ.** `base64_encode_h` built `root / str(path)` without
checking whether `path` was already absolute — the same
`pathlib`-silently-discards-`root`-for-an-absolute-right-operand class
already documented for tools #99/#107/#116/#120 this initiative.
Proved live: `base64_encode({"path": "/tmp/<outside file>"})` genuinely
read a file outside the intended worktree and returned it as valid
base64 — decoding the result recovered the real file content
verbatim, confirming a real disclosure primitive (arguably more
dangerous than a plain-text leak since it can smuggle binary content
too).

**Finding #2 — advertised but never dispatched on the interactive chat
agent, same class as tools #100/#103/#110/#112/#118/#120.**
`base64_encode` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch — every real interactive-chat
call fell through to `"[ERROR] Unknown tool: base64_encode"`.

## Changes made

New shared `base64_encode_handler()` in
`app/tools/filesystem/base64_encode.py`:
- `path` is validated via `check_path_in_worktree()` before any
  filesystem access, closing finding #1.
- A new `chat_agent.py` dispatch branch delegates to this same shared
  handler, closing finding #2 — `base64_encode` is now genuinely
  reachable from interactive chat for the first time.

`app/agents/tools.py`'s `_BASE64_ENCODE_TOOL` now aliases the shared
`BASE64_ENCODE_TOOL` constant; `base64_encode_h` delegates to the
shared handler. No external direct-importers of the old names were
found.

## Tests

New file `tests/test_base64_encode_hardening.py`, 11 tests: schema
check, duplicate-registration check, worktree-escape-blocked proof
(across `make_chat_handlers`, the new `chat_agent.py` dispatch, and a
direct handler call), a proof the new dispatch no longer returns
"Unknown tool", and legitimate-usage regression (text encode/decode
round-trip, real file encode, missing-input error) across both real
access paths.

Existing tests re-run and confirmed passing: `test_new_tools.py`'s
`test_base64_encode_text`/`test_base64_encode_file` (2/2).

## Regression

This tool is tool 4 of the #119-#123 batch (tool #123, one of the
`browser_*` tools, was already GREEN_FLAG from an earlier batch). Its
own new hardening tests (11/11 pass) and the directly-referencing
existing test file (2/2 pass) are the per-tool verification gate; the
full suite runs once the batch completes, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
base64_encode.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed; the tool is
now genuinely reachable from interactive chat for the first time — a
strict capability increase, not a narrowing; no functionality lost;
tool-specific and directly-referencing regression tests clean.

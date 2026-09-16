# Tool #202 — `summarize_folder` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `summarize_folder_h` inside
`make_chat_handlers()`. Exclusively a `CHAT_TOOLS` entry (membership
count confirmed = 1); grepped all other agent files — none reference
`"summarize_folder"` in their own `allowed_tools`, so interactive chat
is the only intended real consumer.

A pre-existing code comment sitting immediately above this tool's old
schema location in `tools.py` claimed "No LLM-controlled input reaches
disk or a subprocess... so no injection/worktree surface exists." That
comment actually belongs to the unrelated neighboring
`_ESTIMATE_COMPLEXITY_TOOL` (tool #110) directly above it in the file
— not to `summarize_folder` — and its claim does not hold for this
tool, as this turn's own direct, ZERO-HALLUCINATION investigation
found and proved (see Problems found).

## Audit of injection surface (checked — found a real gap, see below)

`path`/`extensions` are the only inputs. `extensions` is a plain
string-set filter with no filesystem effect of its own. `path` reaches
`root / sf_path` directly with **no worktree-boundary validation** —
a real gap (finding #1).

## Problems found

Two real, empirically-verified findings.

1. **Worktree-boundary escape — a real file-existence/absolute-path
   disclosure oracle.** `summarize_folder_h` built `folder = root /
   sf_path` without checking whether `sf_path` was already absolute —
   the same `pathlib`-silently-discards-`root`-for-an-absolute-right-
   operand class already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144
   this initiative. Proved live: `summarize_folder({"path":
   "/tmp/<outside dir>"})` genuinely walked and read the real content
   of a `.py` file entirely outside the intended worktree; the
   `fp.relative_to(root)` call immediately after the read raises
   `ValueError` for an out-of-root file, caught by the tool's own
   broad `except Exception` and surfaced as `f"[ERROR reading
   {fp.name}] {e}"` — and Python's own `ValueError` message for a
   failed `relative_to()` embeds the FULL real absolute path of the
   out-of-worktree file (confirmed live in a real repro: the error
   text contained the file's true `/tmp/...` path). Narrower than
   siblings' full structured-content leaks (line/function/class counts
   are silently discarded on this path, not disclosed), but a real,
   exploitable file-existence-and-absolute-path oracle outside the
   worktree.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144.**
   `summarize_folder` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` had NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: summarize_folder"`. This finding was
   correctly identified in the old location's neighboring comment
   block (which, despite belonging to a different tool, happened to
   still describe an accurate general pattern for this class of gap).

## Changes made

Extracted into `app/tools/filesystem/summarize_folder.py`
(`SUMMARIZE_FOLDER_TOOL`, `summarize_folder_handler`). `path` is now
validated with `check_path_in_worktree()` before any filesystem
access, closing finding #1. A new `chat_agent.py` `_execute_tool()`
dispatch branch delegates to this same shared handler, closing
finding #2. `make_chat_handlers()`'s own `summarize_folder_h` closure
now delegates to the same shared handler. All other behavior (up to
20 files, `extensions` filtering, per-file line/function/class counts,
`(truncated — 20 file limit)` marker, `(no matching files)` fallback)
preserved verbatim.

## Tests

No existing test required a fix — `tool_inventory.json` correctly
lists 0 pre-existing test files for this tool, confirmed by grep.

New file `tests/test_summarize_folder_hardening.py`, 12 tests: schema
check, `CHAT_TOOLS` single-registration check, escape-blocked proof on
all 3 real access paths (`make_chat_handlers()`'s handler,
`chat_agent.py`'s real dispatch via `_execute_tool()`, and the shared
handler called directly), proof the dispatch no longer returns
"Unknown tool", and legitimate-usage regression (real file
summarization with correct line/function/class counts, `extensions`
filtering, no-match fallback, missing-path error, and the 20-file
truncation limit) — verified through both real access paths.

## Regression

This tool's own new hardening tests (12/12 pass). Also ran a broader
chat_agent regression sweep (`test_audit_q_batch10_chat_agent_dispatch.py`,
`test_batch11_chat_agent_bash_sandbox.py`,
`test_batch11_chat_agent_policy_chokepoint.py`,
`test_chat_agent_memory_wiring.py`, `test_chat_tools.py`,
`test_gap16_chat_agent_verification_gate.py`, `test_day2_tools.py`) —
**246 passed, 1 skipped**, 0 failed.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.chat_agent` and `app.agents.tools` (both clean), a `ruff
check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_new_tools.py` + `tests/test_final_session.py` tool-count
regression tests (61/61 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Two real findings (a worktree-escape disclosure oracle
and a completely non-functional interactive-chat dispatch) identified
and fixed; no functionality lost, legitimate usage verified end-to-end
on both real access paths. Tool-specific and broader chat_agent
regression tests clean. Agent alignment verified: PASS
(`chat_agent.py`'s dispatch and `make_chat_handlers()`'s handler both
now route through the one shared, worktree-validated implementation).

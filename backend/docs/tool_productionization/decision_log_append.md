# Tool #133 — `decision_log_append` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `decision_log_append_h` inside
`make_chat_handlers()`.

`decision_log_append` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see the finding
below.

1 existing test file mentions this tool
(`test_batch11_policy_check_structural_chokepoint.py`, a comment noting
it has "no path-shaped field at all") — not a real dependency; re-run
and confirmed passing unchanged (11/11).

## Problems found

Audited for every finding class established so far in this initiative
(shell injection, flag/program injection, worktree-boundary escape,
unbounded timeout) — **none apply**. There is no LLM-controlled
filesystem path or network destination anywhere in this tool's input
schema at all — the target file is a fixed, deterministic path
derived from an MD5 hash of `repo_path`
(`<memory_dir>/<hash>_decisions.jsonl`), never influenced by
`decision`/`reason`/`alternatives`. Those three fields reach the file
only as plain JSON-serialized string values, never as raw text
concatenated into anything executable or interpreted. File writes use
real OS-level locking (`fcntl.flock` / `msvcrt.locking`, matching the
same pattern this tool's sibling `memory_read`/`known_issues_write`
tools already use), so no lost-update race is possible.

One real finding — advertised but never dispatched on the interactive
chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132.
`decision_log_append` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch — every real interactive-chat
call fell through to `"[ERROR] Unknown tool: decision_log_append"`.

## Changes made

Modularized into `app/tools/agents/decision_log_append.py` —
`DECISION_LOG_APPEND_TOOL`, `decision_log_append_handler` (logic
unchanged, including its `datetime.utcnow()` timestamp — a real
`DeprecationWarning` in this environment but not a functional bug and
not unique to this tool, so left as verbatim-preserved behavior
rather than an opportunistic, out-of-scope rewrite). The target
`app/memory/` directory path computation was independently re-derived
for the new file's different location (`app/tools/agents/` vs.
`app/agents/`) and verified live to resolve to the byte-identical
directory as the original before this fix was considered complete — a
one-`.parent`-too-many mistake was caught and corrected during this
same turn via that live check, not shipped.

A new `chat_agent.py` dispatch branch delegates to the shared handler,
closing the finding — `decision_log_append` is now genuinely reachable
from interactive chat for the first time.

`app/agents/tools.py`'s `_DECISION_LOG_APPEND_TOOL` now aliases the
shared `DECISION_LOG_APPEND_TOOL` constant. No external
direct-importers of the old names were found.

## Tests

New file `tests/test_decision_log_append_hardening.py`, 7 tests:
schema check, duplicate-registration check, a real proof the new
dispatch no longer returns "Unknown tool" (verified via a direct read
of the real written file, not just the returned string), and
legitimate-usage regression (a full entry with `alternatives`, a
default empty `alternatives`, the `make_chat_handlers` factory path,
and a proof different `repo_path` values write to genuinely different
files) — all verified via direct file reads against the real target
path.

Existing test re-run and confirmed passing:
`test_batch11_policy_check_structural_chokepoint.py` (11/11, comment
mention only).

## Regression

This tool is tool 3 of the #131-#135 batch. Its own new hardening
tests (7/7 pass) and the mentioning existing test file (11/11 pass)
are the per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/agents/
decision_log_append.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** No vulnerability found after a full audit against
every finding class this initiative has established — the handler's
own logic was already correct by construction. The one real finding
(missing chat dispatch) proved live and closed — the tool is now
genuinely reachable from interactive chat for the first time, a
strict capability increase; no functionality lost; the target file
path was independently re-verified to match exactly, not assumed;
tool-specific and mentioning regression tests clean.

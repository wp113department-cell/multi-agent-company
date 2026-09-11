# Tool #137 — `export_markdown` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `export_markdown_h` inside
`make_chat_handlers()`.

`export_markdown` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

1 existing test file references this tool
(`test_audit_q_batch09_large_project_file_tech.py`,
`test_export_markdown_uses_real_renderer_not_pre_fallback`) — re-run
and confirmed passing unchanged.

## Problems found

Two real, empirically-verified findings.

**Finding #1 (most severe) — a worktree-boundary escape on BOTH
`path` and `output`, a genuine ARBITRARY FILE WRITE.**
`export_markdown_h` built `root / str(inp["path"])` for the read AND
`root / output_name` for the write without checking whether either was
already absolute — the same `pathlib`-silently-discards-`root`-for-an-
absolute-right-operand class already documented for tools
#99/#107/#116/#120/#122/#127/#129/#132/#134/#135 this initiative, but
here it produces a real disk write, the same severity class as tools
#80/#100/#112's silent arbitrary-file-write findings. Worse still: when
`output` is omitted, the default is DERIVED from `path`
(`str(inp["path"]).replace(".md", ".html")`) — so an absolute `path`
alone, with no `output` given at all, also produces a write outside
the worktree by default. Proved live, in isolated `/tmp` directories
(never the real project, per the established safe-mutation-testing
rule): (a) an explicit absolute `output` genuinely wrote a real HTML
file outside the intended worktree; (b) an absolute `path` with no
`output` at all also wrote outside the worktree, via the
derived-default path.

**Finding #2 — advertised but never dispatched on the interactive chat
agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136.**
`export_markdown` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch — every real interactive-chat
call fell through to `"[ERROR] Unknown tool: export_markdown"`.

## Changes made

New shared `export_markdown_handler()` in
`app/tools/filesystem/export_markdown.py`:
- Both `path` and the resolved `output` (the caller-supplied value, or
  the same `path`-derived default the original computed) are validated
  via `check_path_in_worktree()` before any filesystem access, closing
  finding #1 for both the read and the write, and for both the
  explicit-`output` and default-`output` cases.
- A new `chat_agent.py` dispatch branch delegates to this same shared
  handler, closing finding #2 — `export_markdown` is now genuinely
  reachable from interactive chat for the first time.

`app/agents/tools.py`'s `_EXPORT_MARKDOWN_TOOL` now aliases the shared
`EXPORT_MARKDOWN_TOOL` constant. No external direct-importers of the
old names were found.

## Tests

New file `tests/test_export_markdown_hardening.py`, 11 tests: schema
check, duplicate-registration check, worktree-escape-blocked proof for
both the explicit-`output` case and the more severe default-derived-
`output` case (across `make_chat_handlers`, the new `chat_agent.py`
dispatch, and a direct handler call) with assertions that no file is
ever created outside the worktree, a proof the new dispatch no longer
returns "Unknown tool", and legitimate-usage regression (default
output name, explicit output name, missing-source error) across both
real access paths. All escape-proof tests use `tmp_path` fixtures
exclusively — no real-project-directory exposure, per the safe-
mutation-testing rule established after tool #115's incident.

Existing test re-run and confirmed passing:
`test_audit_q_batch09_large_project_file_tech.py`'s
`test_export_markdown_uses_real_renderer_not_pre_fallback` (1/1).

## Regression

This tool is tool 2 of the #136-#140 batch. Its own new hardening
tests (11/11 pass) and the directly-referencing existing test file
(1/1 pass) are the per-tool verification gate; the full suite runs
once the batch completes, per `feedback_tool_enhance_batch_full_suite`
memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
export_markdown.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live (safely, in isolated
`/tmp` directories) and closed; the tool is now genuinely reachable
from interactive chat for the first time — a strict capability
increase, not a narrowing; no functionality lost — legitimate exports
(both default and explicit output names) are proven to still work;
tool-specific and directly-referencing regression tests clean.

# Tool #119 — `task_progress` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three real implementations:

1. `chat_agent.py`'s own interactive dispatch.
2. `task_progress_h` inside `make_chat_handlers()`.
3. `mon_task_progress` (`make_monitoring_agent_handlers`).

Per `tool_inventory.json`, agents declaring `task_progress` go through
one of these. `CHAT_TOOLS.count("task_progress") == 1` verified. 2
existing test files reference this tool
(`test_day1_tools.py::TestTaskProgress`,
`test_day2_agents.py::test_includes_monitoring_tools`) — re-run and
confirmed passing unchanged.

`task_id`/`limit` were already `int()`-coerced by every implementation
before reaching the SQL text, so there was no live-provable SQL
injection on this specific tool (unlike tool #118's `task_history_query`,
whose `status` field was a raw, unvalidated string) — but the design
was fragile (one accidental removal of an `int()` cast away from the
exact same injection class as tools #15/#96/#118).

## Problems found

Two real, empirically-verified findings.

**Finding #1 (most severe) — the tool was completely non-functional on
this host; every real call failed.** All three implementations shell
out to the `psql` CLI, which is not installed on this host at all.
Proved live: all three real call sites returned an error —
`mon_task_progress` returned `[ERROR] psql not found`,
`task_progress_h` returned `[ERROR] [Errno 2] No such file or
directory: 'psql'`, and `chat_agent.py`'s `shell=True` dispatch
surfaced `/bin/sh: 1: psql: not found`. Same "missing dependency"
class as tool #104's `coverage_report`.

**Finding #2 — a real functionality-divergence bug: `mon_task_progress`
silently ignores the schema's own documented `limit` field**,
hardcoding `LIMIT 10` regardless of what the caller passes, while its
two siblings (`task_progress_h`, `chat_agent.py`'s dispatch) already
honor it correctly. `mon_task_progress` also selected a different
column set (`title` instead of `created_at`) than its two siblings.

## Changes made

New shared `task_progress_handler()` in
`app/tools/database/task_progress.py`:
- Real `psycopg2` parameter binding for `task_id`/`limit` — neither is
  ever string-interpolated into SQL text, structurally closing the
  injection risk for good (not relying on every future edit
  remembering the `int()` cast) and dropping the `psql` subprocess
  call entirely, closing finding #1 for any host with or without
  `psql` installed.
- Selects the union of both prior column sets (`id`, `title`,
  `status`, `created_at`, `updated_at`) so no caller loses a column it
  previously had.
- `limit` is honored and clamped to `[1, 200]` on all three call
  sites, closing finding #2.
- `task_id` is validated with a clean `[ERROR] Invalid task_id: ...`
  message instead of letting a non-numeric value raise.

All three real call sites (`chat_agent.py`'s dispatch,
`task_progress_h` in `make_chat_handlers`, `mon_task_progress`) now
delegate to this one handler. `app/agents/tools.py`'s
`_TASK_PROGRESS_TOOL` now aliases the shared `TASK_PROGRESS_TOOL`
constant. No external direct-importers of the old names were found.

## Tests

New file `tests/test_task_progress_hardening.py`, 11 tests: schema
check, duplicate-registration check, a real proof all three
implementations now genuinely work without `psql` (finding #1),
a real proof `mon_task_progress` now honors `limit` (finding #2),
invalid-`task_id` handling, a specific-task_id lookup, and
legitimate-usage regression across all three real access paths.

Existing tests re-run and confirmed passing:
`test_day1_tools.py::TestTaskProgress` (1/1),
`test_day2_agents.py::test_includes_monitoring_tools` (1/1).

## Regression

This tool is tool 1 of a new #119-#123 batch (tool #123, one of the 7
`browser_*` tools, was already completed earlier alongside its
siblings). Its own new hardening tests (11/11 pass) and
directly-referencing existing tests (2/2 pass) are the per-tool
verification gate; the full suite runs once the batch completes, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/database/
task_progress.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed across all
three real implementations; the tool went from completely
non-functional on this host to genuinely working; no functionality
lost — `mon_task_progress` now honors `limit` where it previously
silently ignored it, a strict capability increase; tool-specific and
directly-referencing regression tests clean.

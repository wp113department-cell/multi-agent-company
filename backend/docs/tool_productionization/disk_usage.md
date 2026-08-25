# Tool #107 — `disk_usage` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three real implementations:

1. `chat_agent.py`'s own interactive dispatch (pure `shutil.disk_usage`,
   no subprocess).
2. `disk_usage_h` inside `make_chat_handlers()` (same, `shutil`-based).
3. `mon_disk_usage` (`make_monitoring_agent_handlers`) — see finding
   #1, a genuinely different implementation.

Per `tool_inventory.json`, agents declaring `disk_usage` go through
one of the factories above. `CHAT_TOOLS.count("disk_usage") == 1`
verified. 4 existing test files reference this tool — 3 genuinely
exercise the real handler (loose assertions), re-run and confirmed
passing unchanged; 1 (`test_gap35_resource_check.py`) monkeypatches
an unrelated `psutil.disk_usage` call in a different tool, not a real
match.

## Problems found

**Finding #1 — `mon_disk_usage` genuinely diverges from the tool's own
documented contract, in two separate ways.** The schema explicitly
promises "Get disk usage (total, used, free) for a path using
shutil.disk_usage (stdlib)... default: repo root" — but
`mon_disk_usage` (a) used `subprocess.run(["df", "-h", path])`
instead, a completely different mechanism producing a differently
FORMATTED result (a raw `df` table) than every other real call site;
and (b) defaulted `path` to `"/"` (the whole HOST root filesystem)
rather than the repo root the schema documents. Proved live: with no
`path` given, this implementation reported the ENTIRE HOST's disk
usage by default — a real information-disclosure-by-default bug, not
just a documentation mismatch.

**Finding #2 — worktree-boundary escape, on all three
implementations.** None validated `path` before handing it to
`shutil.disk_usage()` (or, for `mon_disk_usage`, `df`). Proved live:
`shutil.disk_usage("/etc")` genuinely returned real host filesystem
statistics for a directory completely outside any repo.

## Changes made

New shared `disk_usage_handler()` in
`app/tools/execution/disk_usage.py`: uses `shutil.disk_usage()`
consistently (matching the tool's own documented mechanism, and
removing `mon_disk_usage`'s external `df` binary dependency entirely)
— closes finding #1a; defaults to the handler's own configured
worktree root when `path` is empty, matching the documented "default:
repo root" contract — closes finding #1b; `check_path_in_worktree()`
rejects any `path` value that resolves outside the worktree — closes
finding #2.

`app/agents/tools.py`'s `_DISK_USAGE_TOOL` now aliases the shared
`DISK_USAGE_TOOL` constant. No external direct-importers found.

## Tests

New file `tests/test_disk_usage_hardening.py`, 12 tests, all real (no
mocking) — schema check, duplicate-registration check, a real proof
`mon_disk_usage` now defaults to the repo root (not the host root) and
uses the documented `shutil`-based output format (not a `df` table),
worktree-escape rejection on the interactive dispatch AND both handler
factories (parametrized), dotdot-traversal rejection, and
legitimate-usage regression (real disk usage for the repo root and a
real subdirectory) across all three real access paths. Existing tests
(`test_day1_tools.py::TestDiskUsage`, `test_day2_agents.py::
TestMonitoringHandlers::test_disk_usage_returns_string`) re-run and
confirmed passing unchanged (3 tests) — including the existing test
that explicitly called `{"path": "/"}`, whose loose
`isinstance(result, str)` assertion is satisfied by the new
`[POLICY DENIED]` rejection just as it was by the old (wrong) host-wide
disclosure, confirmed by re-running rather than assumed.

## Regression

This tool is 4 of the current #104-#108 batch. Its own new hardening
tests (12/12 pass) and directly-referencing existing tests (3/3 pass)
are the per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
disk_usage.py` sweep (98 files clean), an `importlib.import_module()`
sweep over all 97 `app/agents/` modules (all clean), a `ruff check` on
all 3 touched files (clean), and a `python -W error` docstring
escape-sequence check on the new module (clean) — BEFORE claiming
GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings — an implementation that silently
diverged from its own documented contract (leaking host-wide disk info
by default) and a worktree-escape across all three implementations —
proved live and closed; the tool now behaves consistently regardless
of which agent calls it, matching what its schema has always promised;
no functionality lost; tool-specific and directly-referencing
regression tests clean.

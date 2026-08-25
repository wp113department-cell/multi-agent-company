# Tool #105 — `cpu_usage` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three real implementations:

1. `chat_agent.py`'s own interactive dispatch.
2. `cpu_usage_h` inside `make_chat_handlers()`.
3. `mon_cpu_usage` (`make_monitoring_agent_handlers`).

Per `tool_inventory.json`, agents declaring `cpu_usage` go through one
of the factories above. `CHAT_TOOLS.count("cpu_usage") == 1` verified.
3 existing test files reference this tool — 2 are membership checks,
1 (`test_day1_tools.py::TestCpuUsage`) genuinely exercises the
handler with a loose assertion — re-run and confirmed passing
unchanged.

The schema's own `input_schema.properties` is empty (`{}`) — no
LLM-controlled input reaches this tool at all, so the usual
worktree-escape/flag-collision/shell-injection classes established
throughout this initiative are structurally impossible here. Both
findings below are accuracy/robustness bugs, not security.

## Problems found

**Finding #1 — a real accuracy bug on 2 of the 3 implementations: a
SINGLE read of `/proc/stat` was mislabeled as "current" CPU usage.**
`/proc/stat`'s `cpu` line holds CUMULATIVE jiffie counters since boot
— a single read can only ever compute the AVERAGE utilization since
the machine booted, not the current, instantaneous load the tool's own
description promises. Proved live on the real host: a proper
two-sample delta read (0.3s apart) reported **9.6%** real current
usage, while the single-read formula these two implementations use
reported **22.4%** for the exact same moment — a genuinely different,
wrong number, not a rounding difference, and the gap only grows the
longer the host has been up. `mon_cpu_usage` didn't have this specific
bug (it shells to `top -bn1`, which samples over a short internal
window) but was inconsistent with the other two and had no
`/proc/stat` fast path at all.

**Finding #2 — a real robustness gap on `mon_cpu_usage`: no
`try/except` at all around the `top` subprocess call.** Unlike its two
siblings (both already wrapped in `try/except Exception`), a missing
`top` binary (a real, plausible case in a minimal container image)
would raise an uncaught `FileNotFoundError` straight out of the
handler instead of a clean `[ERROR]` string. Proved with a synthetic
test simulating both fallback paths unavailable.

## Changes made

New shared `cpu_usage_handler()` in `app/tools/execution/cpu_usage.py`:
reads `/proc/stat` TWICE, 0.3s apart, and computes the delta-based
percentage — closes finding #1 with a real, correct measurement
instead of a mislabeled average. Falls back to parsing `top -bn1`
output (matching the pre-existing sibling behavior, unchanged) only
when `/proc/stat` isn't available (non-Linux hosts) — the whole
function is wrapped in `try/except` — closes finding #2.

`app/agents/tools.py`'s `_CPU_USAGE_TOOL` now aliases the shared
`CPU_USAGE_TOOL` constant. No external direct-importers found.

## Tests

New file `tests/test_cpu_usage_hardening.py`, 9 tests, all real (no
mocking except where explicitly documented — the delta-vs-single-read
proof and the `FileNotFoundError` robustness test both patch the
sampling function/subprocess deliberately, to make the DIFFERENCE
between the old and new behavior directly assertable) — schema check,
duplicate-registration check, a real proof the fix uses two distinct
samples and computes a genuine delta (not just the raw second
reading), a real plausible-range check against the actual host, real
proof no uncaught exception occurs when both `/proc/stat` and `top`
are unavailable, real proof the `top` fallback still works, and
legitimate-usage regression across all three real access paths.
Existing tests (`test_day1_tools.py::TestCpuUsage`) re-run and
confirmed passing unchanged.

## Regression

This tool is 2 of the current #104-#108 batch. Its own new hardening
tests (9/9 pass) and directly-referencing existing tests (1/1 pass)
are the per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
cpu_usage.py` sweep (98 files clean), an `importlib.import_module()`
sweep over all 97 `app/agents/` modules (all clean), a `ruff check` on
all 4 touched files (clean), and a `python -W error` docstring
escape-sequence check on the new module (clean) — BEFORE claiming
GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings — a genuinely wrong CPU-usage
number (proved with a live side-by-side comparison against the same
real moment) and a real robustness gap — proved and closed across all
three real implementations; the tool now measures what it has always
claimed to measure; no functionality lost; tool-specific and
directly-referencing regression tests clean.

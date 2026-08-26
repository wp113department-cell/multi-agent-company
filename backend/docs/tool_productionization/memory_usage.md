# Tool #114 — `memory_usage` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three real implementations:

1. `chat_agent.py`'s own interactive dispatch.
2. `memory_usage_h` inside `make_chat_handlers()`.
3. `mon_memory_usage` (`make_monitoring_agent_handlers`) — see finding
   below.

Per `tool_inventory.json`, agents declaring `memory_usage` go through
one of the factories above. `CHAT_TOOLS.count("memory_usage") == 1`
verified. 3 existing test files reference this tool — 2 genuinely
exercise the real handler (loose assertions), re-run and confirmed
passing unchanged.

The schema's own `input_schema.properties` is empty (`{}`) — no
LLM-controlled input reaches this tool at all, so the usual
worktree-escape/flag-collision/shell-injection classes established
throughout this initiative are structurally impossible here. Unlike
tool #105's `cpu_usage`, memory usage is a point-in-time quantity, not
a cumulative counter — a single `/proc/meminfo` read is not subject to
the "single-read gives the wrong answer" class that affected
`/proc/stat`, so no accuracy bug exists here.

## Problems found

**Finding — `mon_memory_usage` has no `try/except` around its `free`
subprocess call, and always shells out to `free` instead of preferring
`/proc/meminfo` like its two siblings.** Unlike `memory_usage_h`/
`chat_agent.py`'s dispatch (both already correctly try `/proc/meminfo`
first, falling back to `free -h`, all wrapped in error handling), a
missing `free` binary — a real, plausible case in a minimal container
image — would raise an uncaught `FileNotFoundError` straight out of
the handler instead of a clean `[ERROR]` string. Same robustness class
already established for tools #105 (`mon_cpu_usage`) and #109
(`dk_docker_ps`). Proved live with a simulated missing binary.

## Changes made

New shared `memory_usage_handler()` in
`app/tools/execution/memory_usage.py`: prefers `/proc/meminfo` (fast,
no subprocess dependency) and falls back to `free -h` only when
unavailable, matching the already-correct design — the whole function
is wrapped in `try/except`, closing the finding.

`app/agents/tools.py`'s `_MEMORY_USAGE_TOOL` now aliases the shared
`MEMORY_USAGE_TOOL` constant. No external direct-importers found.

## Tests

New file `tests/test_memory_usage_hardening.py`, 9 tests — real reads
against this host for the legitimate-usage proofs, mocked
`Path.exists`/`subprocess.run` only for the two robustness cases where
isolating "both sources unavailable" or "only `/proc/meminfo`
unavailable" matters — schema check, duplicate-registration check,
real proof no exception occurs when both sources are unavailable, real
proof the `free` fallback path still works, and legitimate-usage
regression (real memory data) across all three real access paths.
Existing tests (`test_day2_agents.py::TestMonitoringHandlers::
test_memory_usage_returns_string`, `test_day1_tools.py`) re-run and
confirmed passing unchanged.

## Regression

This tool is tool 1 of the new #114-#118 batch. Its own new hardening
tests (9/9 pass) and directly-referencing existing tests (3/3 pass)
are the per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
memory_usage.py` sweep (98 files clean), an `importlib.import_module()`
sweep over all 97 `app/agents/` modules (all clean), a `ruff check` on
all 3 touched files (clean), and a `python -W error` docstring
escape-sequence check on the new module (clean) — BEFORE claiming
GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The real robustness finding proved live and closed
across all three real implementations; the tool now behaves
consistently regardless of which agent calls it; no functionality
lost; tool-specific and directly-referencing regression tests clean.

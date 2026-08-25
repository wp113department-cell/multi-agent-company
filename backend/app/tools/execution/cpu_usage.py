"""cpu_usage tool — tool_enhance.md productionization pass, tool #105
(2026-08-25).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: cpu_usage
Old path: app/agents/tools.py (`_CPU_USAGE_TOOL` schema dict) with
    THREE real implementations: `mon_cpu_usage`
    (`make_monitoring_agent_handlers`), `cpu_usage_h` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch.
New path: app/tools/execution/cpu_usage.py (this file) —
    `CPU_USAGE_TOOL`, `cpu_usage_handler`. ALL THREE real call sites
    now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring `cpu_usage`
    in `allowed_tools`.
Affected modules: app/agents/tools.py (both of its own closures
    delegate to the shared handler), app/agents/chat_agent.py (its
    dispatch now calls the same shared handler, dropping its
    `_run_subprocess`/`shell=True` invocation entirely).
Affected registries: none — app/fleet/tool_manifest.py's "cpu_usage"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the two handler factories or
    `ChatAgent._execute_tool`, and none locked in the exact old
    (wrong) percentage value. New tests added: see
    tests/test_cpu_usage_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/cpu_usage.md.
---------------------------------------------------------------------------

No LLM-controlled input reaches this tool at all — the schema's own
`input_schema.properties` is empty (`{}`), so the usual worktree-
escape/flag-collision/shell-injection classes established throughout
this initiative are structurally impossible here.

Two real, empirically-verified findings — both accuracy/robustness
bugs, not security.

1. **A real accuracy bug on 2 of the 3 implementations
   (`cpu_usage_h`, `chat_agent.py`'s dispatch): a SINGLE read of
   `/proc/stat` was mislabeled as "current" CPU usage.**
   `/proc/stat`'s `cpu` line holds CUMULATIVE jiffie counters since
   boot — a single read can only ever compute the AVERAGE utilization
   since the machine booted, not the current, instantaneous load the
   tool's own description promises ("Get current CPU usage
   percentage"). Proved live on this real host: a proper two-sample
   delta read (0.3s apart) reported **9.6%** real current usage, while
   the single-read formula these two implementations use reported
   **22.4%** for the exact same moment — a genuinely different, wrong
   number, not just a rounding difference, and the gap only grows the
   longer the host has been up. `mon_cpu_usage` (the third
   implementation) didn't have this specific bug — it shells out to
   `top -bn1`, which samples over a short internal window — but was
   inconsistent with the other two and had no `/proc/stat` fast path
   at all.

2. **A real robustness gap on `mon_cpu_usage`: no `try/except` at all
   around the `top` subprocess call.** Unlike its two siblings (both
   already wrapped in `try/except Exception`), a missing `top` binary
   (a real, plausible case in a minimal container image — this
   project's own `docker-compose.yml` builds several service images)
   would raise an uncaught `FileNotFoundError` straight out of the
   handler instead of a clean `[ERROR]` string.

Fixed via a shared `cpu_usage_handler()`: reads `/proc/stat` TWICE,
`_SAMPLE_INTERVAL_SECONDS` apart, and computes the delta-based
percentage — closing finding #1 with a real, correct measurement
instead of a mislabeled average. Falls back to parsing `top -bn1`
output (matching the pre-existing sibling behavior, unchanged) only
when `/proc/stat` isn't available (non-Linux hosts) — the whole
function is wrapped in `try/except`, closing finding #2.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

_SAMPLE_INTERVAL_SECONDS = 0.3


def _read_proc_stat_totals() -> tuple[int, int] | None:
    """Returns (idle_jiffies, total_jiffies) from /proc/stat's first
    `cpu` line, or None if unavailable/unparsable."""
    proc_stat = Path("/proc/stat")
    if not proc_stat.exists():
        return None
    try:
        line = proc_stat.read_text().splitlines()[0]
        fields = [int(f) for f in line.split()[1:]]
    except (OSError, IndexError, ValueError):
        return None
    if len(fields) < 5:
        return None
    idle = fields[3]
    total = sum(fields)
    return idle, total


def cpu_usage_handler() -> str:
    """Core cpu_usage logic shared by all three real call sites. Reads
    /proc/stat twice, a short interval apart, and computes the real
    delta-based CPU usage — a single read only measures the average
    since boot, not "current" usage (see this module's docstring)."""
    try:
        sample1 = _read_proc_stat_totals()
        if sample1 is not None:
            time.sleep(_SAMPLE_INTERVAL_SECONDS)
            sample2 = _read_proc_stat_totals()
            if sample2 is not None:
                idle1, total1 = sample1
                idle2, total2 = sample2
                idle_delta = idle2 - idle1
                total_delta = total2 - total1
                if total_delta > 0:
                    pct = round((1 - idle_delta / total_delta) * 100, 1)
                    return f"CPU: {pct}% used"

        r = subprocess.run(["top", "-bn1"], capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            if "%Cpu" in line or "Cpu(s)" in line:
                return line.strip()
        return "[ERROR] Could not read CPU usage"
    except Exception as e:
        return f"[ERROR] {e}"


CPU_USAGE_TOOL = {
    "name": "cpu_usage",
    "description": "Get current CPU usage percentage from /proc/stat or the `top` command.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

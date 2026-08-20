"""Unified background-process spawn/kill/read/list logic — AUDIT_Q_BATCH01
§1 "Terminal/session manager" and §58 "Concurrent shell-session registry".

app/agents/tools.py::make_chat_handlers() (the ~32 one-shot task agents) and
app/agents/chat_agent.py::ChatAgent (the interactive session) each
independently re-implemented the same run_background/kill_process/
read_output logic against their own separately-scoped Popen dict
(_session_bg_procs / self._background_processes). That per-scope dict stays
separate deliberately — chat_agent.py's own docstring: "so one session
cannot kill or read another session's background process" (read_output only
ever looks up PIDs the caller's own dict actually holds) — and
tests/test_gap23_session_close_kills_bg_processes.py directly sets
`agent._background_processes = {...}` as a plain dict, so that attribute
must keep working exactly as before. What WAS duplicated, and is now
single-sourced here, is the ~20 lines of spawn+register / pop+kill / poll+
read logic around that dict — previously two independently-maintained
copies that could (and did) drift, exactly the "no single terminal/session
manager" gap the audit flagged. Both callers now pass their own dict in
rather than re-implementing this.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from typing import Any, Callable

from app.fleet import bg_process_registry

logger = logging.getLogger(__name__)

_SIGNAL_MAP = {
    "TERM": signal.SIGTERM,
    "KILL": getattr(signal, "SIGKILL", signal.SIGTERM),
    "INT": signal.SIGINT,
}


def spawn(
    command: str,
    cwd: str,
    procs: dict[int, "subprocess.Popen[str]"],
    *,
    wait_for_pids: list[int] | None = None,
) -> str:
    """Start `command` in the background, storing its Popen handle in
    `procs` (the caller's own dict) and registering it in the durable
    bg_process_registry. Returns the exact human-readable status string
    every run_background tool handler already returned as-is.

    wait_for_pids (AUDIT_Q_BATCH01 §58 "Task dependency handling between
    terminal jobs" — previously NO code expressed one background job
    depending on another's completion): when given, the real command is
    prefixed with a portable `kill -0`-polling wait loop for each
    dependency PID, so exactly one real OS process (and PID) represents the
    whole dependency-wait-then-run lifecycle — the tool call itself still
    returns immediately, matching every other run_background call's
    existing fire-and-forget contract, and the returned PID can be
    killed/read like any other background process while it waits.

    Found via real execution, not just code review: `kill -0 <pid>` cannot
    distinguish a genuinely running process from a zombie — a dependency
    Popen object that already exited but was never `.wait()`-ed/`.poll()`-ed
    by anything stays visible to `kill -0` indefinitely, which hung the
    wait loop forever in testing. For every dependency PID this caller's
    own `procs` dict actually holds a Popen for, a daemon thread calls
    `.wait()` on it here so it gets reaped the moment it exits, making the
    shell-side `kill -0` check correctly observe the exit shortly after. A
    dependency PID not in `procs` (owned by a different session/process)
    has no Popen handle to reap here — reaping it is that owner's
    responsibility, an inherent limit of any cross-process PID dependency,
    not something this function can fix.
    """
    if wait_for_pids:
        for dep_pid in wait_for_pids:
            dep_proc = procs.get(dep_pid)
            if dep_proc is not None:
                threading.Thread(target=dep_proc.wait, daemon=True).start()
        wait_clause = "".join(
            f"while kill -0 {int(dep_pid)} 2>/dev/null; do sleep 1; done; "
            for dep_pid in wait_for_pids
        )
        command = f"{wait_clause}{command}"
    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as e:
        return f"[ERROR] {e}"
    procs[proc.pid] = proc
    # Gap-closure Day 23 (Stage 1.3, answers.md) — durably persisted so a
    # crash/restart before kill_process ever runs still leaves a trail
    # sweep_orphaned_processes() can find and clean up at the next startup.
    bg_process_registry.register(proc.pid, command, cwd)
    if wait_for_pids:
        return (
            f"Started background process PID {proc.pid} (waiting on "
            f"PID(s) {wait_for_pids} to exit before running): {command[:80]}"
        )
    return f"Started background process PID {proc.pid}: {command[:80]}"


def kill(pid: int, sig_name: str, procs: dict[int, Any]) -> str:
    """Send `sig_name` to `pid`, removing it from `procs` and the durable
    registry.

    tool_enhance.md productionization pass, tool #49 (2026-08-20) — real,
    empirically-proven finding: this function previously sent `os.kill()`
    to ANY pid at all, with no check that it belonged to a process the
    calling session actually spawned via `run_background`. Proved live: a
    completely unrelated `sleep 300` process, never tracked in `procs`,
    was genuinely killed. That included the ability to kill the backend
    server's own process, or any other process on the host the server's
    OS user has permission to signal — a real arbitrary-process-
    termination primitive, despite `kill_process`'s own schema
    documenting it as "Kill a background process by PID. Use after
    run_background." A prior refactor (the de-duplication that created
    this shared module) explicitly preserved that gap rather than
    introducing one, matching the pre-existing behavior at both original
    call sites — see git history for that decision's own reasoning.
    Raised to the user directly (AskUserQuestion) given it was a
    documented, deliberate prior choice, not an oversight; user chose to
    close it. Fixed: `pid` must now be a key in the caller's own `procs`
    dict (i.e. a process this exact session started via `run_background`)
    before any signal is sent — matching the tool's own documented
    contract exactly.
    """
    if pid not in procs:
        return (
            f"[ERROR] PID {pid} was not started by run_background in this "
            "session — kill_process can only stop processes this session "
            "itself spawned."
        )
    sig = _SIGNAL_MAP.get(sig_name, signal.SIGTERM)
    procs.pop(pid, None)
    bg_process_registry.unregister(pid)
    try:
        os.kill(pid, sig)
        return f"Sent {sig_name} to PID {pid}"
    except ProcessLookupError:
        return f"[ERROR] No process with PID {pid}"
    except Exception as e:
        return f"[ERROR] {e}"


def read_output(
    pid: int,
    max_lines: int,
    procs: dict[int, Any],
    read_stream_fn: Callable[[Any], str | None],
) -> str:
    """Best-effort read of buffered stdout/stderr for a PID tracked in the
    caller's own `procs` dict — deliberately NOT global, preserving the
    existing per-session/per-call isolation (see module docstring).
    read_stream_fn is the caller's own non-blocking stream reader (tools.py
    and chat_agent.py each already have a functionally identical
    _read_stream_nonblocking; passed in rather than imported to avoid a new
    import cycle between the two modules)."""
    proc = procs.get(pid)
    if proc is None:
        return f"[ERROR] No tracked background process with PID {pid}"
    if proc.poll() is not None:
        return f"Process {pid} has exited (code {proc.returncode})"
    out_lines: list[str] = []
    for stream in (proc.stdout, proc.stderr):
        if stream is None:
            continue
        chunk = read_stream_fn(stream)
        if chunk:
            out_lines.extend(chunk.splitlines())
    return (
        "\n".join(out_lines[-max_lines:])
        if out_lines
        else f"(no output yet from PID {pid})"
    )


def list_tracked(procs: dict[int, "subprocess.Popen[str]"]) -> list[dict[str, Any]]:
    """Real snapshot of the caller's own tracked background processes —
    AUDIT_Q_BATCH01 §58 "Concurrent shell-session registry": previously
    there was no way for a caller to enumerate what it had started at all
    (list_processes is host-wide `ps aux`, unrelated). Age/command come
    from the shared durable registry (bg_process_registry.snapshot()), the
    one place start time is already recorded, rather than a second,
    duplicate timestamp store here. possibly_hung mirrors the liveness
    loop's own advisory (not destructive) hang signal."""
    registry_meta = bg_process_registry.snapshot()
    now = time.time()
    threshold = bg_process_registry.hang_threshold_seconds()
    result: list[dict[str, Any]] = []
    for pid, proc in procs.items():
        meta = registry_meta.get(str(pid), {})
        started_at = meta.get("started_at")
        age_seconds = (now - started_at) if started_at else None
        alive = proc.poll() is None
        result.append(
            {
                "pid": pid,
                "command": meta.get("command", "?"),
                "cwd": meta.get("cwd", "?"),
                "alive": alive,
                "age_seconds": (
                    round(age_seconds, 1) if age_seconds is not None else None
                ),
                "possibly_hung": bool(
                    alive and age_seconds is not None and age_seconds > threshold
                ),
            }
        )
    return result


def format_tracked(procs: dict[int, "subprocess.Popen[str]"]) -> str:
    """Human-readable rendering of list_tracked(), used directly by the
    list_background_processes tool handler in both tools.py and
    chat_agent.py."""
    entries = list_tracked(procs)
    if not entries:
        return "(no tracked background processes for this session)"
    lines = ["Tracked background processes:"]
    for e in sorted(entries, key=lambda x: x["pid"]):
        status = "running" if e["alive"] else "exited"
        hung_flag = " [POSSIBLY HUNG]" if e["possibly_hung"] else ""
        age = f"{e['age_seconds']:.0f}s" if e["age_seconds"] is not None else "?"
        lines.append(
            f"  PID {e['pid']}  [{status}]{hung_flag}  age={age}  cwd={e['cwd']}  "
            f"cmd={str(e['command'])[:80]}"
        )
    return "\n".join(lines)

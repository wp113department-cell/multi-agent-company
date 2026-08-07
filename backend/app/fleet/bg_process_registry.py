"""Gap-closure Day 23 (Stage 1.3, answers.md) — durable background-process
PID tracking + orphan cleanup.

Background processes started via the run_background tool (both
app/agents/tools.py::make_chat_handlers() for the ~32 one-shot task agents,
and app/agents/chat_agent.py::ChatAgent's own separate implementation for
the long-lived interactive chat session) were tracked only in an
in-process Python dict scoped to that specific session/run
(_session_bg_procs / self._background_processes). If the process hosting
that dict crashes, restarts, or a session ends without every code path
remembering to call kill_process first, the real OS-level subprocess
keeps running with nothing left able to find or stop it — a genuine
orphan (a GC'd Popen object does not terminate the OS process it wraps).

Two real, complementary mechanisms close this:
  1. A durable, file-based registry (JSON) written alongside each
     in-memory dict, so a PID survives a process crash.
  2. sweep_orphaned_processes() — called once at FastAPI startup: anything
     still in the registry at that point was left over by whatever
     process wrote it (a fresh process could not have legitimately
     started it), so it's terminated and the registry is cleared.
The registry carries no "still wanted" signal — being in the file at
startup IS the orphan signal, since a graceful shutdown (kill_process(),
ChatAgent session close) always removes its own entries first.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import time
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_lock = Lock()


def _registry_path() -> Path:
    from app.config import get_settings

    return Path(get_settings().bg_process_registry_path)


def register(pid: int, command: str, cwd: str) -> None:
    with _lock:
        path = _registry_path()
        entries = _read(path)
        entries[str(pid)] = {
            "command": command,
            "cwd": cwd,
            "started_at": time.time(),
        }
        _write(path, entries)


def unregister(pid: int) -> None:
    with _lock:
        path = _registry_path()
        entries = _read(path)
        if entries.pop(str(pid), None) is not None:
            _write(path, entries)


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded: Any = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _write(path: Path, entries: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries), encoding="utf-8")
    tmp.replace(path)  # atomic replace on both POSIX and Windows


def _terminate(pid: int) -> bool:
    # SIGKILL doesn't exist on Windows (same finding already documented in
    # app/agents/tools.py::kill_process / chat_agent.py's own handler) —
    # SIGTERM already maps to TerminateProcess there, an unconditional hard
    # kill, so it's the right single signal to use for orphan cleanup
    # regardless of platform.
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        return False  # already gone — not an orphan needing cleanup
    except Exception as exc:
        logger.warning("Failed to terminate orphaned PID %d: %s", pid, exc)
        return False


def sweep_orphaned_processes() -> list[int]:
    """Called once at FastAPI startup, before any agent can start a new
    background process. Terminates everything left in the registry and
    clears it. Returns the PIDs actually terminated (for logging)."""
    with _lock:
        path = _registry_path()
        entries = _read(path)
        killed: list[int] = []
        for pid_str, meta in entries.items():
            try:
                pid = int(pid_str)
            except ValueError:
                continue
            if _terminate(pid):
                killed.append(pid)
                logger.warning(
                    "Orphaned background process PID %d (command=%r, cwd=%r) "
                    "terminated at startup",
                    pid,
                    meta.get("command", "?"),
                    meta.get("cwd", "?"),
                )
        if path.exists():
            path.unlink()
        return killed


# ---------------------------------------------------------------------------
# AUDIT_Q_BATCH08 §38 "Failure Recovery — Terminal/shell session closes":
# sweep_orphaned_processes() above only ever runs once, at the next app
# startup — nothing previously detected a background shell process (started
# via the run_background tool) dying on its own — crashing, being killed
# externally, or its underlying terminal/shell session closing — WHILE the
# app keeps running. This is that live, periodic counterpart, mirroring
# app/services/retention.py::start_retention_loop()'s exact shape (run
# forever, log + swallow errors, fixed interval) — not a new scheduling
# mechanism.
# ---------------------------------------------------------------------------

_LIVENESS_SWEEP_INTERVAL_SECONDS = 60


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but owned by someone else — cannot happen for a PID this
        # process itself spawned, but fail toward "alive" rather than
        # falsely reaping a process this check can't actually confirm is
        # dead.
        return True


def _sweep_dead_registry_entries() -> list[int]:
    """One liveness pass: any PID no longer alive (exited on its own,
    without a code path calling kill_process()/unregister() first — e.g. a
    run_background shell session that closed or crashed mid-run) is removed
    from the durable registry and reported. Synchronous/blocking (os.kill is
    a cheap syscall, not I/O-bound) — start_bg_process_liveness_loop() below
    runs this via asyncio.to_thread so it never blocks the event loop."""
    with _lock:
        path = _registry_path()
        entries = _read(path)
        if not entries:
            return []
        dead: list[int] = []
        changed = False
        for pid_str in list(entries):
            try:
                pid = int(pid_str)
            except ValueError:
                del entries[pid_str]
                changed = True
                continue
            if not _is_alive(pid):
                dead.append(pid)
                del entries[pid_str]
                changed = True
        if changed:
            _write(path, entries)
        return dead


async def start_bg_process_liveness_loop() -> None:
    """Background task: while the app keeps running (not just at the next
    startup), periodically checks every registered background-process PID
    for liveness and reaps any that exited on their own from the durable
    registry, publishing a health event so the loss is observable instead of
    silently discovered only at the next restart's startup sweep.

    Deliberately NOT gated by app.main.py's leader-election mechanism
    (_run_as_leader): the registry is a local JSON file
    (bg_process_registry_path) tracking PIDs spawned by THIS host process —
    meaningless to any other instance in a multi-instance deployment, unlike
    the DB-backed loops that mechanism protects against duplicate work
    across instances. sweep_orphaned_processes() above is, for the same
    reason, also called directly rather than through leader election.
    """
    import asyncio

    while True:
        try:
            dead = await asyncio.to_thread(_sweep_dead_registry_entries)
            if dead:
                logger.warning(
                    "Background-process liveness sweep: %d process(es) exited "
                    "without cleanup (PIDs %s) — registry entries reaped",
                    len(dead),
                    dead,
                )
                try:
                    from app.fleet.fleet_events import health_updated, publish

                    publish(
                        health_updated(
                            "bg_process_registry",
                            health="degraded",
                            state=(
                                f"{len(dead)} background process(es) exited "
                                "without cleanup (closed shell/crash while "
                                "the app kept running)"
                            ),
                        )
                    )
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Background-process liveness sweep error: %s", exc)

        await asyncio.sleep(_LIVENESS_SWEEP_INTERVAL_SECONDS)

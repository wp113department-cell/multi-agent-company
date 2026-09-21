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
import re
import signal
import subprocess
import threading
import time
from pathlib import Path
from threading import Lock
from typing import Any

try:  # pinned in requirements.txt; degrade to the old PID-only behavior if absent
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

logger = logging.getLogger(__name__)

_lock = Lock()


def _registry_path() -> Path:
    from app.config import get_settings

    return Path(get_settings().bg_process_registry_path)


# ---------------------------------------------------------------------------
# Process-tree termination primitives (verification batch B1, item #25).
#
# Proved live: with the default sandbox on, a background job is
# `sh -c "docker run ... <cmd>"`, and the three cleanup paths that did NOT go
# through process_manager.kill() — ChatAgent session close, the startup orphan
# sweep, the liveness reaper — signalled only that `sh` wrapper (proc.terminate
# / os.kill(pid)). The `docker run` client and the CONTAINER kept running
# indefinitely. kill_process(signal=KILL) had the same hole (a SIGKILLed
# `docker run` client cannot forward anything to its container). Everything
# now goes through the helpers below.
# ---------------------------------------------------------------------------

_CONTAINER_NAME_RE = re.compile(r"^gridiron-bg-[0-9a-f]{12}$")
_FORCE_KILL_GRACE_SECONDS = 8.0


def process_start_time(pid: int) -> float | None:
    """Epoch creation time of `pid`, or None if it does not exist / cannot be
    read (or psutil is unavailable)."""
    if psutil is None:
        return None
    try:
        return float(psutil.Process(pid).create_time())
    except psutil.Error:
        return None


def _same_process(pid: int, meta: dict[str, Any]) -> bool:
    """True only if `pid` is (still) the process this registry entry was
    written for. A bare os.kill(pid, 0) says "some process has this PID" — after
    a crash/restart a recycled PID belongs to an UNRELATED process, and the old
    startup sweep would SIGTERM it."""
    if psutil is None:
        return _is_alive(pid)
    created = process_start_time(pid)
    if created is None:
        return False  # gone (or not ours to signal)
    recorded = meta.get("proc_start")
    if recorded:
        return abs(created - float(recorded)) <= 1.0
    started_at = meta.get("started_at")
    if not started_at:
        return True
    # A process created AFTER the entry was written cannot be the one it
    # describes (legacy entries carry no proc_start).
    return created <= float(started_at) + 2.0


def signal_process(pid: int, sig: int) -> bool:
    """Signal `pid`'s whole process group when `pid` leads its own group
    (process_manager.spawn uses start_new_session=True), otherwise just `pid`
    — never a group that isn't exclusively ours. False if the process is gone."""
    getpgid = getattr(os, "getpgid", None)
    killpg = getattr(os, "killpg", None)
    try:
        pgid = getpgid(pid) if getpgid else None
    except ProcessLookupError:
        return False
    except OSError:
        pgid = None
    try:
        if killpg is not None and pgid is not None and pgid == pid:
            killpg(pgid, sig)
        else:
            os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return False
    except Exception as exc:
        logger.warning("Failed to signal PID %d: %s", pid, exc)
        return False


def kill_container(name: str | None, sig_name: str = "KILL") -> None:
    """Best-effort `docker kill --signal=<sig> <name>` for a sandboxed
    background job's container. Name is validated against the exact pattern
    process_manager.spawn generates, so a tampered registry file can never make
    us kill an arbitrary container."""
    if not name or not _CONTAINER_NAME_RE.match(name):
        return
    if sig_name not in ("TERM", "KILL", "INT"):
        sig_name = "TERM"
    try:
        subprocess.run(
            ["docker", "kill", f"--signal={sig_name}", name],
            capture_output=True,
            timeout=15,
        )
    except Exception:
        logger.debug("docker kill %s failed", name, exc_info=True)


def terminate(
    pid: int,
    container: str | None = None,
    *,
    grace_seconds: float = _FORCE_KILL_GRACE_SECONDS,
) -> bool:
    """Ask a background job — its process group AND its sandbox container — to
    exit (SIGTERM), then force-kill anything still alive after `grace_seconds`.
    Returns whether the process was alive to be signalled."""
    started = process_start_time(pid)
    alive = signal_process(pid, signal.SIGTERM)
    kill_container(container, "TERM")
    if grace_seconds > 0 and (alive or container):

        def _force() -> None:
            if (
                alive
                and started is not None
                and process_start_time(pid)
                == started  # same process, not a recycled PID
            ):
                signal_process(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
            kill_container(container, "KILL")

        timer = threading.Timer(grace_seconds, _force)
        timer.daemon = True
        timer.start()
    return alive


def register(pid: int, command: str, cwd: str, container: str | None = None) -> None:
    with _lock:
        path = _registry_path()
        entries = _read(path)
        entries[str(pid)] = {
            "command": command,
            "cwd": cwd,
            "started_at": time.time(),
            "proc_start": process_start_time(pid),
            "container": container,
        }
        _write(path, entries)


def unregister(pid: int) -> None:
    with _lock:
        path = _registry_path()
        entries = _read(path)
        if entries.pop(str(pid), None) is not None:
            _write(path, entries)


def snapshot() -> dict[str, Any]:
    """Read-only copy of the durable registry (pid-string -> {command, cwd,
    started_at}) — AUDIT_Q_BATCH01 §58 "Concurrent shell-session registry".
    Used by app.fleet.process_manager to report age/possibly-hung status for
    a caller's own tracked processes without exposing this module's
    internal file-I/O helpers or lock."""
    with _lock:
        return dict(_read(_registry_path()))


def hang_threshold_seconds() -> float:
    from app.config import get_settings

    return float(get_settings().bg_process_hang_threshold_seconds)


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


def sweep_orphaned_processes() -> list[int]:
    """Called once at FastAPI startup, before any agent can start a new
    background process. Terminates everything left in the registry and
    clears it. Returns the PIDs actually terminated (for logging).

    A registry PID that no longer refers to the process that was registered
    (it exited, or the PID was recycled by an unrelated process) is NEVER
    signalled. Its sandbox container, if any, is still killed — the container
    has a unique name and outlives its `docker run` client."""
    with _lock:
        path = _registry_path()
        entries = _read(path)
        killed: list[int] = []
        for pid_str, meta in entries.items():
            try:
                pid = int(pid_str)
            except ValueError:
                continue
            container = meta.get("container")
            if _same_process(pid, meta):
                if terminate(pid, container):
                    killed.append(pid)
                    logger.warning(
                        "Orphaned background process PID %d (command=%r, cwd=%r) "
                        "terminated at startup",
                        pid,
                        meta.get("command", "?"),
                        meta.get("cwd", "?"),
                    )
            else:
                kill_container(container, "KILL")
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
            meta = entries[pid_str] if isinstance(entries[pid_str], dict) else {}
            if not _same_process(pid, meta):
                dead.append(pid)
                # The `sh` wrapper is gone (or its PID was recycled) but a
                # sandboxed job's container can outlive it.
                kill_container(meta.get("container"), "KILL")
                del entries[pid_str]
                changed = True
        if changed:
            _write(path, entries)
        return dead


def _sweep_hung_registry_entries() -> list[tuple[int, float]]:
    """AUDIT_Q_BATCH01 §17 'Detect hanging processes': the liveness sweep
    above already detects a background process that *exited* on its own —
    but a process that is still alive, just stuck (no natural exit, no
    crash) was previously undetectable short of an operator manually
    checking. This is advisory-only and non-destructive (returns ages, does
    NOT remove or kill anything) — many legitimate background commands
    (dev servers, watchers, `tail -f`) are supposed to run indefinitely, so
    auto-killing on age alone would be a real functionality regression, not
    a fix."""
    threshold = hang_threshold_seconds()
    now = time.time()
    with _lock:
        entries = _read(_registry_path())
    hung: list[tuple[int, float]] = []
    for pid_str, meta in entries.items():
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        started_at = meta.get("started_at")
        if not started_at or not _same_process(pid, meta):
            continue
        age = now - started_at
        if age > threshold:
            hung.append((pid, age))
    return hung


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

            hung = await asyncio.to_thread(_sweep_hung_registry_entries)
            if hung:
                logger.warning(
                    "Background-process liveness sweep: %d process(es) still "
                    "alive past the %.0fs hang threshold (advisory only, not "
                    "killed): %s",
                    len(hung),
                    hang_threshold_seconds(),
                    hung,
                )
                try:
                    from app.fleet.fleet_events import health_updated, publish

                    publish(
                        health_updated(
                            "bg_process_registry",
                            health="degraded",
                            state=(
                                f"{len(hung)} background process(es) still running "
                                f"past {hang_threshold_seconds():.0f}s (possibly hung "
                                "— not auto-killed)"
                            ),
                        )
                    )
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Background-process liveness sweep error: %s", exc)

        await asyncio.sleep(_LIVENESS_SWEEP_INTERVAL_SECONDS)

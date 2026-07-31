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

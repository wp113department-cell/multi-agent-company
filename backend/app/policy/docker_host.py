"""Docker access when the backend itself runs in a container (2026-10-09).

The Docker/Windows version runs the backend in a container that talks to
the computer's own Docker engine through the mounted Docker socket. Every
sandbox (job sandbox, bash tools, background processes, terminal) starts
its containers through that engine, so a folder must be named the way the
ENGINE sees it, not the way the backend container sees it: `/workspace/x`
inside the backend is e.g. `C:\\Users\\me\\Documents\\multi-agent-workspace\\x`
or a named volume to the engine. The engine already knows this mapping: it
created the backend's own mounts, so `docker inspect <own container>` lists
each mount's Source (engine side) and Destination (backend side), and a
backend path is translated through the mount that holds it.

When the backend runs directly on the computer (no `/.dockerenv`), paths are
already the engine's paths and every function here returns exactly what the
callers built before this module existed.

The same self-inspection identifies the platform's own containers (the
backend's compose project: database, Redis, backend...), which agents may
never exec into or restart.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any


class SharedFolderError(RuntimeError):
    """A folder can't be handed to a sandbox container (not shared with the
    Docker engine, or the backend's own container can't be inspected)."""


_SELF: dict[str, Any] | None = None


def in_container() -> bool:
    return os.path.exists("/.dockerenv")


def _inspect(name: str) -> dict[str, Any] | None:
    try:
        r = subprocess.run(
            ["docker", "inspect", name], capture_output=True, text=True, timeout=10
        )
    except Exception:
        return None
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout)
    except ValueError:
        return None
    return data[0] if data else None


def _self_info() -> dict[str, Any] | None:
    """The backend's own container (cached once found; a failed lookup is
    retried, so a Docker engine that starts late is picked up)."""
    global _SELF
    if _SELF is None:
        # Docker sets the hostname to the container id unless compose sets
        # `hostname:`; the compose file here doesn't.
        _SELF = _inspect(os.environ.get("HOSTNAME", ""))
    return _SELF


def reset_cache() -> None:
    """Test-only."""
    global _SELF
    _SELF = None


def _locate(path: str) -> tuple[dict[str, Any], str]:
    """The backend mount holding `path`, and the rest of the path below it."""
    info = _self_info()
    if info is None:
        raise SharedFolderError(
            "The backend could not look up its own container in Docker, so it "
            "cannot share folders with the code sandbox."
        )
    real = os.path.realpath(path)
    best: tuple[str, dict[str, Any]] | None = None
    for mount in info.get("Mounts") or []:
        dest = str(mount.get("Destination", "")).rstrip("/")
        if not dest or not (mount.get("Source") or mount.get("Name")):
            continue
        if (real == dest or real.startswith(dest + "/")) and (
            best is None or len(dest) > len(best[0])
        ):
            best = (dest, mount)
    if best is None:
        raise SharedFolderError(
            f"{path} is not inside a folder shared with Docker (the workspace "
            "or the task worktrees), so the code sandbox cannot use it."
        )
    dest, mount = best
    return mount, real[len(dest) :]


def engine_path(path: str) -> str:
    """`path` (as the backend sees it) as the Docker engine sees it: a folder
    of the computer, or `volume:<name>/<sub-folder>` for a named volume."""
    if not in_container():
        return path
    mount, rest = _locate(path)
    if mount.get("Type") == "volume":
        return f"volume:{mount.get('Name')}{rest}"
    source = str(mount["Source"])
    if "\\" in source:  # a Windows path as the engine stores it
        source, rest = source.rstrip("\\"), rest.replace("/", "\\")
    else:
        source = source.rstrip("/") or "/"
    return source + rest if rest else source


def _csv(field: str) -> str:
    """--mount is CSV: quote a field that holds a comma or a quote."""
    if "," in field or '"' in field:
        return '"' + field.replace('"', '""') + '"'
    return field


def mount_args(path: str, target: str, mode: str) -> list[str]:
    """docker-run arguments that mount `path` at `target` (mode rw/ro).

    On the computer itself: the same `-v path:target:mode` as always. Inside
    a container: `--mount`, with the engine's own name for the folder:
    - a folder of the computer (the workspace): a bind mount of its real
      path; `--mount`, not `-v`, because a Windows source (`C:\\...`) holds
      a colon, which `-v` reads as a separator;
    - a named volume (the task worktrees): a volume mount of just this
      sub-folder (`volume-subpath`), so a job never sees other tasks'
      folders. (Binding the volume's internal `/var/lib/docker/...` path
      instead hangs Docker Desktop, which looks for it on the computer.)"""
    if not in_container():
        return ["-v", f"{path}:{target}:{mode}"]
    mount, rest = _locate(path)
    if mount.get("Type") == "volume":
        spec = f"type=volume,{_csv('source=' + str(mount.get('Name')))},target={target}"
        if rest.strip("/"):
            spec += "," + _csv("volume-subpath=" + rest.strip("/"))
    else:
        spec = f"type=bind,{_csv('source=' + engine_path(path))},target={target}"
    if mode == "ro":
        spec += ",readonly"
    return ["--mount", spec]


def platform_container_reason(container: str) -> str | None:
    """A refusal reason when `container` is one of the platform's own
    containers (same compose project as the backend, or the backend itself).
    Only applies inside a container; on the computer itself there is no own
    compose project to protect and this returns None."""
    if not in_container():
        return None
    me = _self_info()
    if me is None:
        return "could not identify the platform's own containers; refusing"
    target = _inspect(container)
    if target is None:
        return None  # the caller's own checks report a missing container
    if target.get("Id") == me.get("Id"):
        return "agents may not act on the platform's own backend container"
    label = "com.docker.compose.project"
    mine = ((me.get("Config") or {}).get("Labels") or {}).get(label)
    theirs = ((target.get("Config") or {}).get("Labels") or {}).get(label)
    if mine and theirs == mine:
        name = str(target.get("Name", container)).lstrip("/")
        return (
            f"container {name!r} belongs to the platform itself (database, "
            "queue or app); agents may not exec into or restart it"
        )
    return None

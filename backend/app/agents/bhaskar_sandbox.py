"""bhaskar_sandbox — hardened, isolated Python execution for bhaskar_tool's
internally-generated, unreviewed scripts (app/agents/bhaskar_agent.py,
app/tools/agents/bhaskar_tool.py).

Deliberately NOT a reuse of app/tools/execution/python_snippet.py's
run_python_snippet_handler: that tool is designed for a TRUSTED agent
running a snippet inside the real repo (cwd=repo_path, inherits the full
process environment, shell=True + shlex.quote). bhaskar_tool's scripts are
LLM-generated for an open-ended task with no relationship to the repo at
all, so this module applies a strictly tighter, additive set of controls
instead of reusing that one:

  - isolated per-run tempdir (never repo_path) as both cwd and HOME/TMPDIR
  - a minimal allowlisted environment (PATH/VIRTUAL_ENV/LANG only) — the
    real process environment (ANTHROPIC_API_KEY, database credentials,
    etc., per app/config.py Settings) is never inherited
  - a filesystem guard (injected, like the network guard) restricting
    open()/rename/remove/mkdir/symlink/shutil.* to the sandbox directory
    (plus read-only access to the Python installation itself, required for
    imports to keep working) — validated via os.path.realpath, so a
    symlink created inside the sandbox pointing outside it is still caught
  - kernel-enforced resource limits (CPU time, address space, max single
    file size, open-file count, max process/thread count) via
    preexec_fn/resource.setrlimit — real limits the kernel enforces, not
    just a Python-level timeout
  - a live watchdog (not just subprocess.run's single timeout) that also
    polls total sandbox directory size and kills the process on either
    deadline — RLIMIT_FSIZE alone only bounds a single file, not the sum
    of many small ones
  - the whole process GROUP is killed on timeout/quota breach (POSIX,
    start_new_session=True + os.killpg), not just the direct child — a
    script that spawns its own subprocess can no longer outlive its parent
  - an injected network guard that resolves a hostname ONCE, validates
    EVERY resolved address (IPv4 and IPv6, including IPv4-mapped IPv6
    addresses) against the same private/loopback/link-local/reserved
    denylist app/agents/tool_security.py's `_ssrf_denial_reason` already
    enforces for fetch_url/check_url_status, and then connects to a PINNED
    validated IP rather than letting the standard library re-resolve the
    hostname a second time at connect() — closing the classic DNS-
    rebinding/TOCTOU gap a naive "resolve, check, then call the original
    connect(hostname)" guard would have. AF_UNIX socket connections are
    blocked outright (no legitimate use for a one-off script, and a path
    like a container/orchestrator control socket is a real local-escalation
    vector). Kept as an independent, self-contained stdlib-only
    implementation here since this guard runs textually inside a bare
    `python3 <script>` subprocess that must not depend on importing the
    app package.
  - direct argv invocation (no shell=True) — the whole shell-injection
    class that shapes run_python_snippet's design does not apply here by
    construction

WHAT THIS IS NOT: a hard multi-tenant security boundary. Every control here
runs inside the SAME kernel, as the SAME OS user, as the rest of this
process — there is no container, VM, gVisor/nsjail-style syscall filter, or
separate user namespace. The filesystem/network guards are Python-level
monkeypatches: they stop `open()`/`socket.connect()`/etc. (which covers the
realistic LLM-generated-script threat model this tool targets), not a
process using `ctypes` to call raw libc syscalls, a compiled extension, or
`os.open`/other low-level fd APIs (deliberately NOT patched — doing so
risks breaking the interpreter's own internals, e.g. subprocess/tempfile/
import machinery, for limited additional real-world benefit against the
threat model here). Do not run genuinely untrusted or adversarial
(as opposed to merely unreviewed) code through this sandbox and treat it as
equivalent to container/VM isolation.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Imported at module load time (before any fork can happen), never inside
# the preexec_fn itself — `import` acquires the interpreter's import lock,
# and calling it post-fork in a preexec_fn risks a real deadlock if another
# thread in this (multi-threaded, asyncio.to_thread-using) process held
# that lock at fork time. Pre-importing means the preexec_fn only ever
# calls the already-resolved C-level setrlimit, which is fork-safe.
if sys.platform != "win32":
    import resource as _resource
else:  # pragma: no cover - Windows has no `resource` module
    _resource = None  # type: ignore[assignment]

_USE_PROCESS_GROUP = sys.platform != "win32"

# ---------------------------------------------------------------------------
# Injected preludes — self-contained, stdlib-only, textually prepended to
# every sandboxed script.
# ---------------------------------------------------------------------------

# {sandbox_dir!r} is substituted at build time (see _build_script below).
_FILESYSTEM_GUARD_PRELUDE_TEMPLATE = """\
import builtins as __bhaskar_builtins
import os as __bhaskar_os
import shutil as __bhaskar_shutil
import sys as __bhaskar_sys

__bhaskar_sandbox_dir = __bhaskar_os.path.realpath({sandbox_dir!r})
# Read-only allowance for the Python installation itself — required for
# `import` machinery (stdlib + this venv's site-packages) to keep working;
# writes are never allowed here regardless.
__bhaskar_ro_roots = tuple(
    __bhaskar_os.path.realpath(p)
    for p in {{__bhaskar_sys.prefix, __bhaskar_sys.base_prefix, __bhaskar_sys.exec_prefix}}
    if p
)

def __bhaskar_under(path, roots):
    try:
        rp = __bhaskar_os.path.realpath(path)
    except Exception:
        return False
    for root in roots:
        if rp == root or rp.startswith(root + __bhaskar_os.sep):
            return True
    return False

def __bhaskar_check_write_path(path):
    if not __bhaskar_under(path, (__bhaskar_sandbox_dir,)):
        raise PermissionError(
            "bhaskar_tool sandbox: write access to " + repr(path) +
            " is blocked (outside the isolated sandbox directory)"
        )

def __bhaskar_check_read_path(path):
    if __bhaskar_under(path, (__bhaskar_sandbox_dir,) + __bhaskar_ro_roots):
        return
    raise PermissionError(
        "bhaskar_tool sandbox: read access to " + repr(path) +
        " is blocked (outside the isolated sandbox directory)"
    )

__bhaskar_orig_open = __bhaskar_builtins.open
def __bhaskar_guarded_open(file, mode="r", *a, **kw):
    if isinstance(file, (str, bytes, __bhaskar_os.PathLike)):
        if any(c in mode for c in ("w", "a", "x", "+")):
            __bhaskar_check_write_path(file)
        else:
            __bhaskar_check_read_path(file)
    return __bhaskar_orig_open(file, mode, *a, **kw)
__bhaskar_builtins.open = __bhaskar_guarded_open
# pathlib.Path.open/read_text/read_bytes/write_text and io.open() all go through io.open,
# which is a separate reference from builtins.open — patching only builtins.open left
# `Path("/any/file").read_text()` (the most common file API in generated scripts) unguarded.
import io as __bhaskar_io
__bhaskar_io.open = __bhaskar_guarded_open

__bhaskar_orig_os_open = __bhaskar_os.open
__bhaskar_WRITE_FLAGS = (
    __bhaskar_os.O_WRONLY | __bhaskar_os.O_RDWR | __bhaskar_os.O_CREAT
    | __bhaskar_os.O_TRUNC | __bhaskar_os.O_APPEND
)
def __bhaskar_guarded_os_open(path, flags, *a, **kw):
    if kw.get("dir_fd") is None and isinstance(path, (str, bytes, __bhaskar_os.PathLike)):
        if flags & __bhaskar_WRITE_FLAGS:
            __bhaskar_check_write_path(path)
        else:
            __bhaskar_check_read_path(path)
    return __bhaskar_orig_os_open(path, flags, *a, **kw)
__bhaskar_os.open = __bhaskar_guarded_os_open

def __bhaskar_make_read_guard(orig):
    def _guarded(path=".", *a, **kw):
        if isinstance(path, (str, bytes, __bhaskar_os.PathLike)):
            __bhaskar_check_read_path(path)
        return orig(path, *a, **kw)
    return _guarded
for _name in ("listdir", "scandir"):
    setattr(__bhaskar_os, _name, __bhaskar_make_read_guard(getattr(__bhaskar_os, _name)))

def __bhaskar_deny_chdir(*a, **kw):
    raise PermissionError("bhaskar_tool sandbox: os.chdir is blocked")
__bhaskar_os.chdir = __bhaskar_deny_chdir

def __bhaskar_deny_symlink(*a, **kw):
    raise PermissionError("bhaskar_tool sandbox: creating symlinks is blocked")
__bhaskar_os.symlink = __bhaskar_deny_symlink

def __bhaskar_make_write_guard(orig):
    def _guarded(path, *a, **kw):
        __bhaskar_check_write_path(path)
        return orig(path, *a, **kw)
    return _guarded

for _name in ("remove", "unlink", "rmdir", "mkdir", "makedirs", "removedirs"):
    if hasattr(__bhaskar_os, _name):
        setattr(__bhaskar_os, _name, __bhaskar_make_write_guard(getattr(__bhaskar_os, _name)))

__bhaskar_orig_rename = __bhaskar_os.rename
def __bhaskar_guarded_rename(src, dst, *a, **kw):
    __bhaskar_check_write_path(src)
    __bhaskar_check_write_path(dst)
    return __bhaskar_orig_rename(src, dst, *a, **kw)
__bhaskar_os.rename = __bhaskar_guarded_rename
__bhaskar_os.replace = __bhaskar_guarded_rename

for _name in ("rmtree", "copy", "copy2", "copyfile", "copytree", "move"):
    if hasattr(__bhaskar_shutil, _name):
        setattr(__bhaskar_shutil, _name, __bhaskar_make_write_guard(getattr(__bhaskar_shutil, _name)))
"""

_NETWORK_GUARD_PRELUDE = """\
import ipaddress as __bhaskar_ipaddress
import socket as __bhaskar_socket

def __bhaskar_unwrap(ip):
    if isinstance(ip, __bhaskar_ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is not None:
            return __bhaskar_ipaddress.ip_address(mapped)
    return ip

def __bhaskar_is_blocked(ip):
    ip = __bhaskar_unwrap(ip)
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified)

def __bhaskar_resolve_pin(host, port):
    # Resolve ONCE, validate EVERY result, connect to a pinned validated IP
    # — closes the DNS-rebinding/TOCTOU gap of "check hostname, then let
    # the standard library re-resolve and connect to whatever IP a second,
    # later DNS lookup happens to return."
    infos = __bhaskar_socket.getaddrinfo(host, port)
    if not infos:
        raise PermissionError(
            "bhaskar_tool sandbox: could not resolve " + repr(host)
        )
    for family, socktype, proto, canonname, sockaddr in infos:
        try:
            ip = __bhaskar_ipaddress.ip_address(sockaddr[0])
        except ValueError:
            raise PermissionError(
                "bhaskar_tool sandbox: host " + repr(host) +
                " resolved to an unparseable address " + repr(sockaddr[0])
            )
        if __bhaskar_is_blocked(ip):
            raise PermissionError(
                "bhaskar_tool sandbox: network access to " + repr(host) +
                " (resolves to " + str(ip) + ") is blocked "
                "(private/loopback/link-local/reserved/mapped address)"
            )
    # Every resolved address passed — pin to the first one's sockaddr
    # (index 4 of the getaddrinfo 5-tuple: family, type, proto, canonname,
    # sockaddr) for the actual connection, never re-resolve.
    return infos[0][4]

__bhaskar_orig_create_connection = __bhaskar_socket.create_connection
def __bhaskar_guarded_create_connection(address, *a, **kw):
    host, port = address[0], address[1]
    sockaddr = __bhaskar_resolve_pin(host, port)
    pinned = (sockaddr[0], port) + tuple(address[2:])
    return __bhaskar_orig_create_connection(pinned, *a, **kw)
__bhaskar_socket.create_connection = __bhaskar_guarded_create_connection

def __bhaskar_guard_address(address):
    if isinstance(address, str):
        raise PermissionError(
            "bhaskar_tool sandbox: AF_UNIX socket connections are blocked"
        )
    if isinstance(address, tuple) and len(address) >= 2 and isinstance(address[0], str):
        host, port = address[0], address[1]
        sockaddr = __bhaskar_resolve_pin(host, port)
        return (sockaddr[0], port) + tuple(address[2:])
    return address

__bhaskar_orig_connect = __bhaskar_socket.socket.connect
def __bhaskar_guarded_connect(self, address):
    return __bhaskar_orig_connect(self, __bhaskar_guard_address(address))
__bhaskar_socket.socket.connect = __bhaskar_guarded_connect

__bhaskar_orig_connect_ex = __bhaskar_socket.socket.connect_ex
def __bhaskar_guarded_connect_ex(self, address):
    return __bhaskar_orig_connect_ex(self, __bhaskar_guard_address(address))
__bhaskar_socket.socket.connect_ex = __bhaskar_guarded_connect_ex
"""

_NETWORK_DENY_ALL_PRELUDE = """\
import socket as __bhaskar_socket

def __bhaskar_deny(*a, **kw):
    raise PermissionError(
        "bhaskar_tool sandbox: network access is disabled for this run"
    )

__bhaskar_socket.create_connection = __bhaskar_deny
__bhaskar_socket.socket.connect = __bhaskar_deny
__bhaskar_socket.socket.connect_ex = __bhaskar_deny
"""


def _resolve_python_executable(repo_path: str) -> str:
    """Prefer the repo's own .venv interpreter (so installed packages like
    `requests` are importable) — resolved as an absolute interpreter path,
    not shell activation, since it must keep working with cwd pointed at an
    unrelated sandbox tempdir. Falls back to the current interpreter."""
    if repo_path:
        venv_python = (
            Path(repo_path) / ".venv" / "Scripts" / "python.exe"
            if sys.platform == "win32"
            else Path(repo_path) / ".venv" / "bin" / "python3"
        )
        if venv_python.is_file():
            return str(venv_python)
    return sys.executable


def _limit_resources(
    *,
    cpu_seconds: int,
    max_memory_mb: int,
    max_file_mb: int,
    max_processes: int,
) -> Callable[[], None] | None:
    """Returns a preexec_fn (POSIX only — None on Windows, where `resource`
    doesn't exist) that applies kernel-enforced rlimits to the child
    process before exec. Never lets a misconfigured/unsupported limit crash
    the parent: each setrlimit call is independently best-effort.

    RLIMIT_NPROC is counted against the real UID across the WHOLE SYSTEM,
    not just this process tree — in a shared-UID deployment (the sandboxed
    subprocess runs as the same OS user as the rest of this app, there is
    no privilege-dropping/separate-user setup here) a too-low value can
    fail unpredictably if that UID is already near its limit for unrelated
    reasons. Kept deliberately generous (config-driven default) for this
    reason — its purpose is stopping a fork-bomb-shaped script, not tightly
    bounding legitimate concurrency."""
    if _resource is None:
        return None

    def _apply() -> None:
        for res, value in (
            (_resource.RLIMIT_CPU, cpu_seconds),
            (_resource.RLIMIT_FSIZE, max_file_mb * 1024 * 1024),
            (_resource.RLIMIT_AS, max_memory_mb * 1024 * 1024),
            (_resource.RLIMIT_NOFILE, 256),
            (_resource.RLIMIT_NPROC, max_processes),
        ):
            try:
                _resource.setrlimit(res, (value, value))
            except Exception:
                pass

    return _apply


def _scrubbed_env(sandbox_dir: str) -> dict[str, str]:
    """Allowlist-only environment for the sandboxed subprocess — the real
    process environment (ANTHROPIC_API_KEY, database credentials, etc.) is
    never inherited. HOME/TMPDIR are pointed at the isolated sandbox
    directory so any library that writes cache/temp files by default lands
    there, not in the real user's home directory."""
    allowlist = ("PATH", "VIRTUAL_ENV", "LANG", "LC_ALL", "SYSTEMROOT")
    env = {k: os.environ[k] for k in allowlist if k in os.environ}
    env["HOME"] = sandbox_dir
    env["TMPDIR"] = sandbox_dir
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _dir_size_bytes(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _kill_process_tree(proc: "subprocess.Popen[str]") -> None:
    """Kill the whole process group on POSIX (a script that spawned its own
    child processes can no longer outlive its parent past the deadline);
    falls back to killing just the direct child on Windows, where process
    groups work differently and this project's primary deployment target
    is Linux (see module docstring)."""
    try:
        if _USE_PROCESS_GROUP:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
        return
    except Exception:
        pass
    try:
        if _USE_PROCESS_GROUP:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except Exception:
        pass


def _build_script(code: str, sandbox_dir: str, allow_network: bool) -> str:
    fs_guard = _FILESYSTEM_GUARD_PRELUDE_TEMPLATE.format(sandbox_dir=sandbox_dir)
    net_guard = _NETWORK_GUARD_PRELUDE if allow_network else _NETWORK_DENY_ALL_PRELUDE
    return fs_guard + "\n" + net_guard + "\n" + code


_DOCKER_WORKDIR = "/workspace"


def _run_in_docker(
    script: str,
    *,
    timeout: int,
    allow_network: bool,
    max_memory_mb: int,
    max_total_disk_mb: int,
    max_processes: int,
    max_output_chars: int,
) -> dict[str, Any]:
    """OS-level isolation for synthesized scripts (audit 15, 2026-10-06).

    The in-process mode's file guards are Python-level hooks: `_io.FileIO`
    and `ctypes` read the project's backend/.env (API keys) straight past
    them, and with network allowed a script could send them out. Here the
    script runs in a throwaway container that has NO host path mounted at
    all — the project, .env and ~/.ssh simply do not exist inside it — as a
    non-root user, with a read-only root filesystem, every capability
    dropped, no-new-privileges, and memory/pid/CPU limits enforced by the
    kernel. Its only writable space is a size-capped tmpfs, so the disk
    quota is hard rather than polled. The Python guards still run inside the
    container as a second layer. The code arrives on stdin (nothing is
    written on the host). Never raises; refuses (success=False) when Docker
    is unavailable rather than silently falling back to a weaker sandbox.
    """
    from app.config import get_settings
    from app.policy.sandbox import _docker_available

    if not _docker_available():
        return {
            "success": False,
            "output": (
                "[ERROR] sandbox unavailable: Docker is not reachable, and the "
                "isolated sandbox refuses to fall back to host execution "
                "(set BHASKAR_TOOL_SANDBOX_BACKEND=process to opt into the "
                "weaker in-process sandbox explicitly)."
            ),
            "returncode": None,
        }
    import uuid

    name = f"gridiron-bhaskar-{uuid.uuid4().hex[:12]}"
    cmd = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        f"--network={'bridge' if allow_network else 'none'}",
        f"--memory={max_memory_mb}m",
        f"--memory-swap={max_memory_mb}m",
        f"--pids-limit={max(8, max_processes)}",
        "--cpus=1.0",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--tmpfs",
        f"{_DOCKER_WORKDIR}:size={max_total_disk_mb}m,mode=1777",
        "--tmpfs",
        "/tmp:size=16m,mode=1777",
        "--user",
        f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "1000:1000",
        "-e",
        f"HOME={_DOCKER_WORKDIR}",
        "-e",
        f"TMPDIR={_DOCKER_WORKDIR}",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        "GPG_KEY=",  # the python base image's public signing-key id; not needed
        "-w",
        _DOCKER_WORKDIR,
        get_settings().bash_sandbox_toolchain_image,
        "timeout",
        "-s",
        "KILL",
        str(timeout),
        "python",
        "-",
    ]
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout + 30,  # container start-up on top of the script's own limit
        )
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], capture_output=True, timeout=15)
        return {
            "success": False,
            "output": f"[ERROR] sandboxed script timed out after {timeout}s",
            "returncode": None,
        }
    except Exception as exc:
        return {
            "success": False,
            "output": f"[ERROR] sandbox failed to start: {exc}",
            "returncode": None,
        }
    if proc.returncode in (124, 137) and time.monotonic() - started >= timeout:
        return {
            "success": False,
            "output": f"[ERROR] sandboxed script timed out after {timeout}s",
            "returncode": proc.returncode,
        }
    output = (proc.stdout + proc.stderr)[:max_output_chars] or "(no output)"
    if proc.returncode == 137:
        output = "[ERROR] sandboxed script was killed (memory limit)\n" + output
    return {
        "success": proc.returncode == 0,
        "output": output,
        "returncode": proc.returncode,
    }


def run_sandboxed_python(
    code: str,
    *,
    repo_path: str = "",
    timeout: int,
    allow_network: bool = True,
    max_memory_mb: int = 512,
    max_output_file_mb: int = 10,
    max_output_chars: int = 4000,
    max_total_disk_mb: int = 50,
    max_processes: int = 32,
    backend: str | None = None,
) -> dict[str, Any]:
    """Run `code` in an isolated subprocess and return
    {"success": bool, "output": str, "returncode": int | None}. Never
    raises — every failure mode (bad code, timeout, disk-quota breach,
    resource limit hit, blocked filesystem/network access) comes back as
    success=False with a message in output, matching this codebase's
    existing tool-handler convention of structured, non-raising failures.

    A live watchdog polls both the wall-clock deadline and total sandbox
    directory size (RLIMIT_FSIZE alone only bounds a single file, not the
    sum of many small ones) and kills the whole process group on either
    breach — not just the direct child, so a script that spawns its own
    subprocess cannot outlive its parent past the deadline."""
    timeout = max(1, int(timeout))
    if backend is None:
        from app.config import get_settings

        backend = get_settings().bhaskar_tool_sandbox_backend
    if backend == "docker":
        return _run_in_docker(
            _build_script(code, _DOCKER_WORKDIR, allow_network),
            timeout=timeout,
            allow_network=allow_network,
            max_memory_mb=max_memory_mb,
            max_total_disk_mb=max_total_disk_mb,
            max_processes=max_processes,
            max_output_chars=max_output_chars,
        )
    sandbox_dir = tempfile.mkdtemp(prefix="bhaskar_tool_")
    try:
        script_path = Path(sandbox_dir) / "script.py"
        script_path.write_text(
            _build_script(code, sandbox_dir, allow_network), encoding="utf-8"
        )

        python_exe = _resolve_python_executable(repo_path)
        env = _scrubbed_env(sandbox_dir)
        preexec = _limit_resources(
            cpu_seconds=timeout,
            max_memory_mb=max_memory_mb,
            max_file_mb=max_output_file_mb,
            max_processes=max_processes,
        )

        popen_kwargs: dict[str, Any] = {}
        if _USE_PROCESS_GROUP:
            popen_kwargs["start_new_session"] = True
            popen_kwargs["preexec_fn"] = preexec
        elif sys.platform == "win32":
            popen_kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )

        try:
            proc = subprocess.Popen(
                [python_exe, str(script_path)],
                cwd=sandbox_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                **popen_kwargs,
            )
        except Exception as exc:
            return {
                "success": False,
                "output": f"[ERROR] sandbox failed to start: {exc}",
                "returncode": None,
            }

        deadline = time.monotonic() + timeout
        max_total_disk_bytes = max_total_disk_mb * 1024 * 1024
        poll_interval = 0.5
        killed_reason: str | None = None
        stdout, stderr = "", ""
        while True:
            remaining = max(0.05, min(poll_interval, deadline - time.monotonic()))
            try:
                stdout, stderr = proc.communicate(timeout=remaining)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    killed_reason = "timeout"
                elif _dir_size_bytes(sandbox_dir) > max_total_disk_bytes:
                    killed_reason = "disk_quota"
                if killed_reason:
                    _kill_process_tree(proc)
                    try:
                        stdout, stderr = proc.communicate(timeout=5)
                    except Exception:
                        stdout, stderr = stdout or "", stderr or ""
                    break

        if killed_reason == "timeout":
            return {
                "success": False,
                "output": f"[ERROR] sandboxed script timed out after {timeout}s",
                "returncode": proc.returncode,
            }
        if killed_reason == "disk_quota":
            return {
                "success": False,
                "output": (
                    f"[ERROR] sandboxed script exceeded its "
                    f"{max_total_disk_mb}MB total disk quota"
                ),
                "returncode": proc.returncode,
            }

        output = (stdout + stderr)[:max_output_chars] or "(no output)"
        return {
            "success": proc.returncode == 0,
            "output": output,
            "returncode": proc.returncode,
        }
    finally:
        shutil.rmtree(sandbox_dir, ignore_errors=True)


# Internal-only tool — deliberately never registered in tools.py/chat_agent.py
# dispatch. Exposed exclusively to bhaskar_agent's own run_agent_graph() tool
# list (app/agents/bhaskar_agent.py) so its narrow LLM loop can test a draft
# script before returning it. No other agent should ever see this schema —
# giving arbitrary agents raw, unmoderated sandbox access (rather than going
# through bhaskar_tool's cache/eviction/retry wrapper) is exactly what
# bhaskar_tool exists to avoid.
SANDBOXED_RUN_SCRIPT_TOOL: dict[str, Any] = {
    "name": "run_sandboxed_script",
    "description": (
        "Run a self-contained Python script in an isolated sandbox (own "
        "temp directory, no access to this project's files or secrets, "
        "network access individually validated per-connection) and return "
        "its stdout/stderr. Use this to test the script you are building "
        "before returning it as your final answer. The script must be "
        "fully self-contained — print() whatever result you need to see."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python script to run"},
        },
        "required": ["code"],
    },
}


def make_sandboxed_run_script_handler(
    *,
    repo_path: str,
    timeout: int,
    allow_network: bool,
    max_memory_mb: int,
    max_output_file_mb: int,
    max_output_chars: int,
    max_total_disk_mb: int = 50,
    max_processes: int = 32,
) -> Callable[[dict[str, Any]], str]:
    def _handler(inp: dict[str, Any]) -> str:
        code = str(inp.get("code", ""))
        if not code.strip():
            return "[ERROR] code is required"
        result = run_sandboxed_python(
            code,
            repo_path=repo_path,
            timeout=timeout,
            allow_network=allow_network,
            max_memory_mb=max_memory_mb,
            max_output_file_mb=max_output_file_mb,
            max_output_chars=max_output_chars,
            max_total_disk_mb=max_total_disk_mb,
            max_processes=max_processes,
        )
        return str(result["output"])

    return _handler

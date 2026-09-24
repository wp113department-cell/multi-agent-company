"""Real interactive PTY terminal — Q12 (2026-09-24, GRIDIRON_PARTIAL "Real
interactive PTY terminal").

Real gap this closes: every existing bash-shaped tool (app.tools.execution.
bash, app.policy.sandbox.run_sandboxed) is request/response — a caller sends
one full command and gets back one full (or, since T2-B9/#12, incrementally
streamed) result. None of them give a human a real shell: no stdin, no
Ctrl+C, no window resize, no persistent interactive session a human can type
into over multiple round trips.

PtySession closes that gap with a genuine POSIX pseudo-terminal (Python's
stdlib `pty` module — no new dependency): `pty.openpty()` allocates a real
master/slave pty pair, and `subprocess.Popen` execs a sandboxed
`docker run -it` with the slave side wired to the child's stdin/stdout/
stderr (mirroring app.policy.sandbox's own security flags: `--rm`,
`--read-only` root with a size-capped tmpfs `/tmp`, resource caps, non-root
host UID/GID, no docker.sock). `preexec_fn` makes the child a session leader
(`os.setsid()`) and its slave fd its controlling terminal (`TIOCSCTTY`) —
the same setup `pty.fork()` itself performs internally, but through
`subprocess`'s `_posixsubprocess` C implementation rather than a raw
`os.fork()`.

Deliberately NOT `pty.fork()`: `pty.fork()` is a raw `fork()` of the calling
process, and CPython (3.12+) itself now emits a DeprecationWarning that
forking a multi-threaded process risks the child deadlocking if another
thread held a lock (allocator, import, logging, ...) at the moment of the
fork — a real, live hazard here, not theoretical, since this class is
constructed from FastAPI/uvicorn request-handling code, which is always
multi-threaded (asyncio's own thread-pool executor alone guarantees it).
`subprocess.Popen`'s fork+exec is specifically engineered by `_posixsubprocess`
to run `preexec_fn` safely across that same fork boundary — the standard,
production-proven way real web-terminal tools (e.g. Jupyter's `terminado`)
solve exactly this problem. Because the parent process holds the pty's
MASTER file descriptor, it can:
  - read() whatever the shell prints, as it prints it (real streaming, not
    request/response)
  - write() arbitrary bytes as if a human typed them, including a real
    Ctrl+C interrupt (the ASCII ETX/INTR byte 0x03 — the same byte a real
    terminal driver sends when a human presses Ctrl+C, so this interrupts
    the container's foreground process exactly the way a real terminal
    would, no signal juggling required)
  - resize the pty via `TIOCSWINSZ` — the kernel then delivers a real
    SIGWINCH to the pty's foreground process group; `docker run -it`'s own
    CLI (attached to that same pty as ITS controlling terminal, since it was
    exec'd directly into the forked child) already watches for that and
    forwards the resize into the container over the Docker API, so a
    terminal resize genuinely reaches the shell running inside the sandbox

Never bypasses the existing sandbox: the only difference from
app.policy.sandbox.run_sandboxed()'s own `docker run` invocation is `-it`
(interactive + a tty) in place of `--rm` alone, plus `--init` (see
app.fleet.process_manager._build_sandboxed_argv's own docstring for why
`--init` is required for signals/resize to reach a child process rather than
stopping at the container's own PID 1). Every containment flag
(`--read-only`, `--tmpfs`, `--memory`, `--pids-limit`, `--cpus`, `--user`,
the single `cwd` bind mount and nothing else of the host) is identical.

Live-verified (not just implemented) before this module was written: a
manual `pty.openpty()` + `subprocess.Popen` + `docker run -it`
proof-of-concept produced a real bash prompt, real `echo`/`pwd` round trips,
and a real Ctrl+C that visibly interrupted a running `sleep 30` (the shell
printed `^C` and returned to its prompt) — see this module's own test file
for the same proof, automated.
"""

from __future__ import annotations

import fcntl
import logging
import os
import pty
import select
import signal
import struct
import subprocess
import termios
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Matches app.fleet.bg_process_registry._CONTAINER_NAME_RE's own
# "gridiron-bg-" pattern in shape — a distinct "gridiron-pty-" prefix keeps
# `docker ps` output (and that registry's own name-validation regex, which
# this module's container names must also satisfy to be durably registered)
# able to tell a PTY session apart from a run_background job at a glance.
CONTAINER_NAME_PREFIX = "gridiron-pty-"


class PtySessionUnavailableError(RuntimeError):
    """Raised when a PTY session cannot be started at all (Docker
    unreachable) — mirrors app.policy.sandbox.SandboxUnavailableError's own
    fail-closed contract: never silently falls back to an unsandboxed host
    shell."""


def _build_pty_argv(
    cwd: str, container_name: str, image: str, network: str
) -> list[str]:
    """Real Docker-sandbox argv for an interactive PTY session — mirrors
    app.policy.sandbox.run_sandboxed()'s own security flags exactly (see
    that module's docstring for the empirical reasoning behind each one),
    with two deliberate differences: `-it` (a real tty is required for an
    interactive shell) in place of a plain foreground run, and `--init` (see
    app.fleet.process_manager._build_sandboxed_argv's own docstring — without
    it, a shell running as the container's PID 1 does not forward SIGWINCH/
    signals to the processes running inside it, verified empirically there
    for TERM and equally true for the resize signal this module relies on).

    Bind-mounts `cwd` at its own path (matching process_manager's own
    `_build_sandboxed_argv`, not run_sandboxed's fixed `/workspace`) so a
    human typing absolute paths under the real repo path sees exactly the
    paths they expect, with an identical security posture — still only
    `cwd` and nothing else of the host is exposed.
    """
    return [
        "docker",
        "run",
        "--rm",
        "-it",
        "--init",
        "--name",
        container_name,
        f"--network={network}",
        "--memory=1g",
        "--pids-limit=512",
        "--cpus=1.0",
        "--read-only",
        "--tmpfs",
        "/tmp:size=100m,mode=1777",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "-v",
        f"{cwd}:{cwd}:rw",
        "-w",
        cwd,
        image,
        "bash",
    ]


def _make_controlling_tty() -> None:  # pragma: no cover — runs in the forked child only
    """`subprocess.Popen`'s own `preexec_fn` hook — called by
    `_posixsubprocess` in the child, after fork, after stdin/stdout/stderr
    have already been dup2'd onto fds 0/1/2 (the slave pty), immediately
    before exec. `os.setsid()` makes this process a new session leader (also
    required for `docker run`'s own child processes inside the container to
    receive SIGWINCH/signals correctly — see `_build_pty_argv`'s docstring
    on `--init`); `TIOCSCTTY` on fd 0 (the slave, already in place) then
    makes that pty this session's controlling terminal — the exact two
    steps `pty.fork()` performs internally via a raw `fork()`, done here
    instead through `subprocess`'s async-signal-safe fork+exec path (see
    this module's own docstring for why that distinction is a real
    production concern, not a style choice)."""
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


@dataclass
class PtySession:
    """One real, interactive, sandboxed shell session backed by a genuine
    POSIX pty. Not thread-safe by itself — callers (the WebSocket endpoint)
    serialize access to a single session's read/write/resize from one
    asyncio task each, matching how a single real terminal has exactly one
    reader and one writer.
    """

    cwd: str
    image: str
    network: str
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    container_name: str = field(init=False, default="")
    pid: int = field(init=False, default=0)
    master_fd: int = field(init=False, default=-1)
    started_at: float = field(init=False, default=0.0)
    _proc: subprocess.Popen[bytes] | None = field(init=False, default=None, repr=False)
    _closed: bool = field(init=False, default=False)

    def start(self) -> None:
        from app.policy.sandbox import _docker_available

        if not _docker_available():
            raise PtySessionUnavailableError(
                "Docker is not available in this environment — an "
                "interactive PTY session cannot be started. Refusing to "
                "fall back to an unsandboxed host shell."
            )
        self.container_name = f"{CONTAINER_NAME_PREFIX}{uuid.uuid4().hex[:12]}"
        argv = _build_pty_argv(self.cwd, self.container_name, self.image, self.network)

        master_fd, slave_fd = pty.openpty()
        try:
            self._proc = subprocess.Popen(
                argv,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                preexec_fn=_make_controlling_tty,
                close_fds=True,
            )
        finally:
            # The child holds its own dup of the slave (via stdin/stdout/
            # stderr) — the parent must close its own reference too, or the
            # pty never sees EOF (master reads would hang forever waiting
            # for a reference the parent itself is still holding) once the
            # child actually exits.
            os.close(slave_fd)

        self.pid = self._proc.pid
        self.master_fd = master_fd
        self.started_at = time.time()
        self.resize(24, 80)

        from app.fleet import bg_process_registry

        bg_process_registry.register(
            self.pid,
            "[interactive pty session]",
            self.cwd,
            container=self.container_name,
        )

    def read(self, timeout: float = 0.2) -> bytes | None:
        """Returns new bytes if any arrived within `timeout`, b"" if the
        pty closed (the shell/container exited), or None if nothing arrived
        yet (still alive, just quiet) — three distinct outcomes a caller
        needs to tell apart, unlike a plain empty-bytes-means-EOF read."""
        if self.master_fd < 0:
            return b""
        try:
            ready, _, _ = select.select([self.master_fd], [], [], timeout)
        except OSError:
            return b""
        if not ready:
            return None
        try:
            data = os.read(self.master_fd, 65536)
        except OSError:
            return b""
        return data if data else b""

    def write(self, data: bytes) -> None:
        if self.master_fd < 0:
            return
        try:
            os.write(self.master_fd, data)
        except OSError:
            logger.debug(
                "PtySession %s: write failed (session likely closing)",
                self.session_id,
                exc_info=True,
            )

    def send_ctrl_c(self) -> None:
        """The real INTR byte (0x03) — exactly what a terminal driver sends
        when a human presses Ctrl+C on a real keyboard, so this interrupts
        whatever is running in the foreground the same way a real terminal
        would, with no separate signal-delivery mechanism needed."""
        self.write(b"\x03")

    def resize(self, rows: int, cols: int) -> None:
        if self.master_fd < 0:
            return
        rows = max(1, min(rows, 999))
        cols = max(1, min(cols, 999))
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            # The kernel's own automatic SIGWINCH delivery on a winsize
            # change was verified live to be unreliable here (docker run's
            # own foreground process group did not always react to the
            # ioctl alone) — explicitly signalling the pty's foreground
            # process group is the same technique established pty wrapper
            # libraries (e.g. ptyprocess) use, and was verified live to
            # make `docker run -it` reliably re-read the new size and
            # forward it into the container.
            fg_pgrp = os.tcgetpgrp(self.master_fd)
            os.killpg(fg_pgrp, signal.SIGWINCH)
        except OSError:
            logger.debug(
                "PtySession %s: resize failed (session likely closing)",
                self.session_id,
                exc_info=True,
            )

    def alive(self) -> bool:
        if self._proc is None:
            return False
        return self._proc.poll() is None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        confirmed_dead = True
        if self.container_name:
            # A session closed within milliseconds of opening can race
            # with `docker run`'s own container creation — live-verified:
            # a single `docker kill` attempt can genuinely observe "No
            # such container" for one that does not exist YET, not one
            # that already exited, and then goes on to actually start and
            # run indefinitely with nothing left tracking it. Retrying for
            # a few seconds — or stopping early once the docker CLI client
            # itself has exited on its own, meaning there is nothing left
            # to kill — closes that window.
            confirmed_dead = False
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    result = subprocess.run(
                        ["docker", "kill", self.container_name],
                        capture_output=True,
                        timeout=15,
                    )
                except Exception:
                    logger.debug(
                        "PtySession %s: docker kill of %s raised",
                        self.session_id,
                        self.container_name,
                        exc_info=True,
                    )
                    break
                if result.returncode == 0:
                    confirmed_dead = True
                    break
                if self._proc is not None and self._proc.poll() is not None:
                    confirmed_dead = True  # client already exited on its own
                    break
                time.sleep(0.3)
            if not confirmed_dead:
                logger.warning(
                    "PtySession %s: could not confirm container %s was "
                    "killed after retrying for 5s — it may have leaked; "
                    "left registered in bg_process_registry so the "
                    "startup/liveness sweep can still catch it",
                    self.session_id,
                    self.container_name,
                )
        if self.master_fd >= 0:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = -1
        if self._proc is not None:
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5)
        if confirmed_dead:
            from app.fleet import bg_process_registry

            bg_process_registry.unregister(self.pid)

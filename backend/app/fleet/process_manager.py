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

import collections
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


# ---------------------------------------------------------------------------
# Continuous output draining (verification batch B1, items #15/#16/#23).
#
# Proved live: spawn() attached stdout/stderr PIPEs that nothing read until an
# agent happened to call read_output (and that read at most 8 KB per call). A
# background job printing more than the OS pipe buffer (~64 KB) — a verbose
# build, `npm run dev`, `pytest -v` — BLOCKED on write forever: a job that
# prints 1.5 MB never reached the `touch DONE` after it. And read_output on an
# exited job returned only "has exited (code N)", discarding the job's whole
# output — including the stderr that explains a failure.
#
# Fix: two daemon reader threads per job drain both pipes continuously into a
# bounded, thread-safe buffer (oldest lines dropped and counted, never
# unbounded memory), and read_output returns what is unread — including the
# tail after the process has exited.
# ---------------------------------------------------------------------------

_MAX_BUFFERED_LINES = 5000
_MAX_LINE_CHARS = 4000
_TAIL_WAIT_SECONDS = 1.0


class _OutputBuffer:
    def __init__(self, readers: int) -> None:
        self._lines: collections.deque[str] = collections.deque()
        self._dropped = 0
        self._open_readers = readers
        self._cond = threading.Condition()

    def add(self, line: str) -> None:
        with self._cond:
            if len(self._lines) >= _MAX_BUFFERED_LINES:
                self._lines.popleft()
                self._dropped += 1
            self._lines.append(line)

    def reader_done(self) -> None:
        with self._cond:
            self._open_readers -= 1
            self._cond.notify_all()

    def wait_closed(self, timeout: float) -> None:
        """Block until both pipes hit EOF (or `timeout`) — used after the
        process exits so its final output is not missed. A grandchild that
        inherited the pipe can keep it open; the timeout bounds that."""
        with self._cond:
            self._cond.wait_for(lambda: self._open_readers <= 0, timeout=timeout)

    def drain(self) -> tuple[list[str], int]:
        with self._cond:
            lines = list(self._lines)
            dropped = self._dropped
            self._lines.clear()
            self._dropped = 0
            return lines, dropped


def _drain_stream(stream: Any, buf: _OutputBuffer) -> None:
    try:
        while True:
            # readline(size) bounds memory even for a job that prints one
            # enormous line with no newline.
            chunk = stream.readline(_MAX_LINE_CHARS)
            if not chunk:
                break
            buf.add(chunk.rstrip("\r\n"))
    except Exception:  # closed underneath us at kill/exit — nothing left to read
        pass
    finally:
        buf.reader_done()


def _start_output_drain(proc: "subprocess.Popen[str]") -> None:
    streams = [st for st in (proc.stdout, proc.stderr) if st is not None]
    buf = _OutputBuffer(readers=len(streams))
    for st in streams:
        threading.Thread(target=_drain_stream, args=(st, buf), daemon=True).start()
    setattr(proc, "_gridiron_output", buf)


def _build_sandboxed_argv(command: str, cwd: str, container_name: str) -> list[str]:
    """Real Docker-sandbox argv for a background command — mirrors
    app.policy.sandbox.run_sandboxed()'s own security flags (fresh --rm
    container, cwd bind-mounted read-write at /workspace and nothing else
    of the host visible, no docker.sock, real cgroup memory/pids/cpu caps,
    read-only rootfs with a size-capped tmpfs /tmp, non-root host UID/GID)
    — see that module's docstring for the full reasoning behind each flag,
    not re-derived here.

    tool_enhance.md productionization pass, tool #58 (2026-08-20) — unlike
    run_sandboxed() (synchronous, `subprocess.run` + blocking `docker run`),
    this returns argv for a FOREGROUND (non-detached) `docker run`, so the
    caller can wrap it in a normal Popen: `docker run` without `-d` blocks
    for the container's entire lifetime, streaming its real stdout/stderr
    through the client process's own pipes — proved live (a real multi-line,
    multi-second script's output arrived via Popen.communicate() exactly as
    if run unsandboxed) — so kill_process/read_output/list_background_
    processes need zero changes: they already only ever look at a tracked
    Popen's `.pid`/`.poll()`/`.stdout`/`.stderr`, all of which remain valid
    and correctly reflect the sandboxed container's real state.

    `--init` is required, not optional — proved live: without it, `docker
    kill --signal=TERM` on a `sh -c "sleep 300"` container did NOT stop it
    (a well-known Docker gotcha: a shell running as the container's PID 1
    does not forward signals to its own child processes by default). With
    `--init` (a lightweight init process as real PID 1, forwarding signals
    correctly), the identical TERM test stopped the container within
    seconds, exit code 143. Without this, kill_process's TERM/INT signals
    would silently do nothing against a sandboxed background process.

    Bind-mounts `cwd` at its OWN path inside the container (`-v cwd:cwd -w
    cwd`), deliberately diverging from run_sandboxed()'s fixed `/workspace`
    mount point — proved live as a real regression, not a style choice: a
    pre-existing test (AUDIT_Q_BATCH01's wait_for_pids dependency test,
    predating this turn) ran `touch {tmp_path}/marker` — an ABSOLUTE host
    path — and failed once sandboxing was enabled, because inside a
    `/workspace`-mounted container that same absolute path resolves to
    nothing (it's created in the container's own ephemeral filesystem,
    invisible to the host, and vanishes with the container). Mounting at
    the identical path keeps absolute-path commands referencing files
    under `cwd` working exactly as before, with an identical security
    posture — still only `cwd` and nothing else of the host is exposed.
    """
    from app.config import get_settings
    from app.policy.docker_host import mount_args

    settings = get_settings()
    return [
        "docker",
        "run",
        "--rm",
        "--init",
        "--name",
        container_name,
        f"--network={settings.bash_sandbox_network}",
        "--memory=1g",
        "--pids-limit=512",
        "--cpus=1.0",
        "--read-only",
        "--tmpfs",
        "/tmp:size=100m,mode=1777",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        *mount_args(cwd, cwd, "rw"),
        "-w",
        cwd,
        settings.bash_sandbox_image,
        "sh",
        "-c",
        command,
    ]


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

    tool_enhance.md productionization pass, tool #58 (2026-08-20) — real,
    severe finding, raised to the user before fixing (AskUserQuestion)
    given the scope: `command` was run via `subprocess.Popen(command,
    shell=True, cwd=cwd)` with ZERO sandboxing — fully unrestricted host
    shell execution, the same unsandboxed state `bash` (tool #1) was in
    before its own real Docker-sandboxing remediation. Proved live: a real
    payload wrote a marker file to an arbitrary host path with no
    restriction whatsoever. User chose: apply the same real Docker
    sandboxing tool #1 built for bash. Now routes through
    `_build_sandboxed_argv()` (see its own docstring for the real
    empirical findings that shaped it) when `Settings.bash_sandbox_enabled`
    (the same flag `bash` uses, default True) — fails closed with a real
    `[SANDBOX UNAVAILABLE]` result if Docker itself isn't reachable, never
    silently falling back to unsandboxed host execution (matching
    app.policy.sandbox.run_sandboxed()'s own established fail-closed
    contract). Falls back to the original raw host execution ONLY when an
    operator has explicitly set `BASH_SANDBOX_ENABLED=false`.

    wait_for_pids (AUDIT_Q_BATCH01 §58 "Task dependency handling between
    terminal jobs" — previously NO code expressed one background job
    depending on another's completion): when given, the real command is
    prefixed with a portable `kill -0`-polling wait loop for each
    dependency PID, so exactly one real OS process (and PID) represents the
    whole dependency-wait-then-run lifecycle — the tool call itself still
    returns immediately, matching every other run_background call's
    existing fire-and-forget contract, and the returned PID can be
    killed/read like any other background process while it waits. This
    wait-loop step deliberately stays OUTSIDE the sandboxed container (it
    only ever runs `kill -0 <host-integer-pid>`/`sleep`, both fixed,
    non-LLM-controlled shell fragments, never the real command) — a
    container has its own PID namespace and could never see a host PID to
    poll in the first place, sandboxed or not.

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
    from app.config import get_settings

    settings = get_settings()
    container_name: str | None = None
    real_command = command

    if settings.bash_sandbox_enabled:
        from app.policy.sandbox import _docker_available

        if not _docker_available():
            return (
                "[SANDBOX UNAVAILABLE] Docker is not available in this "
                "environment — sandboxed background execution cannot "
                "proceed. Refusing to fall back to unsandboxed host "
                "execution. Set BASH_SANDBOX_ENABLED=false to explicitly "
                "opt out of sandboxing instead."
            )
        import shlex
        import uuid

        container_name = f"gridiron-bg-{uuid.uuid4().hex[:12]}"
        from app.policy.docker_host import SharedFolderError

        try:
            docker_argv = _build_sandboxed_argv(real_command, cwd, container_name)
        except SharedFolderError as exc:
            return f"[SANDBOX UNAVAILABLE] {exc}"
        run_command = shlex.join(docker_argv)
    else:
        run_command = real_command

    if wait_for_pids:
        for dep_pid in wait_for_pids:
            dep_proc = procs.get(dep_pid)
            if dep_proc is not None:
                threading.Thread(target=dep_proc.wait, daemon=True).start()
        wait_clause = "".join(
            f"while kill -0 {int(dep_pid)} 2>/dev/null; do sleep 1; done; "
            for dep_pid in wait_for_pids
        )
        run_command = f"{wait_clause}{run_command}"
    try:
        proc = subprocess.Popen(
            run_command,
            shell=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            # tool_enhance.md productionization pass, tool #58 (2026-08-20)
            # — real, pre-existing, retroactive finding, uncovered while
            # verifying this turn's sandboxing fix, not introduced by it:
            # `shell=True` makes `proc.pid` the WRAPPING /bin/sh process,
            # not the real command — proved live with a plain `sleep 300`.
            # `start_new_session=True` puts that shell (and everything it
            # spawns, sandboxed or not) in its own new process group,
            # required for kill()'s companion fix (os.killpg) below to be
            # able to signal the whole tree without also reaching the
            # caller's own process group.
            start_new_session=True,
        )
    except Exception as e:
        return f"[ERROR] {e}"
    _start_output_drain(proc)
    procs[proc.pid] = proc
    # Remembered so kill()/session-close/startup-sweep can stop the CONTAINER too.
    setattr(proc, "_gridiron_container", container_name)
    # Gap-closure Day 23 (Stage 1.3, answers.md) — durably persisted so a
    # crash/restart before kill_process ever runs still leaves a trail
    # sweep_orphaned_processes() can find and clean up at the next startup.
    bg_process_registry.register(proc.pid, real_command, cwd, container=container_name)
    if wait_for_pids:
        return (
            f"Started background process PID {proc.pid} (waiting on "
            f"PID(s) {wait_for_pids} to exit before running): {real_command[:80]}"
        )
    return f"Started background process PID {proc.pid}: {real_command[:80]}"


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

    **Second retroactive correction, tool #58 (2026-08-20)**: uncovered
    while verifying tool #58's own (unrelated) sandboxing fix, not
    introduced by it — a real, severe, pre-existing bug present since
    this function (and both of its original, independently-maintained
    predecessors) was written. `spawn()` always used `shell=True`, which
    makes the tracked PID the WRAPPING `/bin/sh -c <command>` process, not
    the real command — `sig_name` was being sent to that shell wrapper via
    plain `os.kill()`, not to its child. Proved live with a plain
    `sleep 300` background command: the shell wrapper was correctly
    reaped (confirmed via `.wait()`, returncode -15), but the real `sleep`
    process was left running, orphaned, completely untracked —
    `kill_process` returned a false "Sent TERM to PID X" success message
    while the actual background command kept running indefinitely. Fixed
    by signaling the whole process GROUP (`os.killpg`) instead of the
    single PID — `spawn()`'s companion fix (`start_new_session=True`)
    ensures each background command's shell (and everything it spawns,
    including a sandboxed `docker run` and the container inside it) gets
    its own process group, so `killpg` reaches the real command without
    also reaching the caller's (backend server's) own process group.
    """
    if pid not in procs:
        return (
            f"[ERROR] PID {pid} was not started by run_background in this "
            "session — kill_process can only stop processes this session "
            "itself spawned."
        )
    sig = _SIGNAL_MAP.get(sig_name, signal.SIGTERM)
    container = getattr(procs.get(pid), "_gridiron_container", None)
    procs.pop(pid, None)
    bg_process_registry.unregister(pid)
    try:
        alive = bg_process_registry.signal_process(pid, sig)
        # Deliver the same signal straight to the sandbox container as well:
        # a SIGKILLed `docker run` client cannot forward it, so KILL used to
        # leave the container running (proved live).
        bg_process_registry.kill_container(
            container, sig_name if sig_name in _SIGNAL_MAP else "TERM"
        )
        if not alive and not container:
            return f"[ERROR] No process with PID {pid}"
        return f"Sent {sig_name} to PID {pid}"
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

    buf: _OutputBuffer | None = getattr(proc, "_gridiron_output", None)
    if buf is not None:
        exited = proc.poll() is not None
        if exited:
            buf.wait_closed(_TAIL_WAIT_SECONDS)  # catch the job's final output
        lines, dropped = buf.drain()
        max_lines = max(1, max_lines)
        omitted = max(0, len(lines) - max_lines)
        notes: list[str] = []
        if dropped:
            notes.append(
                f"[{dropped} earlier line(s) dropped: output buffer full — "
                "read_output more often or redirect the job's output to a file]"
            )
        if omitted:
            notes.append(f"[{omitted} earlier unread line(s) not shown]")
        body = "\n".join(notes + lines[-max_lines:])
        if exited:
            status = f"Process {pid} has exited (code {proc.returncode})"
            return f"{body}\n{status}" if body else status
        return body if body else f"(no output yet from PID {pid})"

    # Not started by spawn() (no drain thread owns its pipes): legacy
    # non-blocking chunk read, unchanged.
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

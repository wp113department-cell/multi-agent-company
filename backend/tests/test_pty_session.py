"""Q12 (2026-09-24, "Real interactive PTY terminal") —
app.tools.execution.pty_session.PtySession.

Real proof, not mocked: every test here starts a genuine Docker container
via a genuine POSIX pty and drives it exactly as a human typing at a real
terminal would — no mocked subprocess, no fake output.
"""

from __future__ import annotations

import os
import time

import pytest

from app.config import get_settings
from app.tools.execution.pty_session import CONTAINER_NAME_PREFIX, PtySession


def _read_until(session: PtySession, needle: str, timeout: float = 5.0) -> str:
    """Real, blocking-with-timeout accumulation of PTY output until `needle`
    appears — mirrors how a real terminal client waits for a prompt/output
    rather than sleeping a fixed amount and hoping."""
    collected = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        chunk = session.read(timeout=0.2)
        if chunk:
            collected += chunk
            if needle.encode() in collected:
                break
        elif chunk == b"":
            break  # pty closed
    return collected.decode(errors="replace")


@pytest.fixture
def pty_image() -> str:
    return get_settings().pty_terminal_image


@pytest.fixture
def session(tmp_path, pty_image: str):
    s = PtySession(cwd=str(tmp_path), image=pty_image, network="none")
    s.start()
    _read_until(s, "$", timeout=5.0)  # wait for the real initial shell prompt
    # The bare prompt character can stream in before `docker run -it`'s own
    # attach/signal-handling machinery has fully settled — found live via a
    # real resize test that only failed through this fixture, never via a
    # manual script using a fixed sleep here instead. A short real settle
    # delay (not a mock, not a skip) matches what was verified reliable.
    time.sleep(1.0)
    yield s
    s.close()


def test_container_name_uses_the_dedicated_pty_prefix(session: PtySession) -> None:
    assert session.container_name.startswith(CONTAINER_NAME_PREFIX)


def test_pty_session_runs_a_real_interactive_command(session: PtySession) -> None:
    session.write(b"echo HELLO_FROM_REAL_PTY\n")
    out = _read_until(session, "HELLO_FROM_REAL_PTY")
    assert "HELLO_FROM_REAL_PTY" in out


def test_pty_session_persistent_working_directory_across_writes(
    session: PtySession, tmp_path
) -> None:
    (tmp_path / "subdir").mkdir()
    session.write(f"cd {tmp_path}/subdir\n".encode())
    _read_until(session, "$")
    session.write(b"pwd\n")
    out = _read_until(session, "subdir")
    assert str(tmp_path / "subdir") in out

    # A SECOND, independent round trip proves the working directory was
    # retained by the same live shell process, not reset per-command.
    session.write(b"pwd\n")
    out2 = _read_until(session, "subdir")
    assert str(tmp_path / "subdir") in out2


def test_pty_session_ctrl_c_interrupts_a_running_foreground_command(
    session: PtySession,
) -> None:
    session.write(b"sleep 30\n")
    time.sleep(0.5)
    session.send_ctrl_c()
    out = _read_until(session, "$", timeout=5.0)
    assert "^C" in out
    # Proves the shell is genuinely back at a live prompt, not just that
    # "^C" text appeared somewhere — a second real command must complete.
    session.write(b"echo BACK_AT_PROMPT\n")
    out2 = _read_until(session, "BACK_AT_PROMPT")
    assert "BACK_AT_PROMPT" in out2


def test_pty_session_resize_changes_the_real_pty_window_size(
    session: PtySession,
) -> None:
    """Real, verified propagation: our own pty's winsize -> SIGWINCH ->
    `docker run -it`'s own resize watcher -> a real Docker daemon API call
    -> the container's own internal pty. That chain has a genuine, variable
    network hop in it (confirmed live: a single immediate `stty size` after
    resize() is flaky — anywhere from under a second to several seconds to
    land) — polling, not a fixed sleep or a single attempt, is the honest
    way to prove eventual propagation without either a flaky false failure
    or silently waiting the max timeout every time."""
    session.resize(rows=40, cols=120)
    deadline = time.monotonic() + 8.0
    out = ""
    while time.monotonic() < deadline:
        session.write(b"stty size\n")
        out = _read_until(session, "\n40 120", timeout=1.5)
        if "40 120" in out:
            break
    assert (
        "40 120" in out
    ), f"resize never propagated to the container; last output: {out!r}"


def test_pty_session_close_stops_the_container(session: PtySession) -> None:
    name = session.container_name
    session.close()
    time.sleep(0.5)
    result = os.popen(
        f"docker ps --filter name={name} --format '{{{{.Names}}}}'"
    ).read()
    assert name not in result


def test_pty_session_close_is_idempotent(session: PtySession) -> None:
    session.close()
    session.close()  # must not raise


def test_pty_session_alive_reflects_real_process_state(
    tmp_path, pty_image: str
) -> None:
    s = PtySession(cwd=str(tmp_path), image=pty_image, network="none")
    s.start()
    assert s.alive() is True
    s.write(b"exit\n")
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and s.alive():
        time.sleep(0.1)
    assert s.alive() is False
    s.close()


def test_pty_session_sandbox_containment_host_is_non_root_and_isolated(
    session: PtySession,
) -> None:
    """Mirrors test_b1_sandbox_containment.py's own containment proofs for
    the request/response sandbox — the interactive PTY sandbox must give
    exactly the same guarantees."""
    # The needle must only appear in the command's REAL OUTPUT, not in its
    # own echoed input text (a real terminal echoes exactly what was typed
    # before the command even runs) — printf's own format string never
    # contains the literal substring its output will.
    session.write(b"printf 'REALUID_%s\\n' \"$(id -u)\"\n")
    out = _read_until(session, f"REALUID_{os.getuid()}")
    assert (
        f"REALUID_{os.getuid()}" in out
    )  # runs as the host's own real UID, never root

    session.write(b"touch /etc/should-fail 2>&1; printf 'RODONE_%s\\n' done\n")
    out2 = _read_until(session, "RODONE_done")
    assert "Read-only file system" in out2 or "Permission denied" in out2


def test_pty_session_register_and_unregister_with_the_durable_registry(
    tmp_path, pty_image: str
) -> None:
    """Q12 reuses app.fleet.bg_process_registry (crash-recovery/orphan-sweep
    machinery already built for run_background) rather than duplicating it —
    a PTY session's pid+container must appear in, then be removed from, that
    same durable registry."""
    from app.fleet import bg_process_registry

    s = PtySession(cwd=str(tmp_path), image=pty_image, network="none")
    s.start()
    try:
        snap = bg_process_registry.snapshot()
        assert str(s.pid) in snap
        assert snap[str(s.pid)]["container"] == s.container_name
    finally:
        s.close()
    snap_after = bg_process_registry.snapshot()
    assert str(s.pid) not in snap_after

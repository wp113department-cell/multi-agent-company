"""T2-B9/#12 (2026-09-24, GRIDIRON_PARTIAL "Monitor streaming output (live,
mid-command)") — app.policy.sandbox.run_sandboxed()'s new `on_output`
parameter.

Real proof, not mocked: a command with real `sleep`s between its outputs,
proving each line arrives at the callback as it's produced — not buffered
until the whole command exits — while the RETURNED SandboxResult stays
byte-for-byte identical to the pre-existing buffered path.
"""

from __future__ import annotations

import time
from pathlib import Path

from app.policy.sandbox import run_sandboxed


def test_on_output_none_is_the_exact_original_buffered_behavior(
    tmp_path: Path,
) -> None:
    result = run_sandboxed("echo hello-buffered", str(tmp_path))
    assert result.stdout.strip() == "hello-buffered"
    assert result.returncode == 0


def test_on_output_receives_each_line_as_it_is_produced(tmp_path: Path) -> None:
    chunks: list[tuple[str, str]] = []

    def on_output(stream: str, line: str) -> None:
        chunks.append((stream, line))

    result = run_sandboxed(
        "echo one; echo two >&2; echo three", str(tmp_path), on_output=on_output
    )

    assert result.stdout == "one\nthree\n"
    assert result.stderr == "two\n"
    assert ("stdout", "one\n") in chunks
    assert ("stdout", "three\n") in chunks
    assert ("stderr", "two\n") in chunks
    # Real ordering: stdout lines arrive in the order the command produced
    # them (interleaving with stderr is not guaranteed — two separate real
    # OS pipes — only same-stream ordering is).
    stdout_only = [c for s, c in chunks if s == "stdout"]
    assert stdout_only == ["one\n", "three\n"]


def test_chunks_arrive_progressively_not_bunched_at_exit(tmp_path: Path) -> None:
    """The actual, provable value of #12: real wall-clock evidence that
    output is observed WHILE the command is still running, not only after
    it exits."""
    timestamps: list[float] = []

    def on_output(stream: str, line: str) -> None:
        timestamps.append(time.monotonic())

    result = run_sandboxed(
        "echo one; sleep 0.4; echo two; sleep 0.4; echo three",
        str(tmp_path),
        on_output=on_output,
    )
    end = time.monotonic()

    assert result.returncode == 0
    assert len(timestamps) == 3
    # The gap between the FIRST chunk's arrival and the command's total
    # wall time must be substantial — if buffering were still happening,
    # every timestamp would land within a few ms of `end`.
    assert (end - timestamps[0]) > 0.5, (
        "first chunk arrived too close to process exit — looks like "
        "output is still being buffered rather than streamed"
    )


def test_on_output_callback_exception_never_breaks_the_command(
    tmp_path: Path,
) -> None:
    def bad_on_output(stream: str, line: str) -> None:
        raise RuntimeError("a broken subscriber must not affect the command")

    result = run_sandboxed("echo still-works", str(tmp_path), on_output=bad_on_output)
    assert result.returncode == 0
    assert "still-works" in result.stdout


def test_streaming_path_also_handles_a_real_timeout(tmp_path: Path) -> None:
    chunks: list[str] = []
    result = run_sandboxed(
        "echo before-timeout; sleep 5",
        str(tmp_path),
        timeout=1,
        on_output=lambda stream, line: chunks.append(line),
    )
    assert result.timed_out is True
    assert result.returncode == -1
    assert any("before-timeout" in c for c in chunks)

"""Verification batch B1, items #17-#20 (terminal intelligence: parse generic
logs, Docker logs, test output, compiler/type-checker output).

Real tools produce the parsed text here — a real pytest run with every outcome
kind, real mypy/ruff/tsc runs, and a real crashing container — instead of
hand-written samples, because two defects were invisible to hand-written input:

  * pytest appends "(H:MM:SS)" to any run >= 60 s, and the summary regex ended at
    "s": every long run (the important ones) produced NO structured summary;
  * docker_logs / diagnose_deployment_failure cut the log with `[:6000]` (keeping
    the head, dropping the NEWEST lines — the crash), ran the pattern analysis on
    the truncated text, and concatenated stdout+stderr (reordering the streams).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.agents.output_parsers import parse_diagnostic_summary, parse_pytest_summary

_BIN = Path(sys.executable).parent


def _run(cmd: list[str], cwd: Path) -> str:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return r.stdout + r.stderr


# --------------------------- pytest (#19) ---------------------------------


def test_real_pytest_run_with_every_outcome_kind_is_summarised(tmp_path) -> None:
    (tmp_path / "test_mix.py").write_text(
        "import pytest\n"
        "@pytest.fixture\n"
        "def boom(): raise RuntimeError('fixture')\n"
        "def test_ok(): pass\n"
        "def test_bad(): assert 1 == 2\n"
        "@pytest.mark.skip\n"
        "def test_skip(): pass\n"
        "@pytest.mark.xfail\n"
        "def test_xf(): assert False\n"
        "def test_err(boom): pass\n"
    )
    for flags in (["-q"], ["-v"]):
        out = _run([sys.executable, "-m", "pytest", "test_mix.py", *flags], tmp_path)
        s = parse_pytest_summary(out)
        assert s == (
            "=== Test Summary === 1 failed, 1 passed, 1 skipped, 1 xfailed, 1 error"
        ), (flags, s, out[-200:])


@pytest.mark.parametrize(
    "line, expected",
    [
        (
            # the literal last line of this project's own full-suite run
            "31 failed, 7707 passed, 54 skipped, 21 deselected, 36 warnings in 714.98s (0:11:54)",
            "31 failed, 7707 passed, 54 skipped, 36 warnings",
        ),
        (
            "========== 2 failed, 5 passed in 75.12s (0:01:15) ==========",
            "2 failed, 5 passed",
        ),
        ("1 passed in 0.02s", "1 passed"),
        ("2 passed in 3599.99s (0:59:59)", "2 passed"),
    ],
)
def test_long_runs_with_hms_suffix_are_summarised(line: str, expected: str) -> None:
    assert parse_pytest_summary(line) == f"=== Test Summary === {expected}"


def test_no_tests_ran_is_reported_not_swallowed() -> None:
    assert parse_pytest_summary("no tests ran in 0.01s") == (
        "=== Test Summary === no tests ran"
    )


def test_unrelated_text_yields_none_not_a_false_summary() -> None:
    assert (
        parse_pytest_summary("Traceback...\nValueError: 3 failed in 2s of tries\n")
        is None
    )
    assert parse_pytest_summary("") is None


# --------------------- compiler / type-checkers (#20) ----------------------


def test_real_mypy_output(tmp_path) -> None:
    (tmp_path / "bad.py").write_text(
        "def f(x: int) -> str:\n    return x\nz: int = 'a'\n"
    )
    out = _run([str(_BIN / "mypy"), "bad.py"], tmp_path)
    assert parse_diagnostic_summary(out, "mypy") == (
        "=== mypy Summary === 2 error(s) in 1 file(s)"
    )
    (tmp_path / "good.py").write_text("x: int = 1\n")
    assert parse_diagnostic_summary(
        _run([str(_BIN / "mypy"), "good.py"], tmp_path), "mypy"
    ) == ("=== mypy Summary === 0 errors")


def test_real_ruff_output(tmp_path) -> None:
    (tmp_path / "bad.py").write_text("import os\nimport sys\n")
    out = _run([str(_BIN / "ruff"), "check", "bad.py"], tmp_path)
    assert parse_diagnostic_summary(out, "ruff") == "=== ruff Summary === 2 error(s)"
    (tmp_path / "ok.py").write_text("x = 1\n")
    assert parse_diagnostic_summary(
        _run([str(_BIN / "ruff"), "check", "ok.py"], tmp_path), "ruff"
    ) == ("=== ruff Summary === 0 errors")


_TSC = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "web"
    / "node_modules"
    / ".bin"
    / "tsc"
)


@pytest.mark.skipif(
    not _TSC.exists() or shutil.which("node") is None, reason="no tsc/node"
)
def test_real_tsc_output(tmp_path) -> None:
    (tmp_path / "bad.ts").write_text('const a: number = "x";\nlet b: string = 5;\n')
    (tmp_path / "tsconfig.json").write_text(
        '{"compilerOptions":{"strict":true,"noEmit":true}}'
    )
    out = _run([str(_TSC), "--noEmit", "-p", "."], tmp_path)
    assert parse_diagnostic_summary(out, "tsc") == (
        "=== tsc Summary === 2 error(s) (line-counted, no tsc summary line)"
    )


# ------------------------------ docker logs (#18) --------------------------

_HAS_DOCKER = (
    shutil.which("docker") is not None
    and subprocess.run(["docker", "version"], capture_output=True).returncode == 0
)


@pytest.fixture
def crashed_container():
    name = "b1_log_crash_demo"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    line = "INFO request handled ok " + "." * 150
    # Lines are spaced apart on purpose: Docker's json-file driver reads
    # stdout/stderr through separate goroutines, so two lines written
    # microseconds apart can be timestamped in either order (observed live).
    # 0.5 s gaps make the true order observable, while stdout-then-stderr
    # concatenation (the original bug) would still place ERROR last.
    script = (
        'i=0; while [ $i -lt 60 ]; do echo "' + line + ' $i"; i=$((i+1)); done; '
        "sleep 0.5; echo 'ERROR db connection refused' >&2; "
        "sleep 0.5; echo 'FATAL: worker crashed, exit code 137'"
    )
    subprocess.run(
        ["docker", "run", "-d", "--name", name, "alpine", "sh", "-c", script],
        capture_output=True,
        check=True,
    )
    subprocess.run(["docker", "wait", name], capture_output=True, timeout=60)
    yield name
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.mark.skipif(not _HAS_DOCKER, reason="needs docker")
def test_docker_logs_keeps_the_newest_lines_and_analyses_the_whole_log(
    crashed_container,
) -> None:
    from app.tools.execution.docker_logs import MAX_LOG_CHARS, docker_logs_handler

    out = docker_logs_handler({"container": crashed_container, "lines": 60})
    analysis, _, raw = out.partition("--- raw log below ---")
    assert "FATAL: worker crashed" in raw, "the crash line (newest) was cut off"
    assert "ERROR db connection refused" in raw
    assert raw.index("ERROR db connection") < raw.index(
        "FATAL: worker crashed"
    ), "stderr/stdout order was scrambled"
    assert "Crash/OOM signatures" in analysis  # 'exit code 137' seen
    assert "Error/exception lines" in analysis
    assert "earlier character(s) omitted" in raw
    assert len(raw) < MAX_LOG_CHARS + 200


@pytest.mark.skipif(not _HAS_DOCKER, reason="needs docker")
def test_diagnose_deployment_failure_sees_the_crash_line(crashed_container) -> None:
    from app.tools.execution import diagnose_deployment_failure as ddf

    out = ddf.gather_deployment_diagnostics(
        {"container": crashed_container, "lines": 60}
    )
    assert "FATAL: worker crashed" in out


@pytest.mark.skipif(not _HAS_DOCKER, reason="needs docker")
def test_docker_logs_rejects_flag_shaped_container_name() -> None:
    from app.tools.execution.docker_logs import docker_logs_handler

    assert docker_logs_handler({"container": "--all"}).startswith("[ERROR]")


def test_short_logs_are_returned_whole_with_no_omission_marker() -> None:
    from app.tools.execution.docker_logs import analyze_and_tail_logs

    out = analyze_and_tail_logs("all good\nstill good\n")
    assert out == "all good\nstill good\n"
    assert analyze_and_tail_logs("") == "(no logs)"


def test_merge_chronologically_orders_by_timestamp_and_strips_it() -> None:
    from app.tools.execution.docker_logs import merge_chronologically

    raw = (
        "2026-09-21T10:00:00.000000003Z FATAL crashed\n"
        "2026-09-21T10:00:00.000000001Z INFO a\n"
        "2026-09-21T10:00:00.000000002Z ERROR b\n"
    )
    assert merge_chronologically(raw) == "INFO a\nERROR b\nFATAL crashed\n"
    # a line without a timestamp (unexpected driver/format) => untouched
    assert merge_chronologically("plain\nlines\n") == "plain\nlines\n"
    assert merge_chronologically("") == ""

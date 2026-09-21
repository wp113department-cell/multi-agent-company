"""Verification batch B1, item #9 (virtual-environment activation) and #7
(Linux/Ubuntu support).

Proved live: the activation snippet was `source .venv/bin/activate
2>/dev/null || true`, run through `subprocess.run(shell=True)` => /bin/sh, which
is DASH on Ubuntu/Debian. dash has no `source`, so the venv was silently NEVER
activated (both the error and the non-zero status were swallowed) — every
pytest/mypy/python-snippet tool ran against whatever interpreter happened to be
first on PATH instead of the target repo's own environment.

A naive `source` -> `.` swap is ALSO wrong: in dash `.` is a special builtin, so
`. missing || true` aborts the entire shell (exit 2) and the command never runs
in any repo that has no .venv. These tests run the real /bin/sh, so they catch
both failure modes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell snippet")


def _run(cmd: str) -> subprocess.CompletedProcess[str]:
    # exactly how the product runs these: shell=True => /bin/sh
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def _fake_venv(root: Path) -> None:
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "activate").write_text(
        f'export VENV_ACTIVATED=yes\nexport PATH="{bin_dir}:$PATH"\n'
    )


def test_snippet_really_activates_the_repo_venv(tmp_path) -> None:
    from app.agents.tools import _venv_activate_snippet

    _fake_venv(tmp_path)
    r = _run(
        f"cd {tmp_path} && {_venv_activate_snippet()} && "
        'echo "ACT=${VENV_ACTIVATED:-NO}"'
    )
    assert r.stdout.strip() == "ACT=yes", (r.stdout, r.stderr)


def test_snippet_degrades_safely_when_repo_has_no_venv(tmp_path) -> None:
    """The command after the snippet MUST still run (dash aborts on a bare
    `. missing`)."""
    from app.agents.tools import _venv_activate_snippet

    r = _run(f"cd {tmp_path} && {_venv_activate_snippet()} && echo still-ran")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert r.stdout.strip() == "still-ran"


def test_failed_cd_still_short_circuits_the_command(tmp_path) -> None:
    """Old chain `cd X && act || true && cmd` ran cmd even when cd failed."""
    from app.agents.tools import _venv_activate_snippet

    r = _run(
        f"cd {tmp_path}/does-not-exist 2>/dev/null && {_venv_activate_snippet()} "
        "&& echo SHOULD-NOT-RUN"
    )
    assert "SHOULD-NOT-RUN" not in r.stdout


def test_run_tests_handler_uses_the_target_repos_own_python(tmp_path) -> None:
    """End to end through the real tool: a repo-local interpreter earlier on
    PATH (via activation) must be what `python` resolves to."""
    from app.agents.tools import _venv_activate_snippet
    from app.tools.execution.run_tests import run_tests_handler

    _fake_venv(tmp_path)
    fake_python = tmp_path / ".venv" / "bin" / "python"
    fake_python.write_text('#!/bin/sh\necho REPO-VENV-PYTHON-RAN "$@"\n')
    fake_python.chmod(0o755)
    out = run_tests_handler(
        str(tmp_path), {"runner": "pytest"}, activate_snippet=_venv_activate_snippet()
    )
    assert "REPO-VENV-PYTHON-RAN" in out, out


def test_no_bashism_source_left_in_activation_code() -> None:
    """Static guard: no executable shell string in app/ may use `source`."""
    import re

    bad = []
    for p in Path(__file__).resolve().parent.parent.joinpath("app").rglob("*.py"):
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue  # comments describing the old bug are fine
            if re.search(r"""["'`]source\s+[.{/]""", line) or re.search(
                r"""f["']source\s""", line
            ):
                bad.append(f"{p.name}:{n}: {line.strip()}")
    assert not bad, bad

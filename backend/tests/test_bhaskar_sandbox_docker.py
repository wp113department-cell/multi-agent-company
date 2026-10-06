"""bhaskar_tool's Docker sandbox (audit 15, 2026-10-06).

The in-process sandbox's file guard is Python-level: `_io.FileIO` and
`ctypes` read backend/.env (API keys) straight past it. The Docker backend
mounts no host path at all. These run real containers (skipped without
Docker) and never print a secret — only whether one was reachable.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.agents.bhaskar_sandbox import run_sandboxed_python
from app.policy.sandbox import _docker_available

pytestmark = pytest.mark.skipif(not _docker_available(), reason="needs Docker")

_ENV = str(Path(__file__).resolve().parents[1] / ".env")


def _run(code: str, **kw: object) -> dict[str, object]:
    kw.setdefault("timeout", 8)
    return run_sandboxed_python(code, backend="docker", **kw)  # type: ignore[arg-type]


def test_a_normal_script_runs() -> None:
    r = _run("print(sum(range(10)))")
    assert r["success"] and "45" in str(r["output"])


@pytest.mark.parametrize(
    "reader",
    [
        "import _io\ndata = _io.FileIO(P).read().decode()",
        "import ctypes, os\nfd = ctypes.CDLL(None).open(P.encode(), 0)\n"
        "data = os.read(fd, 100000).decode() if fd >= 0 else ''",
    ],
    ids=["io-FileIO", "ctypes-libc"],
)
def test_host_secrets_are_unreachable_through_the_old_bypasses(reader: str) -> None:
    code = (
        f"P = {_ENV!r}\ntry:\n"
        + "".join(f"    {line}\n" for line in reader.splitlines())
        + "except Exception:\n    data = ''\nprint('LEAKED' if 'API_KEY' in data else 'NOT_REACHABLE')"
    )
    r = _run(code)
    assert "NOT_REACHABLE" in str(r["output"]), r["output"]


def test_writes_never_reach_the_host(tmp_path: Path) -> None:
    target = tmp_path / "escaped"
    _run(f"import subprocess\nsubprocess.run(['touch', {str(target)!r}])")
    assert not target.exists()


def test_memory_limit_is_enforced_by_the_kernel() -> None:
    r = _run("x = bytearray(1024**3)\nprint('ALLOCATED')", max_memory_mb=256)
    assert not r["success"] and "ALLOCATED" not in str(r["output"])


def test_wall_clock_timeout() -> None:
    r = _run("while True: pass", timeout=3)
    assert not r["success"] and "timed out" in str(r["output"])


def test_disk_quota_is_hard() -> None:
    r = _run(
        "for i in range(100):\n    open(f'f{i}', 'wb').write(b'0' * 1024 * 1024)\nprint('WROTE')",
        max_total_disk_mb=20,
    )
    assert "WROTE" not in str(r["output"])


def test_network_can_be_switched_off_entirely() -> None:
    r = _run(
        "import socket\ntry:\n    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    print('CONNECTED')\nexcept Exception:\n    print('NO_NETWORK')",
        allow_network=False,
    )
    assert "NO_NETWORK" in str(r["output"])


def test_runs_as_non_root_with_no_secret_env() -> None:
    r = _run(
        "import os\nprint(os.getuid() != 0, [k for k in os.environ "
        "if any(s in k for s in ('KEY', 'TOKEN', 'SECRET', 'PASS', 'DATABASE')) and os.environ[k]])"
    )
    assert "True []" in str(r["output"]), r["output"]


def test_refuses_instead_of_falling_back_when_docker_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.policy.sandbox._docker_available", lambda: False)
    r = _run("print('ran on the host')")
    assert not r["success"] and "sandbox unavailable" in str(r["output"])
    assert os.environ.get("BHASKAR_TOOL_SANDBOX_BACKEND") in (None, "process", "docker")

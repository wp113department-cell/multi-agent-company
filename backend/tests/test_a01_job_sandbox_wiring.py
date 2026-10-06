"""Sol audit A01 / gap audit G1 (2026-10-06): code-running tools must never
start the code they run on the backend host.

Wiring test, run for real (real Docker, real tool handlers, normal inputs):
every process the tool starts is recorded at `subprocess.Popen`. The only
programs allowed on the host are `docker` (the job container itself) and
`git` (bookkeeping on the worktree). If any tool starts python, node, sh,
pytest, make... directly on the host, the test fails — which it did on the
old code for every tool below.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.agents.tools import make_chat_handlers
from app.policy.sandbox import _docker_available

pytestmark = pytest.mark.skipif(
    not _docker_available(), reason="needs Docker (job sandbox)"
)

_HOST_ALLOWED = {"docker", "git"}


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")
    (tmp_path / "script.py").write_text("print('script-ran')\n")
    (tmp_path / "Makefile").write_text("hello:\n\t@echo make-ran\n")
    (tmp_path / "mod.py").write_text("import os\n\nx = 1\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


@pytest.fixture()
def host_processes(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    started: list[Any] = []
    real_popen = subprocess.Popen

    class Recording(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, args: Any, *a: Any, **kw: Any) -> None:
            started.append((args, bool(kw.get("shell"))))
            super().__init__(args, *a, **kw)

    monkeypatch.setattr(subprocess, "Popen", Recording)
    return started


def _host_violations(started: list[Any]) -> list[Any]:
    bad = []
    for args, shell in started:
        if shell or isinstance(args, (str, bytes)):
            bad.append(args)
            continue
        prog = os.path.basename(str(list(args)[0]))
        if prog not in _HOST_ALLOWED:
            bad.append(args)
    return bad


def _ran_in_job_container(started: list[Any]) -> bool:
    return any(
        not isinstance(a, (str, bytes))
        and list(a)[:2] == ["docker", "run"]
        and any(str(x).startswith("gridiron-job-") for x in a)
        for a, _ in started
    )


CASES = [
    ("run_python_snippet", {"code": "print(6 * 7)"}, "42"),
    ("run_node", {"code": "console.log(6 * 7)"}, "42"),
    ("run_script", {"path": "script.py"}, "script-ran"),
    ("run_make", {"target": "hello"}, "make-ran"),
    ("run_tests", {"path": "test_ok.py"}, "1 passed"),
    ("run_single_test", {"keyword": "test_ok", "file": "test_ok.py"}, "passed"),
    ("cpu_profile", {"command": "script.py"}, "script-ran"),
]


@pytest.mark.parametrize("tool,inp,expect", CASES, ids=[c[0] for c in CASES])
def test_code_running_tool_runs_only_inside_the_job_sandbox(
    tool: str, inp: dict[str, Any], expect: str, repo: Path, host_processes: list[Any]
) -> None:
    handlers = make_chat_handlers(str(repo))
    assert tool in handlers
    out = handlers[tool](inp)
    assert expect in out, out
    assert _ran_in_job_container(host_processes), host_processes
    assert _host_violations(host_processes) == []


def test_job_sandbox_never_mounts_the_servers_own_directory(
    host_processes: list[Any],
) -> None:
    """A shell command with no cwd and no leading `cd` gets an empty
    directory, never the backend's working directory (code + .env)."""
    from app.tools.execution import safe_subprocess

    r = safe_subprocess.run(
        "ls -A", shell=True, capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""
    mounts = [
        a[i + 1]
        for a, _ in host_processes
        if not isinstance(a, str)
        for i, x in enumerate(a)
        if x == "-v"
    ]
    assert mounts and all(not m.startswith(os.getcwd() + ":") for m in mounts)


def test_job_sandbox_refuses_to_mount_root_or_home(host_processes: list[Any]) -> None:
    from app.tools.execution import safe_subprocess

    for where in ("/", os.path.expanduser("~")):
        r = safe_subprocess.run(
            "true", shell=True, cwd=where, capture_output=True, text=True
        )
        assert r.returncode == 126 and "Refusing to mount" in r.stderr
    assert host_processes == []


def test_job_sandbox_unavailable_never_falls_back_to_the_host(
    monkeypatch: pytest.MonkeyPatch, repo: Path, host_processes: list[Any]
) -> None:
    import app.policy.sandbox as sandbox

    monkeypatch.setattr(sandbox, "_docker_available", lambda: False)
    out = make_chat_handlers(str(repo))["run_python_snippet"]({"code": "print(1)"})
    assert "SANDBOX UNAVAILABLE" in out
    assert _host_violations(host_processes) == []


# ---------------------------------------------------------------------------
# Sol A11: the job network is isolated from the control plane
# ---------------------------------------------------------------------------


def _networks(started: list[Any]) -> list[str]:
    return [
        str(x).split("=", 1)[1]
        for a, _ in started
        if not isinstance(a, (str, bytes)) and list(a)[:2] == ["docker", "run"]
        for x in a
        if str(x).startswith("--network=")
    ]


def test_job_code_runs_with_no_network_at_all(
    repo: Path, host_processes: list[Any]
) -> None:
    """Default job network is 'none': the container has only a loopback
    interface, so DB, Redis, the API, the host and cloud metadata are all
    unreachable from code an agent runs."""
    out = make_chat_handlers(str(repo))["run_python_snippet"](
        {"code": "print(len(open('/proc/net/route').read().splitlines()) - 1)"}
    )
    assert out.strip() == "0", out  # no routes: nothing beyond loopback
    assert _networks(host_processes) == ["none"]


def test_only_package_installs_use_the_install_network(
    host_processes: list[Any], tmp_path: Path
) -> None:
    from app.config import get_settings
    from app.tools.execution import safe_subprocess

    safe_subprocess.run(
        "true", shell=True, cwd=str(tmp_path), job_network="install", timeout=60
    )
    safe_subprocess.run("true", shell=True, cwd=str(tmp_path), timeout=60)
    assert _networks(host_processes) == [
        get_settings().job_sandbox_install_network,
        get_settings().job_sandbox_network,
    ]


def test_control_plane_ports_are_loopback_only_in_dev_compose() -> None:
    """The install network is a bridge; Postgres and Redis must therefore
    stay bound to 127.0.0.1 so the bridge gateway cannot reach them."""
    import yaml

    compose = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    )
    for svc in ("db", "redis"):
        for port in compose["services"][svc].get("ports", []):
            assert str(port).startswith("127.0.0.1:"), (svc, port)

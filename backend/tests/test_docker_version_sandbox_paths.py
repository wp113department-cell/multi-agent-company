"""Code sandbox in the Docker/Windows version (2026-10-09).

The backend container starts sandbox containers on the computer's own Docker
engine, so every mounted folder must be the ENGINE's path, translated from
the backend's own mounts (app/policy/docker_host.py). Before this change the
backend passed its own paths (`-v /workspace/x:/workspace/x`), which the
engine resolves on the computer instead, so a sandbox saw an empty or wrong
folder. Agents also may never exec into or restart the platform's own
containers.

No real Docker is used: `docker inspect` answers come from a fake.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.policy import docker_host

WIN_WS = "C:\\Users\\me\\Documents\\multi-agent-workspace"
VOL = "/var/lib/docker/volumes/crr2906_worktrees/_data"

SELF = {
    "Id": "self-id",
    "Name": "/crr2906-backend-1",
    "Config": {"Labels": {"com.docker.compose.project": "crr2906"}},
    "Mounts": [
        {"Type": "bind", "Source": WIN_WS, "Destination": "/workspace"},
        {
            "Type": "bind",
            "Source": "/home/me/repos-extra",
            "Destination": "/workspace/extra",
        },
        {
            "Type": "volume",
            "Name": "crr2906_worktrees",
            "Source": VOL,
            "Destination": "/tmp/gridiron-worktrees",
        },
        {
            "Type": "bind",
            "Source": "/var/run/docker.sock",
            "Destination": "/var/run/docker.sock",
        },
    ],
}
OTHERS = {
    "crr2906-db-1": {
        "Id": "db-id",
        "Name": "/crr2906-db-1",
        "Config": {"Labels": {"com.docker.compose.project": "crr2906"}},
    },
    "users-app": {
        "Id": "app-id",
        "Name": "/users-app",
        "Config": {"Labels": {"com.docker.compose.project": "shop"}},
    },
}


@pytest.fixture
def in_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    docker_host.reset_cache()
    monkeypatch.setenv("HOSTNAME", "self-id")
    monkeypatch.setattr(docker_host, "in_container", lambda: True)
    monkeypatch.setattr(docker_host.os.path, "realpath", lambda p, **k: str(p))

    def fake_inspect(name: str) -> dict[str, Any] | None:
        if name == "self-id":
            return SELF
        return OTHERS.get(name)

    monkeypatch.setattr(docker_host, "_inspect", fake_inspect)
    yield
    docker_host.reset_cache()


# -- on the computer itself nothing changes ---------------------------------


def test_native_mount_args_are_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_host, "in_container", lambda: False)
    assert docker_host.mount_args("/a/b", "/a/b", "rw") == ["-v", "/a/b:/a/b:rw"]
    assert docker_host.mount_args("/a", "/workspace", "ro") == [
        "-v",
        "/a:/workspace:ro",
    ]
    assert docker_host.engine_path("/x/y") == "/x/y"
    assert docker_host.platform_container_reason("anything") is None


# -- path translation in the Docker version ---------------------------------


def test_workspace_path_becomes_the_windows_folder(in_docker: None) -> None:
    assert docker_host.engine_path("/workspace/repos/shop") == WIN_WS + "\\repos\\shop"
    args = docker_host.mount_args(
        "/workspace/repos/shop", "/workspace/repos/shop", "rw"
    )
    assert args == [
        "--mount",
        f"type=bind,source={WIN_WS}\\repos\\shop,target=/workspace/repos/shop",
    ]


def test_worktree_path_becomes_a_sub_folder_of_the_named_volume(
    in_docker: None,
) -> None:
    assert (
        docker_host.engine_path("/tmp/gridiron-worktrees/task-7")
        == "volume:crr2906_worktrees/task-7"
    )
    # never the volume's internal /var/lib/docker path: Docker Desktop looks
    # for that on the computer and the container start hangs
    args = docker_host.mount_args(
        "/tmp/gridiron-worktrees/task-7", "/tmp/gridiron-worktrees/task-7", "rw"
    )
    assert args == [
        "--mount",
        "type=volume,source=crr2906_worktrees,"
        "target=/tmp/gridiron-worktrees/task-7,volume-subpath=task-7",
    ]
    assert VOL not in args[1]


def test_the_most_specific_mount_wins(in_docker: None) -> None:
    assert docker_host.engine_path("/workspace/extra/x") == "/home/me/repos-extra/x"


def test_read_only_and_csv_quoting(
    in_docker: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = docker_host.mount_args("/workspace/a,b", "/workspace", "ro")
    assert args[1] == f'type=bind,"source={WIN_WS}\\a,b",target=/workspace,readonly'


def test_a_folder_outside_the_shared_mounts_is_refused(in_docker: None) -> None:
    with pytest.raises(docker_host.SharedFolderError):
        docker_host.engine_path("/app/backend")
    with pytest.raises(docker_host.SharedFolderError):
        docker_host.engine_path("/workspacefoo/x")  # prefix, not a sub-folder


def test_own_container_not_found_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    docker_host.reset_cache()
    monkeypatch.setattr(docker_host, "in_container", lambda: True)
    monkeypatch.setattr(docker_host, "_inspect", lambda name: None)
    with pytest.raises(docker_host.SharedFolderError):
        docker_host.mount_args("/workspace/x", "/workspace/x", "rw")
    docker_host.reset_cache()


# -- every sandbox uses the translated path ---------------------------------


def test_job_sandbox_mounts_the_engine_path(
    in_docker: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.policy import sandbox
    from app.tools.execution import safe_subprocess

    monkeypatch.setattr(sandbox, "_docker_available", lambda: True)
    monkeypatch.setattr(safe_subprocess, "_exclude_from_git", lambda *a: None)
    monkeypatch.setattr(
        safe_subprocess, "_job_workdir", lambda command, cwd: "/workspace/repos/shop"
    )
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(safe_subprocess._subprocess, "run", fake_run)
    safe_subprocess._run_in_job_container(
        "pytest -q", cwd="/workspace/repos/shop", text=True, timeout=30
    )
    argv = seen[-1]
    assert "--mount" in argv
    assert (
        argv[argv.index("--mount") + 1]
        == f"type=bind,source={WIN_WS}\\repos\\shop,target=/workspace/repos/shop"
    )
    assert "/workspace/repos/shop:/workspace/repos/shop:rw" not in argv


def test_job_sandbox_reports_an_unshared_folder(
    in_docker: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.policy import sandbox
    from app.tools.execution import safe_subprocess

    monkeypatch.setattr(sandbox, "_docker_available", lambda: True)
    monkeypatch.setattr(safe_subprocess, "_exclude_from_git", lambda *a: None)
    monkeypatch.setattr(safe_subprocess, "_job_workdir", lambda command, cwd: "/app/x")
    ran: list[Any] = []
    monkeypatch.setattr(
        safe_subprocess._subprocess, "run", lambda *a, **k: ran.append(a)
    )
    result = safe_subprocess._run_in_job_container("ls", cwd="/app/x", text=True)
    assert result.returncode == 126
    assert "SANDBOX UNAVAILABLE" in result.stderr
    assert ran == []  # nothing ran, not even on the host


def test_bash_tool_sandbox_mounts_the_engine_path(
    in_docker: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.policy import sandbox

    monkeypatch.setattr(sandbox, "_docker_available", lambda: True)
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    sandbox.run_sandboxed("ls", "/tmp/gridiron-worktrees/task-7", read_only=True)
    argv = seen[-1]
    assert argv[argv.index("--mount") + 1] == (
        "type=volume,source=crr2906_worktrees,target=/workspace,"
        "volume-subpath=task-7,readonly"
    )


def test_bash_tool_sandbox_unshared_folder_is_unavailable(
    in_docker: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.policy import sandbox

    monkeypatch.setattr(sandbox, "_docker_available", lambda: True)
    with pytest.raises(sandbox.SandboxUnavailableError):
        sandbox.run_sandboxed("ls", "/app/backend")


def test_background_process_and_terminal_mount_the_engine_path(in_docker: None) -> None:
    from app.fleet.process_manager import _build_sandboxed_argv
    from app.tools.execution.pty_session import _build_pty_argv

    want = (
        "type=volume,source=crr2906_worktrees,"
        "target=/tmp/gridiron-worktrees/task-7,volume-subpath=task-7"
    )
    bg = _build_sandboxed_argv("npm start", "/tmp/gridiron-worktrees/task-7", "bg-1")
    pty = _build_pty_argv("/tmp/gridiron-worktrees/task-7", "pty-1", "img", "none")
    for argv in (bg, pty):
        assert argv[argv.index("--mount") + 1] == want


# -- the platform's own containers are off limits ---------------------------


def test_agents_may_not_touch_the_platforms_own_containers(in_docker: None) -> None:
    assert docker_host.platform_container_reason("crr2906-db-1")
    assert docker_host.platform_container_reason("self-id")
    assert docker_host.platform_container_reason("users-app") is None


def test_docker_exec_check_refuses_the_platform_database(in_docker: None) -> None:
    from app.agents.tool_security import _docker_container_risk_reason

    reason = _docker_container_risk_reason("crr2906-db-1")
    assert reason and "platform" in reason


def test_docker_restart_tool_refuses_the_platform_database(
    in_docker: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.agents import tools

    ran: list[Any] = []
    monkeypatch.setattr(tools.subprocess, "run", lambda *a, **k: ran.append(a))
    for factory in (tools.make_docker_agent_handlers, tools.make_chat_handlers):
        out = factory(str(tmp_path))["docker_restart"]({"container": "crr2906-db-1"})
        assert out.startswith("[POLICY DENIED]")
    assert ran == []


def test_compose_gives_the_backend_the_engine_and_shared_worktrees() -> None:
    import yaml

    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    backend = compose["services"]["backend"]
    assert "/var/run/docker.sock:/var/run/docker.sock" in backend["volumes"]
    assert "worktrees:/tmp/gridiron-worktrees" in backend["volumes"]
    assert backend["depends_on"]["sandbox-image"]["condition"] == (
        "service_completed_successfully"
    )
    assert (
        compose["services"]["sandbox-image"]["image"]
        == "gridiron-bash-toolchain:latest"
    )
    prod = yaml.safe_load((root / "docker-compose.prod.yml").read_text())
    for service in prod["services"].values():
        assert not any("docker.sock" in str(v) for v in service.get("volumes") or [])
    dockerfile = (root / "backend" / "Dockerfile").read_text()
    assert "/usr/local/bin/docker" in dockerfile

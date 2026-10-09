"""Sol A31 (2026-10-09): the sandbox runner.

The backend no longer holds the Docker socket (admin rights on the
computer). The runner does, and lets through only what the code sandboxes
need. Rule tests run everywhere; the end-to-end tests drive the real
`docker` CLI through the runner to the real engine when Docker is present.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest

from app.runner.proxy import Denied, Policy, Runner, route, strip_env, validate_create

TOOLCHAIN = "gridiron-bash-toolchain:latest"
POLICY = Policy(
    images={TOOLCHAIN, "alpine:latest"},
    networks={"none", "bridge", "default"},
    bind_roots=["C:\\Users\\me\\Documents\\multi-agent-workspace", "/home/me/ws"],
    volumes={"crr2906_worktrees"},
)


def _ok(**host: Any) -> dict[str, Any]:
    return {
        "Image": TOOLCHAIN,
        "User": "10001:10001",
        "HostConfig": {"NetworkMode": "none", **host},
    }


def test_a_normal_sandbox_container_is_allowed() -> None:
    validate_create(
        _ok(
            Mounts=[
                {
                    "Type": "bind",
                    "Source": "C:\\Users\\me\\Documents\\multi-agent-workspace\\shop",
                    "Target": "/workspace/shop",
                },
                {
                    "Type": "volume",
                    "Source": "crr2906_worktrees",
                    "Target": "/tmp/gridiron-worktrees/task-7",
                    "VolumeOptions": {"Subpath": "task-7"},
                },
                {"Type": "tmpfs", "Target": "/tmp"},
            ],
            Tmpfs={"/tmp": "size=256m"},
        ),
        POLICY,
    )


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ({**_ok(), "Image": "ubuntu:latest"}, "approved sandbox image"),
        ({**_ok(), "User": ""}, "non-root"),
        ({**_ok(), "User": "0"}, "non-root"),
        (_ok(Privileged=True), "privileged"),
        (_ok(CapAdd=["SYS_ADMIN"]), "capabilities"),
        (_ok(Devices=[{"PathOnHost": "/dev/sda"}]), "Devices"),
        (_ok(PidMode="host"), "PidMode=host"),
        (_ok(NetworkMode="host"), "network 'host'"),
        (_ok(NetworkMode="container:crr2906-db-1"), "not allowed"),
        (_ok(SecurityOpt=["seccomp=unconfined"]), "seccomp"),
        (_ok(Binds=["/:/host"]), "binds are not allowed"),
        (_ok(VolumesFrom=["crr2906-backend-1"]), "VolumesFrom"),
        (
            _ok(Mounts=[{"Type": "bind", "Source": "/", "Target": "/host"}]),
            "outside the shared workspace",
        ),
        (
            _ok(
                Mounts=[
                    {
                        "Type": "bind",
                        "Source": "/var/run/docker.sock",
                        "Target": "/var/run/docker.sock",
                    }
                ]
            ),
            "outside the shared workspace",
        ),
        (
            _ok(
                Mounts=[
                    {
                        "Type": "bind",
                        "Source": "C:\\Users\\me\\Documents\\multi-agent-workspace\\..\\..",
                        "Target": "/x",
                    }
                ]
            ),
            "outside the shared workspace",
        ),
        (
            _ok(
                Mounts=[
                    {
                        "Type": "bind",
                        "Source": "/home/me/ws-other",
                        "Target": "/x",
                    }
                ]
            ),
            "outside the shared workspace",
        ),
        (
            _ok(
                Mounts=[
                    {"Type": "volume", "Source": "crr2906_worktrees", "Target": "/w"}
                ]
            ),
            "own sub-folder",
        ),
        (
            _ok(
                Mounts=[
                    {
                        "Type": "volume",
                        "Source": "crr2906_pgdata",
                        "Target": "/w",
                        "VolumeOptions": {"Subpath": "x"},
                    }
                ]
            ),
            "own sub-folder",
        ),
        ({**_ok(), "Volumes": {"/data": {}}}, "anonymous volume"),
    ],
)
def test_dangerous_containers_are_refused(body: dict[str, Any], why: str) -> None:
    with pytest.raises(Denied) as err:
        validate_create(body, POLICY)
    assert why in str(err.value)


@pytest.mark.parametrize(
    ("method", "path", "kind"),
    [
        ("HEAD", "/_ping", "pipe"),
        ("GET", "/v1.47/version", "pipe"),
        ("POST", "/v1.47/containers/create?name=gridiron-job-1", "create"),
        ("POST", "/v1.47/containers/abc/attach?stream=1", "owned"),
        ("POST", "/v1.47/containers/gridiron-job-1/kill?signal=KILL", "owned"),
        ("DELETE", "/v1.47/containers/abc", "owned"),
        ("GET", "/v1.47/containers/crr2906-db-1/json", "inspect"),
        ("POST", "/v1.47/images/create?fromImage=alpine&tag=latest", "pull"),
    ],
)
def test_sandbox_operations_are_routed(method: str, path: str, kind: str) -> None:
    assert route(method, path)[0] == kind


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v1.47/containers/crr2906-db-1/exec"),
        ("POST", "/v1.47/exec/123/start"),
        ("POST", "/v1.47/containers/crr2906-db-1/restart"),
        ("POST", "/v1.47/build"),
        ("POST", "/v1.47/volumes/create"),
        ("DELETE", "/v1.47/volumes/crr2906_pgdata"),
        ("POST", "/v1.47/networks/create"),
        ("PUT", "/v1.47/containers/abc/archive"),
        ("POST", "/v1.47/swarm/init"),
    ],
)
def test_everything_else_is_blocked(method: str, path: str) -> None:
    with pytest.raises(Denied):
        route(method, path)


def test_other_containers_are_inspected_without_their_secrets() -> None:
    info = {
        "Id": "x",
        "Config": {"Env": ["POSTGRES_PASSWORD=secret"], "Labels": {"a": "b"}},
    }
    assert strip_env(info) == {"Id": "x", "Config": {"Labels": {"a": "b"}}}


# -- end to end: the real docker CLI -> runner -> real engine ----------------


def _engine_socket() -> str | None:
    if not shutil.which("docker"):
        return None
    try:
        out = subprocess.run(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except Exception:
        return None
    path = out.removeprefix("unix://")
    if not out.startswith("unix://") or not os.path.exists(path):
        return None
    if subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode:
        return None
    return path


@pytest.fixture(scope="module")
def runner_host() -> Any:
    sock = _engine_socket()
    if sock is None:
        pytest.skip("no local Docker engine")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    runner = Runner(
        Policy(
            images={"alpine:latest"}, networks={"none"}, bind_roots=[], volumes=set()
        ),
        docker_sock=sock,
    )
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    async def main() -> None:
        server = await asyncio.start_server(runner.handle, "127.0.0.1", port)
        ready.set()
        async with server:
            await server.serve_forever()

    thread = threading.Thread(
        target=lambda: loop.run_until_complete(main()), daemon=True
    )
    thread.start()
    ready.wait(10)
    subprocess.run(
        ["docker", "pull", "-q", "alpine:latest"], capture_output=True, timeout=120
    )
    yield f"tcp://127.0.0.1:{port}"
    loop.call_soon_threadsafe(loop.stop)


def _docker(host: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DOCKER_HOST": host}
    env.pop("DOCKER_CONTEXT", None)
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=120, env=env
    )


def test_a_sandbox_run_works_through_the_runner(runner_host: str) -> None:
    r = _docker(
        runner_host,
        "run",
        "--rm",
        "--user",
        "10001:10001",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "alpine:latest",
        "sh",
        "-c",
        "echo hello-from-sandbox",
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "hello-from-sandbox"


def test_a_sandbox_can_be_killed_by_name(runner_host: str) -> None:
    name = "gridiron-job-a31-kill"
    started = _docker(
        runner_host,
        "run",
        "-d",
        "--rm",
        "--name",
        name,
        "--user",
        "10001",
        "--network=none",
        "alpine:latest",
        "sleep",
        "60",
    )
    assert started.returncode == 0, started.stderr
    killed = _docker(runner_host, "kill", name)
    assert killed.returncode == 0, killed.stderr


@pytest.mark.parametrize(
    "args",
    [
        ["--privileged"],
        ["--network=host"],
        ["-v", "/:/host"],
        ["--user", "0"],
        ["--pid=host"],
    ],
)
def test_dangerous_runs_are_refused(runner_host: str, args: list[str]) -> None:
    user = [] if "--user" in args else ["--user", "10001"]
    net = [] if any(a.startswith("--network") for a in args) else ["--network=none"]
    r = _docker(runner_host, "run", "--rm", *user, *net, *args, "alpine:latest", "true")
    assert r.returncode != 0
    assert "blocked" in r.stderr or "not allowed" in r.stderr or "non-root" in r.stderr


def test_other_containers_cannot_be_controlled(
    runner_host: str, tmp_path: Path
) -> None:
    # a container NOT created through the runner (straight on the engine)
    victim = subprocess.run(
        ["docker", "run", "-d", "--rm", "alpine:latest", "sleep", "60"],
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.strip()
    try:
        for args in (
            ["exec", victim, "true"],
            ["kill", victim],
            ["restart", victim],
            ["logs", victim],
        ):
            r = _docker(runner_host, *args)
            assert r.returncode != 0, args
        inspected = _docker(runner_host, "inspect", victim)
        assert inspected.returncode == 0 and '"Env"' not in inspected.stdout
    finally:
        subprocess.run(["docker", "kill", victim], capture_output=True, timeout=30)

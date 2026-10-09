"""Sandbox runner: a strict gate in front of the Docker engine (Sol A31,
2026-10-09).

The audit (A31): "provide trusted external execution workers ... do not
grant unrestricted host Docker socket access as a routine shortcut". Access
to the Docker socket is admin rights on the computer, so the backend no
longer holds it. This small service does, in its own container, and the
backend's `docker` commands reach it over a private network
(DOCKER_HOST=tcp://runner:2375). It speaks the Docker Engine API but lets
through only what the code sandboxes need:

- create a container from an approved image, as a non-root user, never
  privileged, no added capabilities or devices, no host namespaces, an
  approved network, and folders only from the shared workspace or a
  sub-folder of the task-worktrees volume (the same folders this runner
  itself has mounted — it learns their engine names by inspecting itself);
- start, wait, attach, resize, logs, kill, stop and remove — only for
  containers it created (labelled gridiron.runner=1);
- read-only engine calls (ping, version, info, image inspect, container
  list) and pulling an approved image;
- inspecting other containers, with their environment removed (it holds
  passwords and keys).

Everything else — exec into another container, restart, build, compose,
volumes, networks, privileged or host-mounted containers — gets HTTP 403
with a plain message, which the docker CLI prints. The sandbox tools keep
working unchanged; Docker control tools report clearly that they are
disabled here.

Each client connection carries one request (`Connection: close` is forced,
except for the attach upgrade), so after the request is checked the bytes
are simply relayed in both directions — streaming logs and interactive
terminals included.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ntpath
import os
import posixpath
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

logger = logging.getLogger("gridiron.runner")

LABEL = "gridiron.runner"
_VERSION_PREFIX = re.compile(r"^/v\d+(\.\d+)?(?=/)")
_ID = r"(?P<id>[A-Za-z0-9][A-Za-z0-9_.-]*)"
_MAX_HEAD = 64 * 1024
_MAX_BODY = 1024 * 1024


@dataclass
class Policy:
    images: set[str]
    networks: set[str]
    bind_roots: list[str] = field(default_factory=list)  # engine paths
    volumes: set[str] = field(default_factory=set)  # volume names (sub-folders only)


class Denied(Exception):
    pass


# -- request rules -------------------------------------------------------------


def _norm(path: str) -> tuple[str, Any]:
    mod: Any = ntpath if ("\\" in path or re.match(r"^[A-Za-z]:", path)) else posixpath
    return mod.normcase(mod.normpath(path)), mod


def _under(path: str, roots: list[str]) -> bool:
    if not path:
        return False
    p, mod = _norm(path)
    for root in roots:
        r, rmod = _norm(root)
        if rmod is not mod:
            continue
        if p == r or p.startswith(r.rstrip(mod.sep) + mod.sep):
            return True
    return False


def validate_create(body: dict[str, Any], policy: Policy) -> None:
    """Raise Denied unless this container is one a sandbox may create."""
    image = str(body.get("Image") or "")
    if image not in policy.images:
        raise Denied(f"image {image!r} is not an approved sandbox image")
    user = str(body.get("User") or "")
    if user in ("", "0", "root") or user.startswith(("0:", "root:")):
        raise Denied("sandbox containers must run as a non-root user")
    host = body.get("HostConfig") or {}
    if host.get("Privileged"):
        raise Denied("privileged containers are not allowed")
    if host.get("CapAdd"):
        raise Denied("added capabilities are not allowed")
    for key in ("Devices", "DeviceRequests", "VolumesFrom", "Links", "Sysctls"):
        if host.get(key):
            raise Denied(f"{key} is not allowed")
    for key in ("PidMode", "IpcMode", "UTSMode", "UsernsMode", "CgroupnsMode"):
        if str(host.get(key) or "") == "host":
            raise Denied(f"{key}=host is not allowed")
    for opt in host.get("SecurityOpt") or []:
        if "unconfined" in str(opt):
            raise Denied("disabling seccomp/apparmor is not allowed")
    runtime = str(host.get("Runtime") or "")
    if runtime not in ("", "runc"):
        raise Denied(f"runtime {runtime!r} is not allowed")
    network = str(host.get("NetworkMode") or "default")
    if network not in policy.networks:
        raise Denied(f"network {network!r} is not allowed")
    if host.get("Binds"):
        raise Denied("folders must be given as --mount (binds are not allowed)")
    for mount in host.get("Mounts") or []:
        kind = str(mount.get("Type") or "")
        source = str(mount.get("Source") or "")
        if kind == "tmpfs":
            continue
        if kind == "bind":
            if not _under(source, policy.bind_roots):
                raise Denied(f"folder {source!r} is outside the shared workspace")
            continue
        if kind == "volume":
            sub = str((mount.get("VolumeOptions") or {}).get("Subpath") or "")
            if source not in policy.volumes or not sub or ".." in sub.split("/"):
                raise Denied("only a task's own sub-folder of the worktrees volume")
            continue
        raise Denied(f"mount type {kind!r} is not allowed")
    for name in (body.get("Volumes") or {}).keys():
        raise Denied(f"anonymous volume {name!r} is not allowed")


ROUTES: list[tuple[str, re.Pattern[str], str]] = [
    (m, re.compile(p), kind)
    for m, p, kind in [
        ("HEAD", r"^/_ping$", "pipe"),
        ("GET", r"^/_ping$", "pipe"),
        ("GET", r"^/version$", "pipe"),
        ("GET", r"^/info$", "pipe"),
        ("GET", r"^/containers/json$", "pipe"),
        ("GET", r"^/images/.+/json$", "pipe"),
        ("POST", r"^/images/create$", "pull"),
        ("POST", r"^/containers/create$", "create"),
        ("GET", rf"^/containers/{_ID}/json$", "inspect"),
        ("GET", rf"^/containers/{_ID}/logs$", "owned"),
        (
            "POST",
            rf"^/containers/{_ID}/(start|wait|attach|resize|kill|stop)$",
            "owned",
        ),
        ("DELETE", rf"^/containers/{_ID}$", "owned"),
    ]
]


def route(method: str, target: str) -> tuple[str, str | None]:
    """(kind, container id/name) for an allowed request; Denied otherwise."""
    path = _VERSION_PREFIX.sub("", urlsplit(target).path)
    for m, pattern, kind in ROUTES:
        found = pattern.match(path)
        if m == method and found:
            return kind, found.groupdict().get("id")
    raise Denied(
        f"{method} {path} is blocked by the sandbox runner (only the code "
        "sandbox's own containers can be managed here)"
    )


def pull_allowed(target: str, policy: Policy) -> bool:
    q = parse_qs(urlsplit(target).query)
    image = q.get("fromImage", [""])[0]
    tag = q.get("tag", ["latest"])[0] or "latest"
    ref = image if ":" in image.rsplit("/", 1)[-1] else f"{image}:{tag}"
    return ref in policy.images


def strip_env(info: dict[str, Any]) -> dict[str, Any]:
    cfg = info.get("Config")
    if isinstance(cfg, dict):
        cfg.pop("Env", None)
    return info


# -- HTTP plumbing ---------------------------------------------------------------


class _Request:
    def __init__(self, head: bytes, body: bytes) -> None:
        lines = head.decode("latin-1").split("\r\n")
        self.method, self.target, self.version = lines[0].split(" ", 2)
        self.headers: list[tuple[str, str]] = []
        for line in lines[1:]:
            if line:
                k, _, v = line.partition(":")
                self.headers.append((k.strip(), v.strip()))
        self.body = body

    def header(self, name: str) -> str:
        for k, v in self.headers:
            if k.lower() == name.lower():
                return v
        return ""

    def encode(self, *, close: bool) -> bytes:
        drop = {"content-length", "transfer-encoding"}
        if close:
            drop |= {"connection", "keep-alive"}
        lines = [f"{self.method} {self.target} {self.version}"]
        lines += [f"{k}: {v}" for k, v in self.headers if k.lower() not in drop]
        if self.body or self.method in ("POST", "PUT"):
            lines.append(f"Content-Length: {len(self.body)}")
        if close:
            lines.append("Connection: close")
        return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + self.body


async def _read_request(reader: asyncio.StreamReader) -> _Request | None:
    try:
        head = await reader.readuntil(b"\r\n\r\n")
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        return None
    if len(head) > _MAX_HEAD:
        raise Denied("request headers too large")
    req = _Request(head[:-4], b"")
    if req.header("Transfer-Encoding").lower() == "chunked":
        raise Denied("streamed uploads are not allowed")
    length = int(req.header("Content-Length") or 0)
    if length > _MAX_BODY:
        raise Denied("request body too large")
    if length:
        req.body = await reader.readexactly(length)
    return req


def _response(status: int, reason: str, payload: Any) -> bytes:
    body = json.dumps(payload).encode()
    return (
        f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    ).encode() + body


def _dechunk(data: bytes) -> bytes:
    out, rest = b"", data
    while rest:
        size_line, _, rest = rest.partition(b"\r\n")
        size = int(size_line.split(b";")[0] or b"0", 16)
        if size == 0:
            break
        out, rest = out + rest[:size], rest[size + 2 :]
    return out


class Runner:
    def __init__(
        self, policy: Policy, docker_sock: str = "/var/run/docker.sock"
    ) -> None:
        self.policy = policy
        self.sock = docker_sock
        self.owned: set[str] = set()

    async def _engine(self, raw: bytes) -> tuple[int, dict[str, str], bytes]:
        """Send one complete request to the engine; read the whole reply."""
        r, w = await asyncio.open_unix_connection(self.sock)
        try:
            w.write(raw)
            await w.drain()
            data = await r.read()
        finally:
            w.close()
        head, _, body = data.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        status = int(lines[0].split(" ")[1])
        headers = {
            k.strip().lower(): v.strip()
            for k, _, v in (ln.partition(":") for ln in lines[1:])
        }
        if headers.get("transfer-encoding", "").lower() == "chunked":
            body = _dechunk(body)
        return status, headers, body

    async def _get_json(self, path: str) -> tuple[int, Any]:
        status, _, body = await self._engine(
            f"GET {path} HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n".encode()
        )
        try:
            return status, json.loads(body or b"null")
        except ValueError:
            return status, None

    async def is_owned(self, ident: str) -> bool:
        ident = ident.lstrip("/")
        if ident in self.owned:
            return True
        status, info = await self._get_json(f"/containers/{ident}/json")
        labels = ((info or {}).get("Config") or {}).get("Labels") or {}
        if status == 200 and labels.get(LABEL) == "1":
            self.owned.add(ident)
            return True
        return False

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            try:
                req = await _read_request(reader)
                if req is None:
                    return
                kind, ident = route(req.method, req.target)
                if kind == "pull" and not pull_allowed(req.target, self.policy):
                    raise Denied("only approved sandbox images can be pulled")
                if kind == "owned" and not (ident and await self.is_owned(ident)):
                    raise Denied(
                        f"container {ident!r} was not created by the code sandbox"
                    )
                if kind == "create":
                    await self._create(req, writer)
                    return
                if kind == "inspect" and not (ident and await self.is_owned(ident)):
                    await self._inspect_other(req, writer)
                    return
            except Denied as exc:
                logger.warning("runner blocked: %s", exc)
                writer.write(_response(403, "Forbidden", {"message": str(exc)}))
                await writer.drain()
                return
            await self._relay(req, reader, writer)
        except Exception:
            logger.exception("runner connection failed")
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _create(self, req: _Request, writer: asyncio.StreamWriter) -> None:
        try:
            body = json.loads(req.body or b"{}")
        except ValueError:
            raise Denied("container request is not valid JSON") from None
        validate_create(body, self.policy)
        body.setdefault("Labels", {})
        body["Labels"] = {**(body.get("Labels") or {}), LABEL: "1"}
        req.body = json.dumps(body).encode()
        status, headers, out = await self._engine(req.encode(close=True))
        if status == 201:
            try:
                self.owned.add(str(json.loads(out)["Id"]))
            except (ValueError, KeyError):
                pass
            name = parse_qs(urlsplit(req.target).query).get("name", [""])[0]
            if name:
                self.owned.add(name)
        writer.write(
            f"HTTP/1.1 {status} OK\r\nContent-Type: "
            f"{headers.get('content-type', 'application/json')}\r\n"
            f"Content-Length: {len(out)}\r\nConnection: close\r\n\r\n".encode() + out
        )
        await writer.drain()

    async def _inspect_other(self, req: _Request, writer: asyncio.StreamWriter) -> None:
        status, _, out = await self._engine(req.encode(close=True))
        if status == 200:
            out = json.dumps(strip_env(json.loads(out))).encode()
        writer.write(
            f"HTTP/1.1 {status} OK\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(out)}\r\nConnection: close\r\n\r\n".encode() + out
        )
        await writer.drain()

    async def _relay(
        self,
        req: _Request,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        upgrade = bool(req.header("Upgrade"))
        er, ew = await asyncio.open_unix_connection(self.sock)
        ew.write(req.encode(close=not upgrade))
        await ew.drain()

        async def pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
            try:
                while chunk := await src.read(65536):
                    dst.write(chunk)
                    await dst.drain()
            except (ConnectionError, asyncio.CancelledError):
                pass
            finally:
                try:
                    if dst.can_write_eof():
                        dst.write_eof()
                except (OSError, RuntimeError):
                    pass

        down = asyncio.create_task(pipe(er, writer))
        up = asyncio.create_task(pipe(reader, ew))
        await down
        up.cancel()
        ew.close()


# -- start-up ------------------------------------------------------------------


async def own_mount_policy(runner: Runner) -> None:
    """Learn which folders sandboxes may use: exactly the ones this runner
    container itself has mounted (not the Docker socket), as the engine
    names them."""
    host = os.environ.get("HOSTNAME", "")
    for attempt in range(30):
        status, info = await runner._get_json(f"/containers/{host}/json")
        if status == 200 and info:
            break
        await asyncio.sleep(2)
    else:
        raise RuntimeError("the runner could not inspect its own container")
    for mount in info.get("Mounts") or []:
        if str(mount.get("Destination")) == "/var/run/docker.sock":
            continue
        if mount.get("Type") == "bind" and mount.get("Source"):
            runner.policy.bind_roots.append(str(mount["Source"]))
        elif mount.get("Type") == "volume" and mount.get("Name"):
            runner.policy.volumes.add(str(mount["Name"]))
    logger.info(
        "runner ready: images=%s networks=%s folders=%s volumes=%s",
        sorted(runner.policy.images),
        sorted(runner.policy.networks),
        runner.policy.bind_roots,
        sorted(runner.policy.volumes),
    )


def policy_from_env() -> Policy:
    def items(name: str, default: str) -> set[str]:
        return {
            x.strip() for x in os.environ.get(name, default).split(",") if x.strip()
        }

    return Policy(
        images=items("RUNNER_IMAGES", "gridiron-bash-toolchain:latest,alpine:latest"),
        networks=items("RUNNER_NETWORKS", "none,bridge,default"),
    )


async def serve(host: str = "0.0.0.0", port: int = 2375) -> None:
    runner = Runner(policy_from_env())
    await own_mount_policy(runner)
    server = await asyncio.start_server(runner.handle, host, port)
    async with server:
        await server.serve_forever()

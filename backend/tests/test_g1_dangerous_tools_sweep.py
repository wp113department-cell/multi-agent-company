"""G1 (2026-10-19): every tool that writes files, reaches the network, uses
the browser or reads the environment — and does not execute code (those are
sandboxed, A01/A31) — attacked through its REAL handler.

For each such tool in the manifest, every path-like argument gets path
escapes (`../`, an absolute path, a symlink out of the workspace, `/etc/passwd`,
`.env`), every URL-like argument gets internal addresses (localhost, IPv6
loopback, a hex IP, cloud metadata, `file://`), and some tools get targeted
attacks (patches writing outside, git option injection, secret env vars).
A tool fails if a canary outside the workspace is read or written, a secret
comes back, or a local listener receives a connection.

The first sweep found 3 real holes, fixed with this test:
  * check_target_repo_license_compliance read any file on the host
    (`requirements_filename` was never checked);
  * git_fetch / git_pull let `remote` be any URL, so git connected to
    localhost / internal addresses;
  * read_env_var returned DATABASE_URL with its password.
"""

from __future__ import annotations

import inspect
import os
import socket
import subprocess
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from app.fleet.tool_manifest import TOOL_MANIFEST

SECRET = "ENV-SECRET-CANARY-7f3a"
OUT_CANARY = "OUTSIDE-CANARY-91c2"
ENV_CANARY = "ENVVAR-CANARY-55d1"

TARGETS = sorted(
    n
    for n, e in TOOL_MANIFEST.items()
    if set(e.permissions or [])
    & {"write_repo", "network", "write_remote", "browser", "read_env"}
    and not set(e.permissions or []) & {"execute", "docker"}
)
PATH_KEYS = (
    "path",
    "file",
    "dir",
    "src",
    "dest",
    "target",
    "source",
    "output",
    "archive",
    "folder",
)
URL_KEYS = ("url", "endpoint", "remote", "host", "base")


class Env:
    def __init__(self, root: Path) -> None:
        self.ws = root / "ws"
        self.outside = root / "outside"
        self.ws.mkdir()
        self.outside.mkdir()
        (self.outside / "canary.txt").write_text(OUT_CANARY)
        (self.ws / "a.py").write_text("def f():\n    return 1\n")
        (self.ws / ".env").write_text(f"SECRET_KEY={SECRET}\n")
        os.symlink(self.outside, self.ws / "link")
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "init", "-q"], cwd=self.ws, check=True)
        subprocess.run([*git, "add", "a.py"], cwd=self.ws, check=True)
        subprocess.run([*git, "commit", "-qm", "a"], cwd=self.ws, check=True)
        self.hits: list[str] = []
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(50)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        while True:
            try:
                c, a = self.srv.accept()
            except OSError:
                return
            self.hits.append(str(a))
            c.close()

    def attacks(self, tool: str, param: str) -> list[Any]:
        paths = [
            "../outside/canary.txt",
            str(self.outside / "canary.txt"),
            "link/canary.txt",
            "/etc/passwd",
            ".env",
        ]
        urls = [
            f"http://127.0.0.1:{self.port}/x",
            f"http://localhost:{self.port}/x",
            f"http://[::1]:{self.port}/x",
            f"http://0x7f000001:{self.port}/x",
            "http://169.254.169.254/latest/meta-data/",
            "file:///etc/passwd",
        ]
        pwn = self.outside / "pwned"
        inject = [f"--exec=touch {pwn}", f"--upload-pack=touch {pwn}", f"-o{pwn}"]
        patch = "--- /dev/null\n+++ {}\n@@ -0,0 +1 @@\n+pwn\n"
        extra: dict[str, dict[str, list[Any]]] = {
            "env_diff": {"example": paths, "actual": paths},
            "read_env_var": {
                "name": [
                    "ANTHROPIC_API_KEY",
                    "JWT_SECRET_KEY",
                    "DATABASE_URL",
                    "GITHUB_TOKEN",
                ]
            },
            "apply_patch": {
                "patch": [
                    patch.format("b/../outside/pwn.txt"),
                    patch.format("b/link/pwn.txt"),
                    patch.format(self.outside / "pwn.txt"),
                ]
            },
            "create_branch": {"name": inject, "from_branch": inject},
            "git_merge": {"branch": inject},
            "git_rebase": {"onto": inject},
            "git_reset": {"ref": inject},
            "git_tag": {"name": inject},
            "git_cherry_pick": {"commit_hash": inject},
        }
        if tool in extra:
            return extra[tool].get(param, [])
        low = param.lower()
        if any(k in low for k in PATH_KEYS):
            return paths
        if any(k in low for k in URL_KEYS):
            return urls
        return []

    def damage(self) -> list[str]:
        bad = []
        for p in self.ws.rglob("*"):
            if p.is_file() and not p.is_symlink() and ".git" not in p.parts:
                if p.name != ".env" and SECRET in p.read_text(errors="ignore"):
                    bad.append(f"copied the .env secret into {p.relative_to(self.ws)}")
                    p.unlink()
        for p in self.outside.iterdir():
            if p.name != "canary.txt":
                bad.append(f"wrote outside the workspace: {p.name}")
                subprocess.run(["rm", "-rf", str(p)], check=False)
        if (self.outside / "canary.txt").read_text() != OUT_CANARY:
            bad.append("changed a file outside the workspace")
            (self.outside / "canary.txt").write_text(OUT_CANARY)
        return bad


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    e = Env(tmp_path_factory.mktemp("g1"))
    yield e
    e.srv.close()


@pytest.fixture(scope="module")
def tools(env: Env) -> tuple[dict[str, Callable[..., Any]], dict[str, dict[str, Any]]]:
    """Every tool's real handler (from every make_*_handlers factory bound to
    the workspace) and its input schema."""
    import app.agents.tools as tools_mod

    handlers: dict[str, Callable[..., Any]] = {}
    for name, fn in inspect.getmembers(tools_mod, inspect.isfunction):
        if not (name.startswith("make_") and name.endswith("_handlers")):
            continue
        kw: dict[str, Any] = {}
        usable = True
        for p in inspect.signature(fn).parameters.values():
            if p.name in ("repo_path", "worktree_path", "workspace", "cwd"):
                kw[p.name] = str(env.ws)
            elif p.default is inspect.Parameter.empty:
                usable = False
        if usable:
            for k, v in fn(**kw).items():
                handlers.setdefault(k, v)
    schemas: dict[str, dict[str, Any]] = {}
    for _n, obj in inspect.getmembers(tools_mod):
        items = obj if isinstance(obj, list) else [obj] if isinstance(obj, dict) else []
        for t in items:
            if isinstance(t, dict) and "name" in t and "input_schema" in t:
                schemas.setdefault(t["name"], t["input_schema"])
    return handlers, schemas


@pytest.fixture(autouse=True)
def _no_real_keys(monkeypatch: pytest.MonkeyPatch, env: Env) -> None:
    from app.config import get_settings

    s = get_settings()
    for field in (
        "github_token",
        "slack_webhook_url",
        "linear_api_key",
        "firecrawl_api_key",
    ):
        monkeypatch.setattr(s, field, "")
    for var in (
        "GITHUB_TOKEN",
        "SLACK_WEBHOOK_URL",
        "LINEAR_API_KEY",
        "FIRECRAWL_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", ENV_CANARY)
    monkeypatch.setenv("DATABASE_URL", f"postgresql+asyncpg://u:{ENV_CANARY}@db:5432/x")
    monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(env.ws))


def _call(handler: Callable[..., Any], args: dict[str, Any]) -> str:
    box: list[str] = []

    def run() -> None:
        try:
            box.append(str(handler(args)))
        except Exception as exc:
            box.append(f"[EXC] {type(exc).__name__}: {exc}")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(30)
    return box[0] if box else "[TIMEOUT]"


def _dummy(spec: dict[str, Any]) -> Any:
    return {"integer": 1, "number": 1, "boolean": False, "array": [], "object": {}}.get(
        spec.get("type", ""), "x"
    )


def test_every_target_tool_has_a_handler_and_a_schema(tools: Any) -> None:
    handlers, schemas = tools
    assert len(TARGETS) > 60
    assert [t for t in TARGETS if t not in handlers or t not in schemas] == []


@pytest.mark.parametrize("tool", TARGETS)
def test_tool_refuses_every_attack(tool: str, env: Env, tools: Any) -> None:
    handlers, schemas = tools
    schema = schemas[tool]
    props: dict[str, Any] = schema.get("properties", {})
    findings = []
    for param in props:
        for attack in env.attacks(tool, param):
            args = {p: _dummy(props[p]) for p in schema.get("required", [])}
            if "timeout" in props and param != "timeout":
                args["timeout"] = 1  # wait_for_port otherwise waits 30 s per attack
            args[param] = attack
            before = len(env.hits)
            result = _call(handlers[tool], args)
            bad = env.damage()
            if OUT_CANARY in result:
                bad.append("read a file outside the workspace")
            if SECRET in result:
                bad.append("returned the .env secret")
            if ENV_CANARY in result or "sk-ant-test-not-a-real-key" in result:
                bad.append("returned a secret environment variable")
            if "root:x:0:0" in result:
                bad.append("read /etc/passwd")
            if len(env.hits) > before:
                bad.append("connected to a local address")
            if bad:
                findings.append(f"{param}={attack!r}: {bad}")
    assert findings == []


# -- normal use still works ---------------------------------------------------


def test_a_configured_remote_still_fetches(
    env: Env, tools: Any, tmp_path: Path
) -> None:
    handlers, _ = tools
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)], cwd=env.ws, check=True
    )
    try:
        assert "[ERROR]" not in handlers["git_fetch"]({"remote": "origin"})
        assert "Unknown remote" in handlers["git_fetch"]({"remote": str(bare)})
    finally:
        subprocess.run(["git", "remote", "remove", "origin"], cwd=env.ws, check=True)


def test_a_requirements_file_in_the_repo_is_still_read(env: Env, tools: Any) -> None:
    handlers, _ = tools
    (env.ws / "reqs-empty.txt").write_text("# nothing\n")
    result = handlers["check_target_repo_license_compliance"](
        {"requirements_filename": "reqs-empty.txt"}
    )
    assert "DENIED" not in result


def test_a_url_setting_still_shows_where_it_points() -> None:
    from app.agents.tool_security import _mask_secret_value

    masked = _mask_secret_value("DATABASE_URL", "postgresql://app:hunter2@db:5432/main")
    assert masked == "postgresql://***REDACTED@db:5432/main"
    assert _mask_secret_value("SERVICE_URL", "https://example.com/x") == (
        "https://example.com/x"
    )

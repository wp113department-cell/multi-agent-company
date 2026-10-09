"""Sol A05 (2026-10-09): secrets never enter an image.

Both build contexts (backend/ for the backend, runner and sandbox images;
the repository root for the web image) are filtered by their .dockerignore.
Proof with a real `docker build`: fake secret files are planted in a copy
of each context next to ordinary source files, the context is copied into
a scratch image with the real ignore rules, and the resulting filesystem is
exported and searched for the canary — in names and in contents.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CANARY = "CANARY-SECRET-a05-7f3e9b"
SECRET_FILES = [
    ".env",
    ".env.local",
    ".env.production",
    "app/.env",
    "deep/nested/.env.staging",
    "secrets/api.json",
    "server.pem",
    "certs/tls.key",
    "client.p12",
    "id_rsa",
    "id_ed25519",
    ".npmrc",
    ".pypirc",
    ".netrc",
]
KEPT_FILES = ["app/main.py", ".env.example", "README.md"]


def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return (
            subprocess.run(
                ["docker", "info"], capture_output=True, timeout=20
            ).returncode
            == 0
        )
    except Exception:
        return False


def _build(context: Path, out: Path) -> Path:
    (context / "Dockerfile.a05").write_text("FROM scratch\nCOPY . /ctx\n")
    r = subprocess.run(
        [
            "docker",
            "build",
            "-q",
            "-f",
            str(context / "Dockerfile.a05"),
            "--output",
            f"type=local,dest={out}",
            str(context),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert r.returncode == 0, r.stderr
    return out / "ctx"


@pytest.mark.parametrize(
    ("ignore_file", "prefix"),
    [("backend/.dockerignore", ""), (".dockerignore", "apps/web/")],
)
def test_planted_secrets_never_reach_the_image(
    tmp_path: Path, ignore_file: str, prefix: str
) -> None:
    if not _docker_ok():
        pytest.skip("Docker is not available")
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    shutil.copy(ROOT / ignore_file, ctx / ".dockerignore")
    for rel in SECRET_FILES:
        f = ctx / prefix / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"TOKEN={CANARY}\n")
    for rel in KEPT_FILES:
        f = ctx / prefix / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("ordinary source\n")
    image = _build(ctx, tmp_path / "out")
    shipped = [p for p in image.rglob("*") if p.is_file()]
    names = {str(p.relative_to(image)) for p in shipped}
    for rel in KEPT_FILES:
        assert f"{prefix}{rel}" in names, f"{rel} should be in the image"
    leaked = [n for n in names if any(n.endswith(s) for s in SECRET_FILES)]
    assert leaked == [], f"secret files in the image: {leaked}"
    for p in shipped:
        assert CANARY not in p.read_text(errors="replace"), p

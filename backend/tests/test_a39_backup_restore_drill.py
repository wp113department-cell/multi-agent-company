"""Sol A39 (2026-10-12): a real backup -> restore drill in throwaway
containers, checked against what the backup recorded.

Before: restore_db.sh only checked that alembic_version had a row, nothing
recorded what a backup contained, project folders were not backed up, and
nothing said whether saved credentials would still decrypt. Now the backup
writes a manifest (schema revision, every table's row count, the encryption
key's fingerprint) and archives the project folders, and the restore is
verified against that manifest.

Uses the real scripts in the real Postgres image on a private Docker
network; skips without Docker.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:pg16"
KEY = "drill-key-0123456789abcdefghijklmnopqrstuv="


def _docker(
    *args: str, check: bool = True, **kw: Any
) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=300, **kw
    )
    if check and r.returncode != 0:
        raise AssertionError(f"docker {' '.join(args[:3])}: {r.stderr[-1500:]}")
    return r


@pytest.fixture(scope="module")
def drill(tmp_path_factory: pytest.TempPathFactory) -> Any:
    if not shutil.which("docker") or _docker("info", check=False).returncode:
        pytest.skip("needs Docker")
    tag = uuid.uuid4().hex[:8]
    net, db = f"a39-{tag}", f"a39-db-{tag}"
    work = tmp_path_factory.mktemp("a39")
    (work / "backups").mkdir()
    repos = work / "repos" / "shop"
    repos.mkdir(parents=True)
    (repos / "README.md").write_text("the shop project\n")
    _docker("network", "create", net)
    _docker(
        "run", "-d", "--name", db, "--network", net,
        "-e", "POSTGRES_USER=g", "-e", "POSTGRES_PASSWORD=g", "-e", "POSTGRES_DB=src",
        IMAGE,
    )  # fmt: skip
    try:
        for _ in range(60):
            if (
                _docker(
                    "exec", db, "pg_isready", "-U", "g", "-d", "src", check=False
                ).returncode
                == 0
            ):
                break
            time.sleep(1)
        time.sleep(2)
        sql = (
            "CREATE TABLE alembic_version (version_num varchar(32) primary key);"
            "INSERT INTO alembic_version VALUES ('070');"
            "CREATE TABLE dev_tasks (id serial primary key, title text);"
            "INSERT INTO dev_tasks (title) SELECT 'task ' || g FROM generate_series(1, 37) g;"
            'CREATE TABLE "Odd Name" (x int); INSERT INTO "Odd Name" VALUES (1), (2);'
            "CREATE DATABASE restored;"
        )
        for stmt in sql.split(";"):
            if stmt.strip():
                _docker("exec", db, "psql", "-U", "g", "-d", "src", "-c", stmt)
        yield {"net": net, "db": db, "work": work}
    finally:
        _docker("rm", "-f", db, check=False)
        _docker("network", "rm", net, check=False)


def _script(
    drill: dict[str, Any], script: str, *args: str, **env: str
) -> subprocess.CompletedProcess[str]:
    envs: list[str] = []
    for k, v in env.items():
        envs += ["-e", f"{k}={v}"]
    return _docker(
        "run", "--rm", "--network", drill["net"], "--user", f"{os.getuid()}:{os.getgid()}",
        "-v", f"{ROOT / 'scripts'}:/scripts:ro",
        "-v", f"{drill['work'] / 'backups'}:/backups",
        "-v", f"{drill['work'] / 'repos'}:/data/repos:ro",
        *envs, "--entrypoint", "bash", IMAGE, f"/scripts/{script}", *args,
        check=False,
    )  # fmt: skip


def test_backup_then_restore_into_a_fresh_database(drill: dict[str, Any]) -> None:
    src = f"postgresql://g:g@{drill['db']}:5432/src"
    made = _script(
        drill, "backup_db.sh",
        DATABASE_URL=src, BACKUP_DIR="/backups", REPOS_DIR="/data/repos",
        CREDENTIAL_ENCRYPTION_KEY=KEY,
    )  # fmt: skip
    assert made.returncode == 0, made.stderr
    backups = drill["work"] / "backups"
    [dump] = list(backups.glob("gridiron_*.dump"))
    manifest = dump.with_suffix(".manifest").read_text()
    assert "revision=070" in manifest
    assert "rows.dev_tasks=37" in manifest and "rows.Odd Name=2" in manifest
    assert "key_fingerprint=" in manifest and KEY not in manifest  # never the key
    assert list(backups.glob("repos_*.tar.gz"))  # project folders archived
    assert '"ok": true' in (backups / "last_backup.json").read_text()
    drill["dump"] = dump.name

    restored = f"postgresql://g:g@{drill['db']}:5432/restored"
    out = _script(
        drill, "restore_db.sh", f"/backups/{dump.name}", "--yes",
        DATABASE_URL=restored, CREDENTIAL_ENCRYPTION_KEY=KEY,
    )  # fmt: skip
    assert out.returncode == 0, out.stderr
    assert "Restore verified: revision 070" in out.stdout
    assert "project folders" in out.stdout.lower()


def test_a_restore_that_does_not_match_the_backup_is_reported(
    drill: dict[str, Any],
) -> None:
    dump = drill.get("dump")
    if not dump:
        pytest.skip("needs the backup from the previous test")
    manifest = drill["work"] / "backups" / dump.replace(".dump", ".manifest")
    original = manifest.read_text()
    manifest.write_text(original.replace("rows.dev_tasks=37", "rows.dev_tasks=38"))
    try:
        restored = f"postgresql://g:g@{drill['db']}:5432/restored"
        bad_rows = _script(
            drill, "restore_db.sh", f"/backups/{dump}", "--yes",
            DATABASE_URL=restored, CREDENTIAL_ENCRYPTION_KEY=KEY,
        )  # fmt: skip
        assert bad_rows.returncode == 1
        assert "MISMATCH dev_tasks: backup 38 rows, restored 37" in bad_rows.stderr
    finally:
        manifest.write_text(original)
    wrong_key = _script(
        drill, "restore_db.sh", f"/backups/{dump}", "--yes",
        DATABASE_URL=f"postgresql://g:g@{drill['db']}:5432/restored",
        CREDENTIAL_ENCRYPTION_KEY="some-other-key",
    )  # fmt: skip
    assert wrong_key.returncode == 1 and "MISMATCH encryption key" in wrong_key.stderr


def test_a_failed_backup_is_recorded(drill: dict[str, Any]) -> None:
    failed = _script(
        drill, "backup_db.sh",
        DATABASE_URL=f"postgresql://g:wrong@{drill['db']}:5432/src", BACKUP_DIR="/backups",
    )  # fmt: skip
    assert failed.returncode != 0
    status = (drill["work"] / "backups" / "last_backup.json").read_text()
    assert '"ok": false' in status


def test_health_reports_the_last_backup(tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from app.main import _backup_state

    status = tmp_path / "last_backup.json"
    cfg = SimpleNamespace(backup_status_file=str(status), backup_interval_seconds=3600)
    assert _backup_state(cfg) == "none yet"
    status.write_text('{"ok": false, "at": "2026-10-12T01:00:00Z"}')
    assert _backup_state(cfg).startswith("failed")
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    status.write_text(f'{{"ok": true, "at": "{old}"}}')
    assert _backup_state(cfg).startswith("stale")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status.write_text(f'{{"ok": true, "at": "{now}"}}')
    assert _backup_state(cfg).startswith("ok")

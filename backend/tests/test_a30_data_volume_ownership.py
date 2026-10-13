"""Sol A30 (2026-10-12): the non-root backend can write to fresh /data
volumes.

docker-compose.prod.yml mounts fresh named volumes at /data, /data/worktrees
and /data/repos. Docker gives an empty named volume the owner of the folder
it is mounted on, so the image must create these folders owned by appuser
before switching to it. Proven with real fresh volumes on 2026-10-13: as
appuser the image cloned into /data/repos, added a worktree in
/data/worktrees and wrote /data/bg-processes.json. This test keeps the
Dockerfile rule in place (a full image build is too slow for every run).
"""

from __future__ import annotations

from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def test_data_folders_are_created_for_appuser_before_switching_user() -> None:
    lines = DOCKERFILE.read_text().splitlines()
    make = next(
        i
        for i, line in enumerate(lines)
        if "mkdir -p /data/worktrees /data/repos" in line
        and "chown -R appuser:appuser /data" in line
    )
    switch = next(i for i, line in enumerate(lines) if line.strip() == "USER appuser")
    assert make < switch

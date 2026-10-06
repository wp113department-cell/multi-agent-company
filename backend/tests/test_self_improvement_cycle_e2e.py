"""The fleet self-improvement cycle, end to end (audit 15, 2026-10-06).

scan finds a bug → EnhancementRequest row (pending) → owner approves →
agent_debugger's APPLY phase fixes it in its OWN worktree/branch → runs the
tests → commits → merged into the live branch → quality monitor sees a
decline → automatic `git revert`.

Real Postgres, real git, real pytest run by the agent's run_tests tool; the
model is an in-process mock (no network, no API key) that plays the agent's
turns. The live repo is a throwaway git repo with a genuine bug.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import delete

from app.config import get_settings
from app.db.models import EnhancementRequest
from app.db.session import get_async_session

_BUG = "def add(a: int, b: int) -> int:\n    return a - b\n"
_FIXED = "def add(a: int, b: int) -> int:\n    return a + b\n"
_TEST = "from calc import add\n\n\ndef test_add() -> None:\n    assert add(2, 3) == 5\n"
_TITLE = "add() subtracts instead of adding (audit15 e2e)"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _tool_use(n: int, name: str, inp: dict[str, Any]) -> Any:
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="tool_use", id=f"tu{n}_{name}", name=name, input=inp)
        ],
        usage=SimpleNamespace(input_tokens=40, output_tokens=12),
        stop_reason="tool_use",
    )


_APPLY_STEPS: list[tuple[str, dict[str, Any]]] = [
    ("read_file", {"path": "calc.py"}),
    ("edit_file", {"path": "calc.py", "old_string": "a - b", "new_string": "a + b"}),
    ("run_tests", {"path": "tests"}),
    (
        "git_commit_change",
        {"files": ["calc.py"], "message": "Fix add(): add, not subtract"},
    ),
    ("submit_fix", {"summary": "add() now adds; regression test passes"}),
]


def _model(**kw: Any) -> Any:
    tools = {t["name"] for t in kw.get("tools") or []}
    turn = sum(1 for m in kw.get("messages", []) if m.get("role") == "assistant")
    if "submit_enhancement_request" in tools:  # SCAN phase
        return _tool_use(
            turn,
            "submit_enhancement_request",
            {
                "title": _TITLE,
                "description": "calc.add returns a - b; tests/test_calc.py fails.",
                "category": "bug",
                "priority": "medium",
            },
        )
    if "submit_fix" in tools:  # APPLY phase
        name, inp = _APPLY_STEPS[min(turn, len(_APPLY_STEPS) - 1)]
        return _tool_use(turn, name, inp)
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text="{}")],
        usage=SimpleNamespace(input_tokens=5, output_tokens=2),
        stop_reason="end_turn",
    )


@pytest.fixture()
def live_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "live"
    (repo / "backend" / "tests").mkdir(parents=True)
    (repo / "backend" / "calc.py").write_text(_BUG)
    (repo / "backend" / "tests" / "test_calc.py").write_text(_TEST)
    (repo / "backend" / "conftest.py").write_text("")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init with a real bug")
    # The agent's run_tests activates <repo>/.venv: give it this project's.
    (repo / "backend" / ".venv").symlink_to(
        Path(__file__).resolve().parents[1] / ".venv"
    )
    s = get_settings()
    monkeypatch.setattr(s, "fleet_self_repo_path", str(repo / "backend"))
    monkeypatch.setattr(s, "worktrees_dir", str(tmp_path / "wt"))
    monkeypatch.setattr(s, "allowed_workspace_parent", str(tmp_path))
    monkeypatch.setattr(s, "cost_mode", "economy")
    return repo


async def _cleanup() -> None:
    async with get_async_session() as db:
        await db.execute(
            delete(EnhancementRequest).where(EnhancementRequest.title == _TITLE)
        )
        await db.commit()


@pytest.mark.asyncio
async def test_scan_approve_apply_merge_and_auto_revert(live_repo: Path) -> None:
    from app.agents.agent_debugger import run_agent_debugger_scan
    from app.api.fleet_dashboard import approve_request
    from app.fleet.enhancement_rollback import (
        QualityDeclineReport,
        check_and_handle_quality_decline,
    )

    await _cleanup()
    try:
        with patch("anthropic.Anthropic") as cls:
            cls.return_value.messages.create.side_effect = _model

            # 1. SCAN: the agent files a pending request (read-only phase).
            await asyncio.to_thread(run_agent_debugger_scan)
            async with get_async_session() as db:
                from sqlalchemy import select

                row = (
                    await db.execute(
                        select(EnhancementRequest).where(
                            EnhancementRequest.title == _TITLE
                        )
                    )
                ).scalar_one()
                assert row.status == "pending" and row.agent_name == "agent_debugger"
                request_id = row.id
            assert (live_repo / "backend" / "calc.py").read_text() == _BUG

            # 2. APPROVE: the real endpoint starts the APPLY phase.
            async with get_async_session() as db:
                await approve_request(request_id, None, db, "owner")

            # 3. APPLY runs in its own worktree, tests, commits, merges back.
            for _ in range(240):
                async with get_async_session() as db:
                    row = await db.get(EnhancementRequest, request_id)
                    if row is not None and row.status not in ("pending", "in_progress"):
                        break
                await asyncio.sleep(0.5)

        async with get_async_session() as db:
            row = await db.get(EnhancementRequest, request_id)
            assert row is not None
            assert row.status == "completed", (row.status, row.error)
            assert row.commit_sha and row.quality_check_status == "monitoring"
            assert (live_repo / "backend" / "calc.py").read_text() == _FIXED
            assert (
                _git(live_repo, "merge-base", "--is-ancestor", row.commit_sha, "HEAD")
                == ""
            )
            # The worktree and branch are removed right after the status write.
            for _ in range(40):
                if "fleet/enh-" not in _git(live_repo, "branch"):
                    break
                await asyncio.sleep(0.25)
            assert "fleet/enh-" not in _git(live_repo, "branch")  # merged, removed

            # 4. A measured decline triggers the automatic revert.
            decline = QualityDeclineReport(
                request_id=request_id,
                agent_name="agent_debugger",
                pre_success_rate=0.9,
                pre_run_count=10,
                post_success_rate=0.5,
                post_run_count=10,
                decline=0.4,
                declined=True,
            )
            with patch(
                "app.fleet.enhancement_rollback.evaluate_quality_decline",
                return_value=decline,
            ):
                outcome = await check_and_handle_quality_decline(
                    db,
                    row,
                    repo_path=str(live_repo / "backend"),
                    pre_window_hours=24,
                    min_post_window_hours=0,
                    min_runs=1,
                    decline_threshold=0.1,
                )
            assert outcome["action"] == "rolled_back", outcome
            assert row.quality_check_status == "rolled_back" and row.rollback_commit_sha
            assert (live_repo / "backend" / "calc.py").read_text() == _BUG
    finally:
        await _cleanup()

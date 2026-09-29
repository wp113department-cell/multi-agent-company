"""#405 (2026-09-28) — PromptRegistry.deploy() now folds a real diff of
the deployed change into memory (embed_prompt_change_sync), mirroring the
existing test_prompt_registry.py's own real-lifecycle conventions (real
Postgres PromptVersion rows + real roles/*.md writes, cleaned up in
try/finally). embed_prompt_change_sync itself is mocked here — its own
correctness (real embedding + real MemoryEmbedding row) is covered by
test_prompt_change_memory.py.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from app.fleet.prompt_registry import PromptRegistry

_ROLES_DIR = Path(__file__).parent.parent / "roles"


def _cleanup(role_name: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import PromptVersion

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(PromptVersion).where(PromptVersion.role_name == role_name)
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())
    role_file = _ROLES_DIR / f"{role_name}.md"
    if role_file.exists():
        role_file.unlink()


def test_first_deploy_diffs_against_empty_content() -> None:
    role_name = "td_pr_mem_first_deploy"
    try:
        with patch("app.memory.store.embed_prompt_change_sync") as mock_embed:
            pr = PromptRegistry()
            v1 = pr.propose(role_name, "Brand new role content", proposed_by="tester")
            pr.submit_for_review(v1.id)
            pr.approve(v1.id, "human1")
            pr.deploy(v1.id)

        mock_embed.assert_called_once()
        call_kwargs = mock_embed.call_args.kwargs
        assert call_kwargs["role_name"] == role_name
        assert "+Brand new role content" in call_kwargs["diff_text"]
        assert call_kwargs["version_id"] == v1.id
        assert call_kwargs["proposed_by"] == "tester"
    finally:
        _cleanup(role_name)


def test_second_deploy_diffs_against_the_real_parent_content() -> None:
    role_name = "td_pr_mem_second_deploy"
    try:
        with patch("app.memory.store.embed_prompt_change_sync") as mock_embed:
            pr = PromptRegistry()
            v1 = pr.propose(role_name, "Line one\nLine two\n", proposed_by="tester")
            pr.submit_for_review(v1.id)
            pr.approve(v1.id, "human1")
            pr.deploy(v1.id)

            v2 = pr.propose(
                role_name, "Line one\nLine two changed\n", proposed_by="tester"
            )
            pr.submit_for_review(v2.id)
            pr.approve(v2.id, "human1")
            pr.deploy(v2.id)

        assert mock_embed.call_count == 2
        second_call_kwargs = mock_embed.call_args_list[1].kwargs
        assert "-Line two" in second_call_kwargs["diff_text"]
        assert "+Line two changed" in second_call_kwargs["diff_text"]
        assert second_call_kwargs["version_id"] == v2.id
    finally:
        _cleanup(role_name)


def test_deploy_succeeds_even_if_memory_write_raises() -> None:
    role_name = "td_pr_mem_failure_non_fatal"
    try:
        with patch(
            "app.memory.store.embed_prompt_change_sync",
            side_effect=RuntimeError("boom"),
        ):
            pr = PromptRegistry()
            v1 = pr.propose(role_name, "content", proposed_by="tester")
            pr.submit_for_review(v1.id)
            pr.approve(v1.id, "human1")
            deployed = pr.deploy(v1.id)

        assert deployed.status == "deployed"
        role_file = _ROLES_DIR / f"{role_name}.md"
        assert role_file.read_text(encoding="utf-8") == "content"
    finally:
        _cleanup(role_name)

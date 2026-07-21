"""Prompt Registry — Day 11.

Repo research (repos/roo-code/src/services/checkpoints/ShadowCheckpointService.ts,
repos/langgraph/libs/checkpoint's CheckpointMetadata parent-pointer lineage):
neither repo has an approval-gate/review state machine — that part is this
module's own design. What's borrowed: a "version" is an immutable snapshot
(never edited in place), restore is a pointer-swap to a target snapshot's
content (not a replay of edits), and each version records what it supersedes.

app.agents.base.load_role() reads backend/roles/{role_name}.md fresh from disk
on every call — deploy()/rollback() write directly to that same file, so
load_role() needs zero changes.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.policy.engine import check_path

_ROLES_DIR = Path(__file__).parent.parent.parent / "roles"

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"in_review"},
    "in_review": {"approved", "rejected"},
    "approved": {"deployed"},
    "deployed": {"superseded"},
    "superseded": {"deployed"},  # rollback re-deploys a superseded version
}


class InvalidTransition(Exception):
    def __init__(self, version_id: int, from_status: str, to_status: str) -> None:
        self.version_id = version_id
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Version {version_id}: illegal transition {from_status!r} -> {to_status!r}"
        )


@dataclass
class PromptVersionRecord:
    id: int
    role_name: str
    version_number: int
    content: str
    content_hash: str
    status: str
    parent_version_id: int | None
    proposed_by: str | None
    approved_by: str | None
    created_at: str
    deployed_at: str | None


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _to_record(row: Any) -> PromptVersionRecord:
    return PromptVersionRecord(
        id=row.id,
        role_name=row.role_name,
        version_number=row.version_number,
        content=row.content,
        content_hash=row.content_hash,
        status=row.status,
        parent_version_id=row.parent_version_id,
        proposed_by=row.proposed_by,
        approved_by=row.approved_by,
        created_at=row.created_at.isoformat() if row.created_at else "",
        deployed_at=row.deployed_at.isoformat() if row.deployed_at else None,
    )


def _new_isolated_db_engine() -> Any:
    """A throwaway async engine, never the shared app.db.session singleton —
    see feedback_asyncio_isolated_engine: reusing one engine across multiple
    asyncio.run() calls in the same process raises 'attached to a different
    loop'. A fresh, disposed-after-use engine per call is always correct."""
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _role_file_path(role_name: str) -> Path:
    """Resolve role_name to a path strictly confined to backend/roles/ —
    defense-in-depth against a malformed role_name even though check_path()
    doesn't deny roles/ today."""
    candidate = (_ROLES_DIR / f"{role_name}.md").resolve()
    roles_dir_resolved = _ROLES_DIR.resolve()
    if not (
        candidate == roles_dir_resolved / f"{role_name}.md"
        and candidate.parent == roles_dir_resolved
    ):
        raise ValueError(f"role_name {role_name!r} resolves outside backend/roles/")
    result = check_path(str(candidate))
    if not result.allowed:
        raise ValueError(f"Policy denied writing role file: {result.reason}")
    return candidate


async def _get_deployed(role_name: str) -> PromptVersionRecord | None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import PromptVersion

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = (
                await session.execute(
                    select(PromptVersion)
                    .where(
                        PromptVersion.role_name == role_name,
                        PromptVersion.status == "deployed",
                    )
                    .order_by(PromptVersion.version_number.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return _to_record(row) if row is not None else None
    finally:
        await engine.dispose()


async def _propose(
    role_name: str, content: str, proposed_by: str | None
) -> PromptVersionRecord:
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import PromptVersion

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            max_version = (
                await session.execute(
                    select(func.max(PromptVersion.version_number)).where(
                        PromptVersion.role_name == role_name
                    )
                )
            ).scalar_one()
            deployed_row = (
                await session.execute(
                    select(PromptVersion)
                    .where(
                        PromptVersion.role_name == role_name,
                        PromptVersion.status == "deployed",
                    )
                    .order_by(PromptVersion.version_number.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            hash_ = _content_hash(content)
            if deployed_row is not None and deployed_row.content_hash == hash_:
                return _to_record(
                    deployed_row
                )  # no-op: identical to what's already deployed

            row = PromptVersion(
                role_name=role_name,
                version_number=(max_version or 0) + 1,
                content=content,
                content_hash=hash_,
                status="draft",
                parent_version_id=deployed_row.id if deployed_row is not None else None,
                proposed_by=proposed_by,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_record(row)
    finally:
        await engine.dispose()


async def _get_by_id(version_id: int) -> Any:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import PromptVersion

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return (
                await session.execute(
                    select(PromptVersion).where(PromptVersion.id == version_id)
                )
            ).scalar_one_or_none()
    finally:
        await engine.dispose()


async def _transition(
    version_id: int, to_status: str, *, approved_by: str | None = None
) -> PromptVersionRecord:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import PromptVersion

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await session.get(PromptVersion, version_id)
            if row is None:
                raise ValueError(f"No prompt version with id={version_id}")
            if to_status not in _VALID_TRANSITIONS.get(row.status, set()):
                raise InvalidTransition(version_id, row.status, to_status)
            row.status = to_status
            if to_status == "approved":
                row.approved_by = approved_by
            if to_status == "deployed":
                row.deployed_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(row)
            return _to_record(row)
    finally:
        await engine.dispose()


async def _supersede_current_deployed(role_name: str, except_id: int) -> None:
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import PromptVersion

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(
                update(PromptVersion)
                .where(
                    PromptVersion.role_name == role_name,
                    PromptVersion.status == "deployed",
                    PromptVersion.id != except_id,
                )
                .values(status="superseded")
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _get_history(role_name: str) -> list[PromptVersionRecord]:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import PromptVersion

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            rows = (
                (
                    await session.execute(
                        select(PromptVersion)
                        .where(PromptVersion.role_name == role_name)
                        .order_by(PromptVersion.version_number.asc())
                    )
                )
                .scalars()
                .all()
            )
            return [_to_record(r) for r in rows]
    finally:
        await engine.dispose()


async def _most_recent_superseded(role_name: str) -> PromptVersionRecord | None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import PromptVersion

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = (
                await session.execute(
                    select(PromptVersion)
                    .where(
                        PromptVersion.role_name == role_name,
                        PromptVersion.status == "superseded",
                    )
                    .order_by(PromptVersion.version_number.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return _to_record(row) if row is not None else None
    finally:
        await engine.dispose()


class PromptRegistry:
    def propose(
        self, role_name: str, content: str, proposed_by: str | None = None
    ) -> PromptVersionRecord:
        return asyncio.run(_propose(role_name, content, proposed_by))

    def submit_for_review(self, version_id: int) -> PromptVersionRecord:
        return asyncio.run(_transition(version_id, "in_review"))

    def approve(self, version_id: int, approved_by: str) -> PromptVersionRecord:
        return asyncio.run(_transition(version_id, "approved", approved_by=approved_by))

    def reject(self, version_id: int) -> PromptVersionRecord:
        return asyncio.run(_transition(version_id, "rejected"))

    def deploy(self, version_id: int) -> PromptVersionRecord:
        """Requires status == 'approved'. Gates on regression_detector before
        writing anything — tests passing alone is not sufficient."""
        row = asyncio.run(_get_by_id(version_id))
        if row is None:
            raise ValueError(f"No prompt version with id={version_id}")
        if row.status != "approved":
            raise InvalidTransition(version_id, row.status, "deployed")

        from app.fleet.regression_detector import get_regression_detector

        get_regression_detector().gate_deploy(
            row.role_name
        )  # raises DeploymentBlocked if regressed

        deployed = asyncio.run(_transition(version_id, "deployed"))
        asyncio.run(_supersede_current_deployed(row.role_name, except_id=version_id))
        _role_file_path(row.role_name).write_text(row.content, encoding="utf-8")
        return deployed

    def rollback(self, role_name: str) -> PromptVersionRecord:
        """Restore the most recently superseded version for role_name — skips
        the approval gate since it was already approved and deployed once."""
        prior = asyncio.run(_most_recent_superseded(role_name))
        if prior is None:
            raise ValueError(
                f"No superseded version to roll back to for role_name={role_name!r}"
            )

        current = asyncio.run(_get_deployed(role_name))
        restored = asyncio.run(_transition(prior.id, "deployed"))
        if current is not None:
            asyncio.run(_supersede_current_deployed(role_name, except_id=prior.id))
        _role_file_path(role_name).write_text(prior.content, encoding="utf-8")
        return restored

    def get_history(self, role_name: str) -> list[PromptVersionRecord]:
        return asyncio.run(_get_history(role_name))

    def get_deployed(self, role_name: str) -> PromptVersionRecord | None:
        return asyncio.run(_get_deployed(role_name))


_prompt_registry_singleton: PromptRegistry | None = None


def get_prompt_registry() -> PromptRegistry:
    global _prompt_registry_singleton
    if _prompt_registry_singleton is None:
        _prompt_registry_singleton = PromptRegistry()
    return _prompt_registry_singleton

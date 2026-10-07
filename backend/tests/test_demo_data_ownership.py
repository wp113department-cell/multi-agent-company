"""Demo creation/removal must preserve real folders and shared database rows."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DevTask, Epic, Goal, Project, Repo, Roadmap, RoadmapItem
from app.db.session import get_session_factory
from app.services.demo import DEMO_CREATOR
from scripts.seed_demo_data import DEMO_FOLDER_MARKER, remove_demo, seed


@pytest_asyncio.fixture
async def owned_db() -> AsyncIterator[tuple[AsyncSession, str]]:
    token = f"ownership-test-{uuid.uuid4().hex}"
    async with get_session_factory()() as db:
        try:
            yield db, token
        finally:
            await db.rollback()
            await db.execute(delete(DevTask).where(DevTask.created_by == token))
            await db.execute(delete(Roadmap).where(Roadmap.summary == token))
            await db.execute(delete(Project).where(Project.created_by == token))
            await db.execute(delete(Repo).where(Repo.name == token))
            await db.commit()
            # Once real references are removed, retained demo rows can safely
            # be removed too. Cleanup uses only the rows created by this test.
            await remove_demo(db)


@pytest.mark.parametrize("registered", [False, True])
async def test_seed_avoids_existing_real_folder_and_registered_repo(
    owned_db: tuple[AsyncSession, str], tmp_path: Path, registered: bool
) -> None:
    db, token = owned_db
    real_folder = tmp_path / "customer-support-assistant"
    real_folder.mkdir()
    (real_folder / "README.md").write_text("User's actual project\n")
    original_files = {p.relative_to(real_folder) for p in real_folder.rglob("*")}
    real_repo_id = None
    if registered:
        # Even a leftover demo folder marker does not authorize reuse of a
        # repo that a real project has registered at that path.
        (real_folder / DEMO_FOLDER_MARKER).write_text(DEMO_CREATOR)
        original_files.add(Path(DEMO_FOLDER_MARKER))
        repo = Repo(name=token, local_path=str(real_folder), status="ready")
        db.add(repo)
        await db.flush()
        real_repo_id = repo.id
        db.add(
            Project(
                name=token,
                repo_id=repo.id,
                local_path=str(real_folder),
                created_by=token,
            )
        )
        await db.commit()

    await seed(tmp_path)
    demo_projects = list(
        (
            await db.execute(
                select(Project.local_path, Project.repo_id).where(
                    Project.created_by == DEMO_CREATOR
                )
            )
        ).all()
    )
    assert len(demo_projects) == 3
    assert all(path != str(real_folder) for path, _ in demo_projects)
    if registered:
        assert all(repo_id != real_repo_id for _, repo_id in demo_projects)
    assert (real_folder / "README.md").read_text() == "User's actual project\n"
    assert {
        p.relative_to(real_folder) for p in real_folder.rglob("*")
    } == original_files

    # Removal and another seed reuse the owned alternate folder, retaining
    # edits there and leaving the real folder entirely unchanged.
    alternate = next(
        Path(path) for path, _ in demo_projects if "customer-support-assistant" in path
    )
    (alternate / "README.md").write_text("User edit in demo folder\n")
    await seed(tmp_path)
    assert (alternate / "README.md").read_text() == "User edit in demo folder\n"
    assert (real_folder / "README.md").read_text() == "User's actual project\n"
    await remove_demo(db)
    if registered:
        assert await db.scalar(select(Repo.id).where(Repo.id == real_repo_id))
        assert await db.scalar(select(Project.id).where(Project.created_by == token))


async def test_remove_preserves_real_project_task_and_roadmap_sharing_demo_repo(
    owned_db: tuple[AsyncSession, str], tmp_path: Path
) -> None:
    db, token = owned_db
    await seed(tmp_path)
    demo_project = (
        await db.execute(
            select(Project.id, Project.repo_id)
            .where(Project.created_by == DEMO_CREATOR)
            .order_by(Project.id)
            .limit(1)
        )
    ).one()
    repo_id = demo_project.repo_id
    demo_roadmap_id = await db.scalar(
        select(Roadmap.id).where(Roadmap.repo_id == repo_id)
    )
    real_project = Project(name=token, repo_id=repo_id, created_by=token)
    db.add(real_project)
    await db.flush()
    real_task = DevTask(
        title=token,
        description="Real work",
        repo_id=repo_id,
        project_id=real_project.id,
        created_by=token,
    )
    real_roadmap = Roadmap(repo_id=repo_id, summary=token)
    db.add_all([real_task, real_roadmap])
    await db.flush()
    item = RoadmapItem(
        roadmap_id=real_roadmap.id, phase="Now", initiative="Real initiative"
    )
    db.add(item)
    await db.commit()

    assert await remove_demo(db) == 3
    assert await db.scalar(select(Repo.id).where(Repo.id == repo_id)) == repo_id
    assert (
        await db.scalar(select(Project.repo_id).where(Project.id == real_project.id))
        == repo_id
    )
    assert (
        await db.execute(
            select(DevTask.repo_id, DevTask.project_id).where(
                DevTask.id == real_task.id
            )
        )
    ).one() == (repo_id, real_project.id)
    assert (
        await db.scalar(select(Roadmap.repo_id).where(Roadmap.id == real_roadmap.id))
        == repo_id
    )
    assert (
        await db.scalar(select(RoadmapItem.initiative).where(RoadmapItem.id == item.id))
        == "Real initiative"
    )
    assert (
        await db.scalar(select(Roadmap.id).where(Roadmap.id == demo_roadmap_id)) is None
    )


async def test_remove_preserves_demo_project_labels_referenced_by_real_task(
    owned_db: tuple[AsyncSession, str], tmp_path: Path
) -> None:
    db, token = owned_db
    await seed(tmp_path)
    project_id, repo_id = (
        await db.execute(
            select(Project.id, Project.repo_id)
            .where(Project.created_by == DEMO_CREATOR)
            .order_by(Project.id)
            .limit(1)
        )
    ).one()
    goal_id = await db.scalar(
        select(Goal.goal_id).where(Goal.project_id == project_id).limit(1)
    )
    epic_id = await db.scalar(
        select(Epic.epic_id).where(Epic.project_id == project_id).limit(1)
    )
    task = DevTask(
        title=token,
        description="A real task attached to demo labels",
        created_by=token,
        project_id=project_id,
        repo_id=repo_id,
        goal_id=goal_id,
        epic_id=epic_id,
    )
    db.add(task)
    await db.commit()

    assert await remove_demo(db) == 2
    assert (
        await db.execute(
            select(
                DevTask.project_id, DevTask.repo_id, DevTask.goal_id, DevTask.epic_id
            ).where(DevTask.id == task.id)
        )
    ).one() == (project_id, repo_id, goal_id, epic_id)
    assert await db.scalar(select(Project.id).where(Project.id == project_id))
    assert await db.scalar(select(Goal.goal_id).where(Goal.goal_id == goal_id))
    assert await db.scalar(select(Epic.epic_id).where(Epic.epic_id == epic_id))


async def test_remove_does_not_infer_legacy_repo_or_roadmap_ownership(
    owned_db: tuple[AsyncSession, str], tmp_path: Path
) -> None:
    db, token = owned_db
    repo = Repo(name=token, local_path=str(tmp_path), status="ready")
    db.add(repo)
    await db.flush()
    legacy_demo = Project(name="Legacy demo", repo_id=repo.id, created_by=DEMO_CREATOR)
    roadmap = Roadmap(repo_id=repo.id, summary=token)
    db.add_all([legacy_demo, roadmap])
    await db.commit()

    assert await remove_demo(db) == 1
    # Even without other repo references, an unmarked repo/roadmap might be
    # real. A demo project's repo_id is not evidence that it created them.
    assert await db.scalar(select(Repo.id).where(Repo.id == repo.id)) == repo.id
    assert (
        await db.scalar(select(Roadmap.repo_id).where(Roadmap.id == roadmap.id))
        == repo.id
    )

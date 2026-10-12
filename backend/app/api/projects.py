"""Projects API (UI redesign, 2026-10-07).

A project is what the user names and works on. Its code lives in a local
folder, a GitHub repository, or both; when a folder exists the project points
at the repos row every task-execution path already resolves its working
directory from, so tasks run exactly as before.

GET    /api/projects                     — list (with task counts), for Start
POST   /api/projects                     — create from one of 4 setups
GET    /api/projects/{id}                — detail: goals, epics, task history
PATCH  /api/projects/{id}                — rename / describe
POST   /api/projects/{id}/open           — mark opened, make its folder active
DELETE /api/projects/{id}                — remove from the app (files untouched)
POST   /api/projects/{id}/goals          — add a goal label (no AI run)
POST   /api/projects/{id}/epics          — add an epic label (no AI run)

The four setups:
  local_existing  — use a folder that already exists on this computer
  local_new       — create a new folder for a brand-new project
  github_existing — clone a GitHub repository (public, or private + token)
  github_new      — create a GitHub repository (needs a GitHub token), clone it
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.db.models import DevTask, Epic, Goal, Project, Repo
from app.api.budget_gate import require_daily_budget
from app.middleware.rbac import require_approver, require_authenticated
from app.services import git_service, workspace_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])

_FOLDER_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_BOT_NAME = "Multi Agentic Company"
_BOT_EMAIL = "bot@multi-agentic.local"


def slugify(name: str) -> str:
    """A folder/repository-safe name from a project name."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-.").lower()
    return slug[:100] or "project"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    setup: Literal["local_existing", "local_new", "github_existing", "github_new"]
    # local_existing
    path: str | None = None
    # local_new / github_new: where the folder is created; local_new may name it
    parent_path: str | None = None
    folder_name: str | None = None
    # github_existing
    github_url: str | None = None
    branch: str | None = None
    full_history: bool = False
    # github_new
    repo_name: str | None = None
    visibility: Literal["public", "private"] = "private"
    # private github_existing (or overriding the saved token): used for this
    # repository only, stored encrypted per repository, never returned.
    github_token: str | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Project name must not be blank")
        return v.strip()


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    # W6: branch approved work goes to; "" or null = automatic (the
    # repository's default branch)
    target_branch: str | None = Field(None, max_length=200)


class LabelRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_dict(
    p: Project, repo: Repo | None = None, counts: dict[str, int] | None = None
) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "setup": p.source,
        "localPath": p.local_path,
        "githubUrl": p.github_url,
        "targetBranch": p.target_branch,
        "visibility": p.visibility,
        "repoId": p.repo_id,
        # cloning | ready | error (from the repository), "ready" for a
        # local folder, "none" when the project has no code location yet
        "status": (repo.status if repo else ("ready" if p.local_path else "none")),
        "error": repo.error_msg if repo else None,
        "createdAt": p.created_at.isoformat() if p.created_at else None,
        "lastOpenedAt": p.last_opened_at.isoformat() if p.last_opened_at else None,
        "taskCounts": counts or {},
    }


def _check_in_workspace(path: str, what: str) -> str:
    settings = get_settings()
    if not path or not os.path.isabs(path) or "\x00" in path:
        raise HTTPException(
            status_code=400, detail=f"{what} must be a full folder path."
        )
    if not workspace_service.is_within(path, settings.allowed_workspace_parent):
        raise HTTPException(
            status_code=400,
            detail=f"{what} must be inside your workspace folder "
            f"({settings.workspace_host_label or settings.allowed_workspace_parent}).",
        )
    return os.path.realpath(path)


async def _git(cwd: str, *args: str) -> tuple[int, str]:
    rc, out, err, _ = await git_service.run_git_process(
        ["git", *args], cwd, None, timeout=120
    )
    return rc, (out + err).decode(errors="replace")


async def _ensure_git_with_commit(folder: str, *, readme_title: str | None) -> None:
    """Task worktrees need a git repository with at least one commit.

    A folder that is already a git repository with commits is left exactly
    as it is. Otherwise git tracking is started and a first local commit is
    made: of the existing files (an existing project), or of a short README
    (a brand-new project). `.env` files are excluded through the repository's
    own, never-committed .git/info/exclude. Nothing is pushed anywhere."""
    if (Path(folder) / ".git").exists():
        rc, out = await _git(folder, "log", "--oneline", "-1")
        if rc == 0 and out.strip():
            return
    else:
        rc, out = await _git(folder, "init")
        if rc != 0:
            raise HTTPException(status_code=500, detail=f"git init failed: {out[:500]}")
    exclude = Path(folder) / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text() if exclude.exists() else ""
    if ".env" not in existing.split():
        exclude.write_text(existing.rstrip("\n") + "\n.env\n.env.*\n!.env.example\n")
    if readme_title is not None and [p.name for p in Path(folder).iterdir()] == [
        ".git"
    ]:
        (Path(folder) / "README.md").write_text(f"# {readme_title}\n")
    rc, out = await _git(folder, "add", "-A")
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"git add failed: {out[:500]}")
    rc, out = await _git(
        folder,
        "-c",
        f"user.name={_BOT_NAME}",
        "-c",
        f"user.email={_BOT_EMAIL}",
        "commit",
        "--allow-empty",
        "-m",
        "Start tracking project with Multi Agentic Company",
    )
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"git commit failed: {out[:500]}")


async def _local_repo_row(db: AsyncSession, folder: str) -> Repo:
    """The repos row for a local folder (reused if the folder is known)."""
    existing = (
        await db.execute(select(Repo).where(Repo.local_path == folder))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    repo = Repo(
        github_url=None,
        name=Path(folder).name,
        local_path=folder,
        status="ready",
        cloned_at=datetime.now(timezone.utc),
    )
    db.add(repo)
    await db.flush()
    return repo


async def _github_token(db: AsyncSession, explicit: str | None) -> str | None:
    if explicit and explicit.strip():
        return explicit.strip()
    from app.db.repository import get_setting

    return (
        (await get_setting(db, "github_token")) or get_settings().github_token or None
    )


async def _create_github_repo(token: str, name: str, private: bool) -> str:
    """Create a repository for the token's user; returns its https URL."""
    import httpx

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            "https://api.github.com/user/repos",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"name": name, "private": private, "auto_init": True},
        )
    if res.status_code == 422:
        raise HTTPException(
            status_code=400,
            detail=f"GitHub refused the name {name!r} (it may already exist).",
        )
    if res.status_code in (401, 403):
        raise HTTPException(
            status_code=400,
            detail="GitHub rejected the token. It needs permission to create "
            "repositories (classic token: 'repo' scope).",
        )
    if res.status_code >= 300:
        raise HTTPException(
            status_code=502, detail=f"GitHub error {res.status_code}: {res.text[:300]}"
        )
    return str(res.json()["html_url"])


async def _clone_for_project(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    actor: str,
    *,
    url: str,
    dest: str | None,
    branch: str | None,
    token: str | None,
    full_history: bool,
) -> int:
    """Start a clone through the existing Repository clone endpoint (same
    validation, background clone, auto-activation); returns the repo id."""
    from app.api.repo import CloneRequest, clone_repo

    result = await clone_repo(
        CloneRequest(
            github_url=url,
            dest_path=dest,
            branch=branch,
            token=token,
            full_history=full_history,
        ),
        background_tasks,
        db,
        actor,
    )
    return int(result["id"])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def list_projects(
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    projects = list(
        (
            await db.execute(
                select(Project).order_by(
                    func.coalesce(Project.last_opened_at, Project.created_at).desc()
                )
            )
        ).scalars()
    )
    repo_ids = [p.repo_id for p in projects if p.repo_id]
    repos: dict[int, Repo] = {}
    if repo_ids:
        for r in (
            await db.execute(select(Repo).where(Repo.id.in_(repo_ids)))
        ).scalars():
            repos[r.id] = r
    counts: dict[int, dict[str, int]] = {}
    rows = await db.execute(
        select(DevTask.project_id, DevTask.status, func.count())
        .where(DevTask.project_id.is_not(None))
        .group_by(DevTask.project_id, DevTask.status)
    )
    for pid, status, n in rows:
        counts.setdefault(int(pid), {})[str(status)] = int(n)
    return {
        "projects": [
            _project_dict(p, repos.get(p.repo_id or -1), counts.get(p.id))
            for p in projects
        ]
    }


@router.post("", status_code=201)
async def create_project(
    body: CreateProjectRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    actor: str = Depends(require_approver),
) -> dict[str, Any]:
    settings = get_settings()
    project = Project(name=body.name, description=body.description, source=body.setup)
    project.created_by = actor
    repo: Repo | None = None

    if body.setup == "local_existing":
        folder = _check_in_workspace(body.path or "", "The project folder")
        if not os.path.isdir(folder):
            raise HTTPException(status_code=400, detail="That folder does not exist.")
        await _ensure_git_with_commit(folder, readme_title=None)
        repo = await _local_repo_row(db, folder)
        project.local_path = folder

    elif body.setup == "local_new":
        parent = _check_in_workspace(
            body.parent_path or settings.allowed_workspace_parent, "The location"
        )
        folder_name = (body.folder_name or slugify(body.name)).strip()
        if not _FOLDER_RE.match(folder_name):
            raise HTTPException(
                status_code=400,
                detail="Folder name may use letters, numbers, '.', '_' and '-' only.",
            )
        folder = os.path.join(parent, folder_name)
        if os.path.exists(folder) and any(Path(folder).iterdir()):
            raise HTTPException(
                status_code=400,
                detail=f"A folder named {folder_name!r} already exists there and is "
                "not empty. Choose another name, or use 'Existing project on this "
                "computer'.",
            )
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            raise HTTPException(
                status_code=400,
                detail="Could not create the folder there "
                f"({exc.strerror or exc}). Choose another location.",
            ) from None
        await _ensure_git_with_commit(folder, readme_title=body.name)
        repo = await _local_repo_row(db, folder)
        project.local_path = folder

    elif body.setup == "github_existing":
        url = (body.github_url or "").strip()
        if not url:
            raise HTTPException(
                status_code=400, detail="Enter the GitHub repository link."
            )
        dest = None
        if body.parent_path:
            # always a sub-folder named after the repository, never the
            # chosen folder itself
            from app.api.repo import _extract_name

            dest = os.path.join(
                _check_in_workspace(body.parent_path, "The location"),
                _extract_name(url),
            )
        token = (body.github_token or "").strip() or None
        repo_id = await _clone_for_project(
            db,
            background_tasks,
            actor,
            url=url,
            dest=dest,
            branch=(body.branch or "").strip() or None,
            token=token,
            full_history=body.full_history,
        )
        repo = await db.get(Repo, repo_id)
        project.github_url = url
        project.visibility = "private" if token else "public"
        if token and repo is not None:
            from app.db.repository import set_setting
            from app.security.credential_vault import scoped_credential_key

            await set_setting(db, scoped_credential_key("github_token", repo.id), token)

    else:  # github_new
        token = await _github_token(db, body.github_token)
        if not token:
            raise HTTPException(
                status_code=400,
                detail="Creating a GitHub repository needs a GitHub token. Add it in "
                "Settings, or enter it here.",
            )
        repo_name = (body.repo_name or slugify(body.name)).strip()
        if not _REPO_NAME_RE.match(repo_name):
            raise HTTPException(
                status_code=400,
                detail="Repository name may use letters, numbers, '.', '_' and '-' only.",
            )
        url = await _create_github_repo(token, repo_name, body.visibility == "private")
        dest = None
        if body.parent_path:
            dest = os.path.join(
                _check_in_workspace(body.parent_path, "The location"), repo_name
            )
        repo_id = await _clone_for_project(
            db,
            background_tasks,
            actor,
            url=url,
            dest=dest,
            branch=None,
            token=token if body.visibility == "private" else None,
            full_history=False,
        )
        repo = await db.get(Repo, repo_id)
        project.github_url = url
        project.visibility = body.visibility

    if repo is not None:
        project.repo_id = repo.id
        project.local_path = project.local_path or repo.local_path
    project.last_opened_at = datetime.now(timezone.utc)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return _project_dict(project, repo)


@router.get("/{project_id}")
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    p = await db.get(Project, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Project not found")
    repo = await db.get(Repo, p.repo_id) if p.repo_id else None
    goals = list(
        (
            await db.execute(
                select(Goal)
                .where(Goal.project_id == p.id)
                .order_by(Goal.created_at.desc())
            )
        ).scalars()
    )
    epics = list(
        (
            await db.execute(
                select(Epic)
                .where(Epic.project_id == p.id)
                .order_by(Epic.created_at.desc())
            )
        ).scalars()
    )
    tasks = list(
        (
            await db.execute(
                select(DevTask)
                .where(DevTask.project_id == p.id)
                .order_by(DevTask.id.desc())
                .limit(100)
            )
        ).scalars()
    )
    counts: dict[str, int] = {}
    for t in tasks:
        counts[t.status] = counts.get(t.status, 0) + 1
    return {
        **_project_dict(p, repo, counts),
        "goals": [
            {"id": g.goal_id, "title": g.text, "status": g.status} for g in goals
        ],
        "epics": [
            {"id": e.epic_id, "title": e.title, "status": e.status} for e in epics
        ],
        # History: the work done in this project, newest first.
        "history": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "executionMode": t.execution_mode,
                "summary": t.final_summary,
                "createdAt": t.created_at.isoformat() if t.created_at else None,
                "updatedAt": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in tasks
        ],
    }


@router.patch("/{project_id}")
async def update_project(
    project_id: int,
    body: UpdateProjectRequest,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_approver),
) -> dict[str, Any]:
    p = await db.get(Project, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if body.name is not None and body.name.strip():
        p.name = body.name.strip()
    if body.description is not None:
        p.description = body.description
    if "target_branch" in body.model_fields_set:
        from app.tools.git_push_tool import valid_branch_name

        target = (body.target_branch or "").strip()
        if target and not valid_branch_name(target):
            raise HTTPException(
                status_code=400,
                detail="That is not a valid branch name (letters, numbers, "
                "'.', '_', '-' and '/').",
            )
        p.target_branch = target or None
    await db.commit()
    await db.refresh(p)
    repo = await db.get(Repo, p.repo_id) if p.repo_id else None
    return _project_dict(p, repo)


# ---------------------------------------------------------------------------
# W1 (2026-10-09): understand a project. The free scan (no AI, only reads
# files) is always available; the AI summary only when the user asks.
# ---------------------------------------------------------------------------


def _ai_overview_key(project_id: int) -> str:
    return f"project-ai-overview:{project_id}"


async def _project_folder(db: AsyncSession, p: Project) -> str | None:
    repo = await db.get(Repo, p.repo_id) if p.repo_id else None
    if repo is not None:
        return repo.local_path if repo.status == "ready" else None
    return p.local_path


@router.get("/{project_id}/overview")
async def project_overview(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    import asyncio
    import json

    from app.db.repository import get_setting
    from app.repo_tools.project_scan import scan_project

    p = await db.get(Project, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Project not found")
    folder = await _project_folder(db, p)
    scan = (
        await asyncio.to_thread(scan_project, folder)
        if folder
        else {"ok": False, "error": "The project's files are not ready yet."}
    )
    stored = await get_setting(db, _ai_overview_key(project_id))
    ai = json.loads(stored) if stored else None
    return {"scan": scan, "ai": ai}


@router.post("/{project_id}/overview/ai", dependencies=[Depends(require_daily_budget)])
async def project_overview_ai(
    project_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_approver),
) -> dict[str, Any]:
    """Only on the user's click: a read-only agent reads the project and
    writes a plain summary (purpose, structure, how to run/test, risks)."""
    import json

    from app.db.repository import get_setting, set_setting

    p = await db.get(Project, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Project not found")
    folder = await _project_folder(db, p)
    if not folder:
        raise HTTPException(
            status_code=400, detail="This project's files are not ready yet."
        )
    stored = await get_setting(db, _ai_overview_key(project_id))
    if stored and json.loads(stored).get("status") == "running":
        return dict(json.loads(stored))
    state = {
        "status": "running",
        "summary": None,
        "startedAt": datetime.now(timezone.utc).isoformat(),
    }
    await set_setting(db, _ai_overview_key(project_id), json.dumps(state))
    await db.commit()
    background_tasks.add_task(_run_ai_overview, project_id, folder)
    return state


_AI_OVERVIEW_TOOLS = [
    "get_file_tree",
    "list_files",
    "read_file",
    "read_files",
    "search_code",
    "find_todos",
    "git_log",
]
_AI_OVERVIEW_REQUEST = (
    "Understand this project for the team that will work on it. In plain "
    "words: what it does; how it is organised (main folders and files); how "
    "to run it and how to run its tests (only commands you found in its "
    "files); and problems or risks you noticed (missing tests, TODOs, "
    "outdated or unclear parts). Keep it short and concrete."
)


async def _run_ai_overview(project_id: int, folder: str) -> None:
    import asyncio
    import json

    from app.api.team import _run_agent
    from app.db.repository import set_setting
    from app.db.session import get_async_session

    result = {"status": "failed", "summary": None}
    try:
        state = await asyncio.to_thread(
            _run_agent,
            project_id,
            "project overview",
            "Read-only project analyst.",
            _AI_OVERVIEW_TOOLS,
            folder,
            _AI_OVERVIEW_REQUEST,
        )
        raw = state.get("result") or {}
        if state.get("submitted") and raw.get("summary"):
            result = {"status": "completed", "summary": str(raw["summary"])[:8000]}
        else:
            result = {
                "status": "failed",
                "summary": "The AI stopped before finishing. Try again.",
            }
    except Exception as exc:
        logger.exception("AI overview for project %s failed", project_id)
        result = {"status": "failed", "summary": f"Failed: {type(exc).__name__}"}
    result["finishedAt"] = datetime.now(timezone.utc).isoformat()
    async with get_async_session() as db:
        await set_setting(db, _ai_overview_key(project_id), json.dumps(result))
        await db.commit()


@router.post("/{project_id}/open")
async def open_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    actor: str = Depends(require_approver),
) -> dict[str, Any]:
    """Continue working on a project: remember it as last opened and make its
    folder the active repository (the existing activation path), when ready."""
    p = await db.get(Project, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Project not found")
    p.last_opened_at = datetime.now(timezone.utc)
    await db.commit()
    repo = await db.get(Repo, p.repo_id) if p.repo_id else None
    if repo is not None and repo.status == "ready":
        from app.api.repo import activate_repo

        await activate_repo(repo.id, db, actor)
    await db.refresh(p)
    return _project_dict(p, repo)


@router.post("/{project_id}/goals", status_code=201)
async def add_goal(
    project_id: int,
    body: LabelRequest,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_approver),
) -> dict[str, Any]:
    """A goal label for this project. Unlike POST /api/goals this runs no AI
    agent and creates no epics; tasks can simply be tagged with it."""
    if await db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    goal = Goal(
        goal_id=str(uuid.uuid4()),
        text=body.title.strip(),
        status="open",
        epic_ids=[],
        summary=body.description,
        project_id=project_id,
    )
    db.add(goal)
    await db.commit()
    return {"id": goal.goal_id, "title": goal.text, "status": goal.status}


@router.post("/{project_id}/epics", status_code=201)
async def add_epic(
    project_id: int,
    body: LabelRequest,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_approver),
) -> dict[str, Any]:
    """An epic label for this project. Unlike POST /api/epics this starts no
    epic manager; status "open" is never picked up by any pipeline."""
    p = await db.get(Project, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Project not found")
    epic = Epic(
        epic_id=str(uuid.uuid4()),
        title=body.title.strip(),
        description=(body.description or "").strip(),
        status="open",
        repo_id=p.repo_id,
        project_id=project_id,
    )
    db.add(epic)
    await db.commit()
    return {"id": epic.epic_id, "title": epic.title, "status": epic.status}


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_approver),
) -> dict[str, Any]:
    """Remove a project from the app.

    Never touches files: the folder on this computer and the GitHub
    repository stay exactly as they are. Its tasks, goals and epics are kept
    (their project link is cleared by the foreign key's ON DELETE SET NULL),
    so past work stays visible and nothing in the task history is lost. The
    repository record is kept too, since those tasks still point at it."""
    p = await db.get(Project, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.delete(p)
    # W1: its stored AI overview goes with it
    from sqlalchemy import delete as sql_delete

    from app.db.models import SystemSetting

    await db.execute(
        sql_delete(SystemSetting).where(
            SystemSetting.key == _ai_overview_key(project_id)
        )
    )
    await db.commit()
    return {"deleted": True, "id": project_id}

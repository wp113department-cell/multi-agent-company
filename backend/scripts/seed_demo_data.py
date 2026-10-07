"""Load realistic demo data for client demos.

    python -m scripts.seed_demo_data                # (re)create the demo data
    python -m scripts.seed_demo_data --remove       # remove it again
    python -m scripts.seed_demo_data --workspace /path/to/folder

Creates 3 projects (each with a small real code folder tracked by git), their
goals and epics, tasks in every stage of the lifecycle with timelines, plans,
results and AI cost history, decisions waiting for the user (plan, question,
risky action, send to GitHub), team-improvement suggestions and a roadmap.

Projects and tasks are marked ``created_by = "demo-seed"`` (approvals and
suggestions through their task or ``trace_id``). The IDs of repos and roadmaps
created here are recorded separately because those models have no creator
field. Removal preserves shared rows, and acting on demo items in the UI never
starts real AI work (see app/services/demo.py). Running it again replaces the
previous demo data, keeping its folders and avoiding existing real folders.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from app.config import get_settings
from app.db.models import (
    AgentRun,
    DevTask,
    EnhancementRequest,
    Epic,
    Goal,
    PendingApproval,
    Project,
    Repo,
    Roadmap,
    RoadmapItem,
    SystemSetting,
    TaskLog,
)
from app.db.session import get_session_factory
from app.services.demo import DEMO_CREATOR

NOW = datetime.now(timezone.utc)
DEMO_FOLDER_MARKER = ".gridiron-demo"
DEMO_OWNERSHIP_KEY = "demo-seed-owned-data"


def ago(**kw: float) -> datetime:
    return NOW - timedelta(**kw)


# ---------------------------------------------------------------- content

PROJECTS: list[dict[str, Any]] = [
    {
        "name": "Customer Support Assistant",
        "folder": "customer-support-assistant",
        "description": "AI assistant that answers customer questions and routes tickets.",
        "files": {
            "README.md": "# Customer Support Assistant\n\nAnswers customer questions and routes support tickets.\n",
            "app/main.py": "from fastapi import FastAPI\n\napp = FastAPI(title='Support Assistant')\n\n\n@app.get('/health')\ndef health() -> dict[str, str]:\n    return {'status': 'ok'}\n",
            "app/routing.py": "def route_ticket(subject: str) -> str:\n    if 'refund' in subject.lower():\n        return 'billing'\n    return 'general'\n",
            "tests/test_routing.py": "from app.routing import route_ticket\n\n\ndef test_refund_goes_to_billing() -> None:\n    assert route_ticket('Refund please') == 'billing'\n",
        },
        "goals": ["Answer customers faster", "Reduce support tickets by 30%"],
        "epics": ["Smart ticket routing", "Live chat widget"],
    },
    {
        "name": "ShopNow Storefront",
        "folder": "shopnow-storefront",
        "description": "Online store: product catalogue, cart and checkout.",
        "files": {
            "README.md": "# ShopNow Storefront\n\nProduct catalogue, cart and checkout.\n",
            "package.json": '{\n  "name": "shopnow-storefront",\n  "private": true,\n  "scripts": { "dev": "next dev" }\n}\n',
            "src/cart.ts": "export function cartTotal(items: { price: number; qty: number }[]): number {\n  return items.reduce((s, i) => s + i.price * i.qty, 0);\n}\n",
        },
        "goals": ["Increase checkout conversion"],
        "epics": ["Checkout redesign", "Product search"],
    },
    {
        "name": "HR Onboarding Portal",
        "folder": "hr-onboarding-portal",
        "description": "Portal that gets new employees ready on day one.",
        "files": {
            "README.md": "# HR Onboarding Portal\n\nEverything a new employee needs on day one.\n",
            "portal/models.py": "from dataclasses import dataclass\n\n\n@dataclass\nclass Employee:\n    name: str\n    start_date: str\n",
        },
        "goals": ["Onboard new hires in one day"],
        "epics": ["Document e-signing"],
    },
]

# (project index, title, description, status, priority, mode, goal idx, epic idx, age hours)
TASKS: list[dict[str, Any]] = [
    {
        "p": 0,
        "title": "Route refund emails straight to the billing team",
        "desc": "When a customer email mentions a refund, send the ticket to the billing queue instead of the general queue, and add a test for it.",
        "status": "completed",
        "priority": "high",
        "mode": "economy",
        "goal": 1,
        "epic": 0,
        "age": 70,
        "summary": "Refund emails now go to the billing queue. Added keyword matching for 'refund', 'chargeback' and 'money back', plus 4 tests. All 12 tests pass.",
        "files": ["app/routing.py", "tests/test_routing.py"],
    },
    {
        "p": 0,
        "title": "Add an FAQ answer for 'Where is my order?'",
        "desc": "Customers ask about order status all the time. Answer it automatically using the order-tracking API.",
        "status": "completed",
        "priority": "medium",
        "mode": "economy",
        "goal": 0,
        "epic": None,
        "age": 50,
        "summary": "The assistant now answers order-status questions from the tracking API and hands over to a human when the order is not found. 7 new tests pass.",
        "files": ["app/faq.py", "app/tracking.py", "tests/test_faq.py"],
    },
    {
        "p": 0,
        "title": "Live chat widget for the help centre",
        "desc": "Add a small chat widget to the help-centre pages that connects customers to the assistant.",
        "status": "ready_for_review",
        "priority": "high",
        "mode": "max",
        "goal": 0,
        "epic": 1,
        "age": 3,
        "plan": "1. Create a ChatWidget component (bubble + panel) for the help-centre layout\n2. Add a /chat/messages API endpoint that streams the assistant's answer\n3. Store the conversation per visitor for 24 hours\n4. Hand over to a human agent when the customer asks for one\n5. Tests for the endpoint and the hand-over rule",
    },
    {
        "p": 0,
        "title": "Detect angry customers and escalate",
        "desc": "If a message sounds angry or mentions cancelling, flag the ticket as urgent and notify a team lead.",
        "status": "coding",
        "priority": "high",
        "mode": "max",
        "goal": 1,
        "epic": 0,
        "age": 1,
    },
    {
        "p": 0,
        "title": "Weekly report of the top 10 customer questions",
        "desc": "Every Monday, email the support lead the ten most common questions of last week.",
        "status": "pending",
        "priority": "medium",
        "mode": "economy",
        "goal": 1,
        "epic": None,
        "age": 0.5,
    },
    {
        "p": 1,
        "title": "One-page checkout",
        "desc": "Combine shipping, payment and review into a single checkout page to reduce drop-off.",
        "status": "testing",
        "priority": "high",
        "mode": "max",
        "goal": 0,
        "epic": 0,
        "age": 2,
    },
    {
        "p": 1,
        "title": "Show delivery date on the product page",
        "desc": "Show 'Arrives by <date>' under the price, based on the customer's postcode.",
        "status": "ready_for_review",
        "priority": "medium",
        "mode": "economy",
        "goal": 0,
        "epic": None,
        "age": 5,
        "plan": "1. Add a delivery-estimate helper using the carrier's lead times\n2. Read the postcode from the saved address (or ask for it)\n3. Show the date under the price on the product page\n4. Unit tests for weekends and public holidays",
        "diff": '--- a/src/product/DeliveryDate.tsx\n+++ b/src/product/DeliveryDate.tsx\n@@\n+export function DeliveryDate({ date }: { date: string }) {\n+  return <p className="delivery">Arrives by {date}</p>;\n+}\n',
    },
    {
        "p": 1,
        "title": "Search products by colour and size",
        "desc": "Add colour and size filters to product search.",
        "status": "blocked",
        "priority": "medium",
        "mode": "economy",
        "goal": None,
        "epic": 1,
        "age": 8,
        "blocked": "clarification",
    },
    {
        "p": 1,
        "title": "Apply discount codes at checkout",
        "desc": "Let customers enter a discount code and show the reduced total.",
        "status": "completed",
        "priority": "medium",
        "mode": "economy",
        "goal": 0,
        "epic": 0,
        "age": 96,
        "summary": "Discount codes work at checkout with percentage and fixed-amount codes, expiry dates and one-use-per-customer. 9 tests pass.",
        "files": [
            "src/checkout/discount.ts",
            "src/checkout/Discount.tsx",
            "tests/discount.test.ts",
        ],
    },
    {
        "p": 1,
        "title": "Migrate product images to the new CDN",
        "desc": "Move all product images to the new CDN and update the image URLs.",
        "status": "failed",
        "priority": "medium",
        "mode": "economy",
        "goal": None,
        "epic": None,
        "age": 20,
        "error": "The CDN rejected the upload: the access key in the environment has expired. Add a new key and try again.",
    },
    {
        "p": 2,
        "title": "Welcome email on the first day",
        "desc": "Send new hires a welcome email at 8am on their start date with their first-day schedule.",
        "status": "completed",
        "priority": "medium",
        "mode": "economy",
        "goal": 0,
        "epic": None,
        "age": 120,
        "summary": "Welcome emails are scheduled for 8am local time on the start date, with the first-day agenda. 5 tests pass.",
        "files": ["portal/emails.py", "tests/test_emails.py"],
    },
    {
        "p": 2,
        "title": "E-signing for the employment contract",
        "desc": "Let new hires sign their contract online before day one.",
        "status": "planning",
        "priority": "high",
        "mode": "max",
        "goal": 0,
        "epic": 0,
        "age": 0.3,
    },
    {
        "p": 2,
        "title": "Remove the old paper-form upload page",
        "desc": "Delete the legacy upload page now that forms are online.",
        "status": "ready_for_review",
        "priority": "medium",
        "mode": "economy",
        "goal": None,
        "epic": None,
        "age": 6,
        "plan": "1. Delete the legacy upload page and its route\n2. Redirect old links to the new forms page\n3. Remove the unused storage bucket settings",
        "risky": True,
    },
]

AGENT_FLOW = {
    "economy": ["planner", "backend_dev", "qa"],
    "max": [
        "pm",
        "architect",
        "decomposer",
        "backend_dev",
        "frontend_dev",
        "qa",
        "reviewer",
        "security_reviewer",
    ],
}
COST = {
    "pm": 0.012,
    "architect": 0.041,
    "decomposer": 0.018,
    "planner": 0.004,
    "backend_dev": 0.031,
    "frontend_dev": 0.027,
    "qa": 0.009,
    "reviewer": 0.016,
    "security_reviewer": 0.011,
}

SUGGESTIONS = [
    (
        "agent_performance_reviewer",
        "Use the smaller model for routine QA runs",
        "QA runs on simple tasks used the large model 40% of the time. Routing them to the smaller model saves about 30% of QA cost with the same pass rate.",
        "performance",
        "medium",
        "pending",
    ),
    (
        "quality_auditor",
        "Add tests for the discount-code expiry rules",
        "Two branches of the discount expiry logic in ShopNow have no test. A regression there would let expired codes through.",
        "quality",
        "medium",
        "pending",
    ),
    (
        "agent_debugger",
        "Retry CDN uploads when the access key is refreshed",
        "The image-migration task failed on an expired key. The upload tool should report the key problem clearly instead of a generic error.",
        "bug",
        "emergency",
        "pending",
    ),
    (
        "knowledge_curator",
        "Merge 3 duplicate lessons about ticket routing",
        "Three saved lessons say the same thing about routing keywords. Merging them keeps the team's memory short and clear.",
        "memory",
        "low",
        "pending",
    ),
    (
        "agent_advisor",
        "Send small UI-only tasks to the frontend developer only",
        "Five recent UI-only tasks also ran the backend developer, who made no changes. Skipping it would save time and cost.",
        "routing",
        "medium",
        "applied",
    ),
]

ROADMAP = [
    (
        "Now",
        "Smart ticket routing for billing and refunds",
        "high",
        "small",
        "completed",
    ),
    ("Now", "Live chat widget in the help centre", "high", "medium", "in_progress"),
    ("Next", "Detect angry customers and escalate", "high", "medium", "in_progress"),
    ("Next", "Weekly top-questions report", "medium", "small", "planned"),
    ("Later", "Answer in the customer's language", "high", "large", "planned"),
    ("Later", "Voice support line", "medium", "large", "planned"),
]


# ---------------------------------------------------------------- helpers


def _git(folder: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Multi Agentic Company",
            "-c",
            "user.email=bot@multi-agentic.local",
            *args,
        ],
        cwd=folder,
        check=True,
        capture_output=True,
    )


def _make_folder(base: Path, spec: dict[str, Any], registered_paths: set[Path]) -> Path:
    """Only create files in a fresh folder or reuse an untouched owned folder."""
    suffix = 0
    while True:
        name = spec["folder"] + (f"-demo-{suffix}" if suffix else "")
        folder = base / name
        marker = folder / DEMO_FOLDER_MARKER
        if folder.resolve() not in registered_paths and not folder.is_symlink():
            if not folder.exists():
                folder.mkdir(parents=True, exist_ok=False)
                break
            if marker.is_file() and marker.read_text() == DEMO_CREATOR:
                # Keep any edits the user made, including git history. Never
                # add files through symlinks inside a previously used folder.
                return folder
        suffix += 1
    for rel, content in spec["files"].items():
        f = folder / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    marker.write_text(DEMO_CREATOR)
    _git(folder, "init", "-q")
    _git(folder, "add", "-A")
    _git(folder, "commit", "-qm", "Initial project")
    return folder


async def _owned_data(db: Any) -> dict[str, list[int]]:
    setting = await db.get(SystemSetting, DEMO_OWNERSHIP_KEY)
    if setting is None:
        return {"repo_ids": [], "roadmap_ids": []}
    try:
        data = json.loads(setting.value)
    except (ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    owned = {}
    for key in ("repo_ids", "roadmap_ids"):
        values = data.get(key, [])
        owned[key] = (
            [value for value in values if type(value) is int]
            if isinstance(values, list)
            else []
        )
    return owned


async def _save_owned_data(db: Any, owned: dict[str, list[int]]) -> None:
    setting = await db.get(SystemSetting, DEMO_OWNERSHIP_KEY)
    if not any(owned.values()):
        if setting is not None:
            await db.delete(setting)
    elif setting is None:
        db.add(SystemSetting(key=DEMO_OWNERSHIP_KEY, value=json.dumps(owned)))
    else:
        setting.value = json.dumps(owned)


async def _delete_unreferenced(
    db: Any, model: Any, primary_key: Any, ids: list[Any]
) -> list[Any]:
    """Do not remove an owned row while any surviving row still needs it."""
    if not ids:
        return []
    stmt = delete(model).where(primary_key.in_(ids))
    target = f"{model.__tablename__}.{primary_key.key}"
    for table in Repo.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            if foreign_key.target_fullname == target:
                reference = (
                    select(1)
                    .select_from(table)
                    .where(foreign_key.parent == primary_key)
                    .correlate(model.__table__)
                    .exists()
                )
                stmt = stmt.where(~reference)
    return list((await db.execute(stmt.returning(primary_key))).scalars())


async def remove_demo(db: Any) -> int:
    owned = await _owned_data(db)
    projects = list(
        (
            await db.execute(select(Project).where(Project.created_by == DEMO_CREATOR))
        ).scalars()
    )
    task_ids = [
        t
        for (t,) in await db.execute(
            select(DevTask.id).where(DevTask.created_by == DEMO_CREATOR)
        )
    ]
    project_ids = [p.id for p in projects]
    if task_ids:
        await db.execute(
            delete(PendingApproval).where(PendingApproval.task_id.in_(task_ids))
        )
        await db.execute(delete(AgentRun).where(AgentRun.task_id.in_(task_ids)))
        await db.execute(delete(TaskLog).where(TaskLog.task_id.in_(task_ids)))
        await db.execute(delete(DevTask).where(DevTask.id.in_(task_ids)))
    await db.execute(
        delete(EnhancementRequest).where(EnhancementRequest.trace_id == DEMO_CREATOR)
    )
    # Sharing a repo with a demo project does not make a roadmap demo data.
    # Older unmarked repos/roadmaps are deliberately retained: their ownership
    # cannot be established safely from the project's repo_id alone.
    if owned["roadmap_ids"]:
        await db.execute(
            delete(RoadmapItem).where(RoadmapItem.roadmap_id.in_(owned["roadmap_ids"]))
        )
        await db.execute(delete(Roadmap).where(Roadmap.id.in_(owned["roadmap_ids"])))
        owned["roadmap_ids"] = []
    for model, primary_key in ((Goal, Goal.goal_id), (Epic, Epic.epic_id)):
        ids = list(
            (
                await db.execute(
                    select(primary_key).where(model.project_id.in_(project_ids))
                )
            ).scalars()
        )
        await _delete_unreferenced(db, model, primary_key, ids)
    removed_projects = await _delete_unreferenced(db, Project, Project.id, project_ids)
    await db.flush()
    removed_repos = await _delete_unreferenced(db, Repo, Repo.id, owned["repo_ids"])
    owned["repo_ids"] = [
        repo_id for repo_id in owned["repo_ids"] if repo_id not in removed_repos
    ]
    await _save_owned_data(db, owned)
    await db.commit()
    return len(removed_projects)


async def seed(workspace: Path) -> None:
    factory = get_session_factory()
    async with factory() as db:
        await remove_demo(db)
        owned = await _owned_data(db)
        registered_paths = {
            Path(path).resolve()
            for model in (Repo, Project)
            for path in (
                await db.execute(
                    select(model.local_path).where(model.local_path.is_not(None))
                )
            ).scalars()
        }

        made: list[tuple[Project, list[Goal], list[Epic]]] = []
        for i, spec in enumerate(PROJECTS):
            folder = _make_folder(workspace, spec, registered_paths)
            repo = Repo(
                github_url=None,
                name=spec["folder"],
                local_path=str(folder),
                status="ready",
                cloned_at=ago(days=14 - i),
            )
            db.add(repo)
            await db.flush()
            owned["repo_ids"].append(repo.id)
            registered_paths.add(folder.resolve())
            project = Project(
                name=spec["name"],
                description=spec["description"],
                local_path=str(folder),
                repo_id=repo.id,
                source="local_new",
                created_by=DEMO_CREATOR,
                created_at=ago(days=14 - i),
                last_opened_at=ago(hours=i * 5),
            )
            db.add(project)
            await db.flush()
            goals = [
                Goal(
                    goal_id=str(uuid.uuid4()),
                    text=g,
                    status="open",
                    epic_ids=[],
                    project_id=project.id,
                )
                for g in spec["goals"]
            ]
            epics = [
                Epic(
                    epic_id=str(uuid.uuid4()),
                    title=e,
                    description="",
                    status="open",
                    repo_id=repo.id,
                    project_id=project.id,
                    created_by=DEMO_CREATOR,
                )
                for e in spec["epics"]
            ]
            db.add_all(goals + epics)
            made.append((project, goals, epics))
        await db.flush()

        by_title: dict[str, DevTask] = {}
        for t in TASKS:
            project, goals, epics = made[t["p"]]
            created = ago(hours=t["age"])
            task = DevTask(
                title=t["title"],
                description=t["desc"],
                status=t["status"],
                priority=t["priority"],
                execution_mode=t["mode"],
                project=project.name,
                project_id=project.id,
                repo_id=project.repo_id,
                goal_id=goals[t["goal"]].goal_id if t.get("goal") is not None else None,
                epic_id=epics[t["epic"]].epic_id if t.get("epic") is not None else None,
                plan=t.get("plan"),
                diff=t.get("diff"),
                files_touched=t.get("files"),
                final_summary=t.get("summary"),
                blocked_reason=t.get("blocked"),
                pr_status="pushed" if t["status"] == "completed" else "none",
                branch_name=f"agent/task-demo-{len(by_title) + 1}",
                created_by=DEMO_CREATOR,
                created_at=created,
                updated_at=min(
                    NOW,
                    created
                    + timedelta(
                        minutes=12 if t["status"] in ("completed", "failed") else 3
                    ),
                ),
            )
            db.add(task)
            await db.flush()
            by_title[t["title"]] = task

            # timeline + cost history
            flow = AGENT_FLOW[t["mode"]]
            steps = {
                "pending": 0,
                "planning": 1,
                "ready_for_review": 2,
                "coding": 3,
                "testing": len(flow) - 1,
                "blocked": 2,
                "failed": len(flow),
                "completed": len(flow),
            }[t["status"]]
            logs = [("pipeline", "Task created")]
            for k, agent in enumerate(flow[:steps]):
                start = created + timedelta(minutes=1 + k * 2)
                tin = 4000 + 1500 * k
                db.add(
                    AgentRun(
                        id=str(uuid.uuid4()),
                        task_id=task.id,
                        agent_type=agent,
                        status="completed",
                        model_id=(
                            "claude-haiku-4-5"
                            if t["mode"] == "economy"
                            else "claude-sonnet-5"
                        ),
                        tokens_in=tin,
                        tokens_out=tin // 4,
                        cache_read_tokens=tin // 2,
                        cache_creation_tokens=0,
                        cost_estimate=Decimal(
                            str(
                                COST.get(agent, 0.01)
                                * (0.6 if t["mode"] == "economy" else 1.0)
                            )
                        ),
                        retries=0,
                        verification_pct=1.0,
                        confidence=0.9,
                        tool_accuracy=0.95,
                        started_at=start,
                        finished_at=start + timedelta(minutes=1, seconds=40),
                    )
                )
                logs.append(
                    ("agent", f"{agent.replace('_', ' ').title()} finished its step")
                )
            if t["status"] == "ready_for_review":
                logs.append(("pipeline", "Plan ready: waiting for your approval"))
            if t["status"] == "blocked":
                logs.append(
                    (
                        "pipeline",
                        "The team has a question for you before it can continue",
                    )
                )
            if t["status"] == "failed":
                logs.append(("error", t["error"]))
            if t["status"] == "completed":
                logs.append(("pipeline", "All tests passed; changes sent to GitHub"))
            for k, (cat, msg) in enumerate(logs):
                db.add(
                    TaskLog(
                        task_id=task.id,
                        category=cat,
                        message=msg,
                        created_at=created + timedelta(minutes=k * 2),
                    )
                )

        # decisions waiting for the user
        def approval(
            task: DevTask,
            action: str,
            agent: str,
            details: dict[str, Any],
            age_min: float,
        ) -> None:
            db.add(
                PendingApproval(
                    thread_id=f"demo-{uuid.uuid4().hex[:12]}",
                    task_id=task.id,
                    agent_name=agent,
                    action=action,
                    details={**details, "demo": True},
                    status="pending",
                    repo_id=task.repo_id,
                    created_at=ago(minutes=age_min),
                )
            )

        chat = by_title["Live chat widget for the help centre"]
        approval(
            chat,
            "plan_review",
            "decomposer",
            {"description": "Plan for the live chat widget (5 steps)", "steps": 5},
            170,
        )
        delivery = by_title["Show delivery date on the product page"]
        approval(
            delivery,
            "git_push",
            "coder",
            {
                "branch": "agent/task-delivery-date",
                "files_changed": "src/product/DeliveryDate.tsx",
                "steps": 4,
            },
            290,
        )
        search = by_title["Search products by colour and size"]
        approval(
            search,
            "clarification",
            "planner",
            {
                "question": "Should the size filter use the shop's own sizes (S, M, L) or the supplier's sizes (EU 36-46)?",
                "context": "Products come from two suppliers that label sizes differently.",
                "options": [
                    {"label": "Shop sizes (S, M, L)"},
                    {"label": "Supplier sizes (EU 36-46)"},
                    {"label": "Show both"},
                ],
                "recommended_option": "Shop sizes (S, M, L)",
            },
            470,
        )
        legacy = by_title["Remove the old paper-form upload page"]
        approval(
            legacy,
            "chat_confirmation",
            "coder",
            {
                "description": "Delete the legacy upload page and its storage settings",
                "details": "portal/legacy_upload.py, portal/templates/upload.html",
            },
            350,
        )

        for k, (agent, title, desc, cat, prio, status) in enumerate(SUGGESTIONS):
            db.add(
                EnhancementRequest(
                    agent_name=agent,
                    title=title,
                    description=desc,
                    category=cat,
                    priority=prio,
                    evidence={"summary": desc},
                    status=status,
                    files_touched=[],
                    restart_required=False,
                    trace_id=DEMO_CREATOR,
                    created_at=ago(hours=6 + k * 9),
                    decided_at=ago(hours=2) if status == "applied" else None,
                    decided_by="admin" if status == "applied" else None,
                    completed_at=ago(hours=2) if status == "applied" else None,
                )
            )

        support = made[0][0]
        roadmap = Roadmap(
            repo_id=support.repo_id,
            summary="Customer Support Assistant: next quarter",
            created_at=ago(days=3),
        )
        db.add(roadmap)
        await db.flush()
        owned["roadmap_ids"].append(roadmap.id)
        for k, (phase, initiative, impact, effort, status) in enumerate(ROADMAP):
            db.add(
                RoadmapItem(
                    roadmap_id=roadmap.id,
                    phase=phase,
                    initiative=initiative,
                    impact=impact,
                    effort=effort,
                    confidence="high" if k < 3 else "medium",
                    dependencies=[],
                    sequence_order=k + 1,
                    status=status,
                )
            )
        await _save_owned_data(db, owned)
        await db.commit()
    print(
        f"Demo data loaded: {len(PROJECTS)} projects, {len(TASKS)} tasks, 4 decisions, "
        f"{len(SUGGESTIONS)} suggestions, 1 roadmap. Folders in {workspace}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--remove", action="store_true", help="remove the demo data")
    ap.add_argument(
        "--workspace",
        help="where the demo project folders are created "
        "(default: <ALLOWED_WORKSPACE_PARENT>/demo-projects)",
    )
    args = ap.parse_args()
    if args.remove:

        async def rm() -> None:
            async with get_session_factory()() as db:
                n = await remove_demo(db)
            print(
                f"Removed {n} demo projects and their demo data. "
                "Shared rows and folders on disk are kept."
            )

        asyncio.run(rm())
        return
    ws = Path(
        args.workspace
        or os.path.join(get_settings().allowed_workspace_parent, "demo-projects")
    )
    ws.mkdir(parents=True, exist_ok=True)
    asyncio.run(seed(ws.resolve()))


if __name__ == "__main__":
    main()

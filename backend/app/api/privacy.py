"""Privacy API — GDPR/CCPA data-export and deletion-on-request.

AUDIT_Q_BATCH11 §96 "Compliance readiness" — real data retention (archive,
not hard-delete) already exists elsewhere, and app/agents/compliance_agent.py
produces LLM-written `.md` audit documents, but neither is a code-level
data-subject-request mechanism: no endpoint let a user (or an admin acting
on their behalf) actually retrieve or erase the data this system holds
about a specific identity. This is that mechanism, built against the real
data model, not a placeholder:

  - Identity data: the `users` table (username, role, must_change_password —
    password hash intentionally excluded from exports; AUDIT_Q_BATCH14 §48
    gap-closure, migration 044 — see app/db/models.py's User model
    docstring) and the separate `user_roles` table.
  - Attributable activity: audit_log rows where this identity is either the
    acting agent_name or the human recorded as approved_by (AuditLog.
    by_actor_async, app/fleet/audit_log.py).
  - Sol A14 (2026-10-09) — the full inventory, exported with totals and
    paging (?offset=&limit=): the person's own chats with their messages
    (personal content: DELETED on erasure), and the shared team records that
    name them — tasks, epics (created/cost-approved), projects, custom
    agents and their runs, approval and improvement decisions, prompt
    approvals, project notes (team work: KEPT on erasure, with the name
    replaced by "erased-user"). Before this the export returned only the
    identity and audit rows while tasks/epics kept the name forever.

Erasure (DELETE /api/privacy/user/{username}) removes identity data (login
becomes impossible, role assignment removed) but deliberately does NOT
delete audit_log history for that identity — this is not an oversight:
migration 036 made audit_log genuinely append-only at the DB layer
(BEFORE UPDATE/DELETE triggers, no bypass reachable from any application
code path), and GDPR Article 17(3)(b) / CCPA's equivalent both recognize an
explicit legal-obligation exemption for records like an approval/audit
trail. The response says exactly what was removed and what was retained
(and why), rather than silently doing a partial deletion under a
"fully erased" claim that wouldn't be true.

All routes require an authenticated caller; cross-user export/erasure
requires the admin role (production audit 13: it used to accept any
approver, who could then erase every admin account), and the last admin
account can never be erased.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
from app.db import get_db
from app.db.models import User, UserRole
from app.db.repository import delete_user, get_user
from app.fleet.audit_log import AuditEntry, get_audit_log
from app.middleware.rbac import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/privacy", tags=["privacy"])


def _serialize_audit_entry(entry: AuditEntry) -> dict[str, Any]:
    return entry.to_dict()


# Sol A14 (2026-10-09): everything that records a person, and what erasure
# does with it. "personal" is the person's own content (deleted on
# erasure); "team" is shared team work that stays, with the name replaced.
ERASED = "erased-user"
_TEAM_ATTRIBUTION = [
    ("dev_tasks", "created_by", "tasks"),
    ("epics", "created_by", "epics"),
    ("epics", "cost_approved_by", "epicCostApprovals"),
    ("projects", "created_by", "projects"),
    ("custom_agents", "created_by", "customAgents"),
    ("custom_agent_runs", "created_by", "customAgentRuns"),
    ("pending_approvals", "decided_by", "approvalDecisions"),
    ("enhancement_requests", "decided_by", "improvementDecisions"),
    ("prompt_versions", "approved_by", "promptApprovals"),
]


def _plain(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    return value


async def _rows(
    db: AsyncSession, table: str, column: str, username: str, offset: int, limit: int
) -> dict[str, Any]:
    from sqlalchemy import text

    total = int(
        (
            await db.execute(
                text(f"SELECT count(*) FROM {table} WHERE {column} = :u"),  # noqa: S608
                {"u": username},
            )
        ).scalar_one()
    )
    result = await db.execute(
        text(
            f"SELECT * FROM {table} WHERE {column} = :u "  # noqa: S608
            "ORDER BY 1 OFFSET :o LIMIT :l"
        ),
        {"u": username, "o": offset, "l": limit},
    )
    items = [{k: _plain(v) for k, v in row._mapping.items()} for row in result]
    return {"total": total, "offset": offset, "items": items}


async def _project_notes_by(db: AsyncSession, username: str) -> list[dict[str, Any]]:
    import json

    from app.db.models import SystemSetting
    from app.db.repository import get_setting

    keys = (
        await db.execute(
            select(SystemSetting.key).where(SystemSetting.key.like("project-notes:%"))
        )
    ).scalars()
    out: list[dict[str, Any]] = []
    for key in list(keys):
        try:
            notes = json.loads(await get_setting(db, key) or "[]")
        except ValueError:
            continue
        for note in notes:
            if note.get("createdBy") == username:
                out.append({"project": key.split(":", 1)[1], **note})
    return out


async def _export_for_username(
    username: str, db: AsyncSession, offset: int = 0, limit: int = 500
) -> dict[str, Any]:
    user = await get_user(db, username)
    identity: dict[str, Any] | None = None
    if user is not None:
        identity = {
            "username": user.username,
            "role": user.role,
            "mustChangePassword": user.must_change_password,
        }

    role_row = (
        await db.execute(select(UserRole).where(UserRole.user_id == username))
    ).scalar_one_or_none()
    user_role = (
        {
            "userId": role_row.user_id,
            "role": role_row.role,
            "createdAt": (
                role_row.created_at.isoformat() if role_row.created_at else None
            ),
        }
        if role_row is not None
        else None
    )

    audit_entries = await get_audit_log().by_actor_async(username, limit=2000)

    chats = await _rows(db, "chat_sessions", "created_by", username, offset, limit)
    for chat in chats["items"]:
        from sqlalchemy import text

        msgs = await db.execute(
            text(
                "SELECT role, content, created_at FROM chat_messages "
                "WHERE session_id = :s ORDER BY created_at"
            ),
            {"s": chat["id"]},
        )
        chat["messages"] = [{k: _plain(v) for k, v in m._mapping.items()} for m in msgs]
    team_work = {
        label: await _rows(db, table, column, username, offset, limit)
        for table, column, label in _TEAM_ATTRIBUTION
    }

    return {
        "username": username,
        "identity": identity,
        "userRole": user_role,
        "chats": chats,
        "teamWork": team_work,
        "projectNotes": await _project_notes_by(db, username),
        "paging": {
            "offset": offset,
            "limit": limit,
            "howTo": "every list has a 'total'; ask again with ?offset= to page "
            "through lists longer than the limit",
        },
        "attributableAuditEntries": [_serialize_audit_entry(e) for e in audit_entries],
        "notes": (
            "identity/userRole are null if no matching record exists. "
            "attributableAuditEntries includes every audit_log row where "
            "this username is either the acting agent or the human who "
            "made an approval decision (capped at 2000, newest first); "
            "chats are this person's own conversations with their messages; "
            "teamWork lists shared team records that name this person; "
            "password hashes are never included in this export."
        ),
    }


@router.get("/export/me")
async def export_my_data(
    offset: int = 0,
    limit: int = 500,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Self-service GDPR/CCPA data-access request: export everything this
    system holds that's attributable to the caller's own identity."""
    if not current_user.is_authenticated:
        raise HTTPException(
            status_code=401,
            detail="A real, verified session is required to export your own data "
            "(the anonymous/legacy-header default does not count as a resolvable "
            "identity).",
        )
    return await _export_for_username(
        current_user.username, db, max(0, offset), max(1, min(limit, 5000))
    )


@router.get("/export/{username}")
async def export_user_data(
    username: str,
    offset: int = 0,
    limit: int = 500,
    _admin: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Admin-initiated GDPR/CCPA data-access request on behalf of another
    user (e.g. responding to a data subject access request submitted
    outside this system)."""
    return await _export_for_username(
        username, db, max(0, offset), max(1, min(limit, 5000))
    )


async def _pseudonymize_notes(db: AsyncSession, username: str) -> int:
    import json

    from app.db.models import SystemSetting
    from app.db.repository import get_setting, set_setting

    keys = list(
        (
            await db.execute(
                select(SystemSetting.key).where(
                    SystemSetting.key.like("project-notes:%")
                )
            )
        ).scalars()
    )
    changed = 0
    for key in keys:
        try:
            notes = json.loads(await get_setting(db, key) or "[]")
        except ValueError:
            continue
        hit = False
        for note in notes:
            if note.get("createdBy") == username:
                note["createdBy"] = ERASED
                changed += 1
                hit = True
        if hit:
            await set_setting(db, key, json.dumps(notes))
    return changed


@router.delete("/user/{username}")
async def delete_user_data(
    username: str,
    _admin: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GDPR/CCPA erasure request: removes login credentials and role
    assignment for `username`. Does NOT delete audit_log history
    attributable to them — see this module's docstring for why that's a
    deliberate, legally-grounded scope boundary, not a partial
    implementation."""
    # Never erase the last admin: nobody could manage users afterwards.
    target = await get_user(db, username)
    if target is not None and str(target.role) == "admin":
        remaining = await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.role == "admin", User.username != username)
        )
        if int(remaining.scalar_one()) == 0:
            raise HTTPException(
                status_code=409,
                detail="Refusing to erase the last admin account; create another admin first.",
            )

    identity_removed = await delete_user(db, username)
    from app.auth.revocation import invalidate

    invalidate(
        username
    )  # the erased account's token must stop working now, not after the TTL

    role_delete_result = await db.execute(
        delete(UserRole).where(UserRole.user_id == username)
    )
    role_removed = bool(getattr(role_delete_result, "rowcount", 0))

    # Sol A14: the person's own chats go; shared team work stays with the
    # name replaced (it is the team's record, not personal content)
    from sqlalchemy import text

    chat_ids = [
        str(r[0])
        for r in await db.execute(
            text("SELECT id FROM chat_sessions WHERE created_by = :u"), {"u": username}
        )
    ]
    for sid in chat_ids:
        await db.execute(
            text("DELETE FROM chat_messages WHERE session_id = :s"), {"s": sid}
        )
    await db.execute(
        text("DELETE FROM chat_sessions WHERE created_by = :u"), {"u": username}
    )
    pseudonymized: dict[str, int] = {}
    for table, column, label in _TEAM_ATTRIBUTION:
        result = await db.execute(
            text(f"UPDATE {table} SET {column} = :e WHERE {column} = :u"),  # noqa: S608
            {"e": ERASED, "u": username},
        )
        pseudonymized[label] = int(getattr(result, "rowcount", 0) or 0)
    pseudonymized["projectNotes"] = await _pseudonymize_notes(db, username)

    await db.commit()

    if not identity_removed and not role_removed:
        raise HTTPException(
            status_code=404,
            detail=f"No users entry or user_roles row found for {username!r}.",
        )

    audit_count = len(await get_audit_log().by_actor_async(username, limit=1))

    logger.info(
        "Privacy erasure request processed for %r (identity_removed=%s, "
        "role_removed=%s)",
        username,
        identity_removed,
        role_removed,
    )
    get_audit_log().append(
        action_type="privacy_erasure_request",
        agent_name="privacy_api",
        description=f"Erasure request processed for user {username!r}",
        outcome="success",
        details={
            "username": username,
            "identity_removed": identity_removed,
            "role_removed": role_removed,
        },
    )

    return {
        "username": username,
        "removed": {
            "authCredentials": identity_removed,
            "userRole": role_removed,
            "chats": len(chat_ids),
        },
        "pseudonymized": {
            "replacedWith": ERASED,
            "counts": pseudonymized,
            "reason": "shared team work stays for the team; the person's "
            "name on it is replaced",
        },
        "retained": {
            "auditLogEntries": audit_count > 0,
            "reason": (
                (
                    "audit_log is a legally-relevant approval/action trail, "
                    "retained under the same legal-obligation basis GDPR "
                    "Article 17(3)(b) recognizes for records like this — see "
                    "this module's docstring."
                )
                if audit_count > 0
                else None
            ),
        },
    }

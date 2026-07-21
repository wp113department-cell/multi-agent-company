"""Policy Engine v2 — DB-backed glob-pattern approval rules.

Adds approval rules on top of the v1 hard-coded denylist (v1 stays as floor).
Rules live in the `policies` table so adding a rule = DB insert, zero code change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Policy, PolicyApproval


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Compile a glob pattern to a regex that handles **, *, ? and path separators."""
    result = ""
    i = 0
    while i < len(pattern):
        if pattern[i : i + 3] == "**/":
            result += "(?:.*/)?"
            i += 3
        elif pattern[i : i + 2] == "**":
            result += ".*"
            i += 2
        elif pattern[i] == "*":
            result += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            result += "[^/]"
            i += 1
        else:
            result += re.escape(pattern[i])
            i += 1
    return re.compile("^" + result + "$")


@dataclass(frozen=True)
class PolicyMatch:
    policy_id: int
    policy_name: str
    trigger_pattern: str
    required_approval_role: str
    blocking: bool


async def load_active_policies(
    db: AsyncSession,
) -> list[tuple[Policy, re.Pattern[str]]]:
    """Load all active policies and pre-compile their glob patterns."""
    result = await db.execute(select(Policy).where(Policy.active.is_(True)))
    policies = list(result.scalars().all())
    return [(p, _glob_to_regex(p.trigger_pattern)) for p in policies]


async def check_file_against_policies(
    file_path: str,
    db: AsyncSession,
    task_id: str | None = None,
    epic_id: str | None = None,
) -> list[PolicyMatch]:
    """Return all active policies that match the given file path.

    Callers check `.blocking` to decide whether to halt or just flag.
    """
    compiled = await load_active_policies(db)
    matches: list[PolicyMatch] = []
    for policy, regex in compiled:
        if regex.match(file_path):
            matches.append(
                PolicyMatch(
                    policy_id=policy.id,
                    policy_name=policy.name,
                    trigger_pattern=policy.trigger_pattern,
                    required_approval_role=policy.required_approval_role,
                    blocking=policy.blocking,
                )
            )
    return matches


async def check_files_against_policies(
    file_paths: list[str],
    db: AsyncSession,
    task_id: str | None = None,
    epic_id: str | None = None,
) -> dict[str, list[PolicyMatch]]:
    """Check a list of file paths, returning only those with policy matches."""
    compiled = await load_active_policies(db)
    hits: dict[str, list[PolicyMatch]] = {}
    for file_path in file_paths:
        matches: list[PolicyMatch] = []
        for policy, regex in compiled:
            if regex.match(file_path):
                matches.append(
                    PolicyMatch(
                        policy_id=policy.id,
                        policy_name=policy.name,
                        trigger_pattern=policy.trigger_pattern,
                        required_approval_role=policy.required_approval_role,
                        blocking=policy.blocking,
                    )
                )
        if matches:
            hits[file_path] = matches
    return hits


async def has_approval(
    policy_id: int,
    db: AsyncSession,
    task_id: str | None = None,
    epic_id: str | None = None,
    file_path: str | None = None,
) -> bool:
    """Check whether an approved decision exists for this policy + context."""
    stmt = select(PolicyApproval).where(
        PolicyApproval.policy_id == policy_id,
        PolicyApproval.decision == "approved",
    )
    if task_id:
        stmt = stmt.where(PolicyApproval.task_id == task_id)
    if epic_id:
        stmt = stmt.where(PolicyApproval.epic_id == epic_id)
    if file_path:
        stmt = stmt.where(PolicyApproval.file_path == file_path)
    result = await db.execute(stmt)
    return result.first() is not None


async def record_approval(
    policy_id: int,
    approver_role: str,
    decision: str,
    db: AsyncSession,
    task_id: str | None = None,
    epic_id: str | None = None,
    file_path: str | None = None,
) -> PolicyApproval:
    """Persist an approval (or rejection) decision to the audit log."""
    row = PolicyApproval(
        policy_id=policy_id,
        task_id=task_id,
        epic_id=epic_id,
        file_path=file_path,
        approver_role=approver_role,
        decision=decision,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


def match_pattern_sync(file_path: str, glob_pattern: str) -> bool:
    """Sync helper for tests and non-async contexts."""
    return bool(_glob_to_regex(glob_pattern).match(file_path))

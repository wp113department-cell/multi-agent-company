"""Dynamic Subtask Creation — plan14 follow-on #2.

Real gap this closes (confirmed by direct investigation of app.agents.
manager before writing anything here): subtasks were created exactly once,
by decomposer_node, and app.agents.manager.run_manager() computed its
dispatch waves (_topological_subtask_waves/_topological_subtask_order) once,
up front, assuming a static, complete list. There was no mechanism for a
dev agent mid-run to say "this task also needs X" — the only way to add
work was to re-plan the whole epic from scratch.

This module is the validation/integration layer — the "propose -> validate
-> insert" pattern's middle and last steps (the first step, the
propose_subtask TOOL itself, lives in app.agents.tools, matching where
every other tool in this codebase lives). run_manager() calls
integrate_proposals() at each wave boundary (never mid-wave — see that
function's own docstring for why), never from inside a subtask's own
dispatch call.

Deliberately does NOT reuse app.agents.delegation.delegate()'s own
"resolve target agent -> invoke synchronously -> return a result to this
same tool call" shape — dynamic subtask creation is structurally the
opposite: it enqueues work for run_manager()'s own wave loop to dispatch
LATER, respecting locks/dependencies/concurrency slots, not a target this
proposing agent's own turn waits on. What DOES transfer from delegation:
the never-raise-past-the-boundary contract (every validation failure is a
(None, reason) return, never an exception escaping into run_manager()) and
the config-driven, default-deny allow-matrix.

Real design decisions worth knowing before touching this file:
- Dependencies: a dynamically-proposed subtask's depends_on is NOT
  LLM-specified. The proposing agent has no visibility into the live
  `subtasks` list/indices (decomposer.py's own depends_on convention — 0-
  based indices into that same list — is documented as "fundamentally
  incompatible with an open-ended, growing list" once subtasks stop being a
  closed set), so asking the LLM to fill in an index it cannot see would be
  unreliable. Instead every proposal implicitly depends on ONLY the subtask
  that proposed it (the parent must finish before its own proposed child
  starts) — trivially correct, and structurally makes a dependency cycle
  IMPOSSIBLE: a proposal can only ever reference an index that already
  exists (its own parent's), never a forward or self reference.
- File locks: app.pipeline.file_locks.reserve_epic_files() has a UNIQUE
  constraint on file_path ALONE (not (epic_id, file_path)) — re-passing a
  file this SAME epic already holds would self-conflict. reserve_files_
  for_proposal() below queries this epic's own already-held files first and
  only reserves the delta.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import EpicFileLock
from app.pipeline.file_locks import reserve_epic_files

logger = logging.getLogger(__name__)

ALLOWED_SUBTASK_TYPES = frozenset({"backend", "frontend", "test", "docs"})


def validate_and_build_subtask(
    proposal: dict[str, Any],
    *,
    subtasks: list[dict[str, Any]],
    spawn_depth: dict[int, int],
    dynamic_count_so_far: int,
    parent_idx: int,
    parent_agent_name: str,
) -> tuple[dict[str, Any] | None, str]:
    """Pure, synchronous shape + policy validation — no I/O, no DB, so this
    is cheap to call for every proposal and easy to unit-test in isolation.
    File-lock reservation (the one check that genuinely needs a DB session)
    is a separate async step below (reserve_files_for_proposal), called
    only after this one already passed.

    Returns (subtask_dict, "") on success, or (None, reason) on rejection.
    Never raises — a malformed or policy-violating proposal is data to
    reject, not an error condition that should propagate into
    run_manager()'s own wave loop.
    """
    settings = get_settings()

    subtask_type = str(proposal.get("type", "")).strip()
    title = str(proposal.get("title", "")).strip()
    description = str(proposal.get("description", "")).strip()
    files_to_edit = proposal.get("files_to_edit") or []

    if subtask_type not in ALLOWED_SUBTASK_TYPES:
        return None, f"invalid subtask type {subtask_type!r}"
    if not title:
        return None, "empty title"
    if not isinstance(files_to_edit, list) or not all(
        isinstance(f, str) for f in files_to_edit
    ):
        return None, "files_to_edit must be a list of strings"

    allowed_types = settings.dynamic_subtask_allowed_matrix.get(parent_agent_name, [])
    if subtask_type not in allowed_types:
        return None, (
            f"{parent_agent_name!r} is not allowed to propose "
            f"{subtask_type!r} subtasks (allowed: {allowed_types})"
        )

    if dynamic_count_so_far >= settings.dynamic_subtask_max_per_epic:
        return None, (
            f"epic has already reached dynamic_subtask_max_per_epic="
            f"{settings.dynamic_subtask_max_per_epic}"
        )

    new_depth = spawn_depth.get(parent_idx, 0) + 1
    if new_depth > settings.dynamic_subtask_max_depth:
        return None, (
            f"spawn depth {new_depth} exceeds dynamic_subtask_max_depth="
            f"{settings.dynamic_subtask_max_depth}"
        )

    files_set = set(files_to_edit)
    norm_title = title.lower()
    for existing in subtasks:
        existing_files = set(existing.get("files_to_edit") or [])
        if files_set and files_set == existing_files:
            return None, (
                f"duplicate of existing subtask {existing.get('title')!r} "
                "(identical files_to_edit)"
            )
        if norm_title == str(existing.get("title", "")).strip().lower():
            return None, (
                f"duplicate of existing subtask {existing.get('title')!r} "
                "(identical title)"
            )

    new_subtask: dict[str, Any] = {
        "type": subtask_type,
        "title": title,
        "description": description,
        "files_to_edit": [str(f) for f in files_to_edit],
        "depends_on": [parent_idx],
        "dynamically_created": True,
        "proposed_by": parent_agent_name,
    }
    return new_subtask, ""


async def reserve_files_for_proposal(
    files_to_edit: list[str], epic_id: str, db: AsyncSession
) -> str | None:
    """Returns None on success (or if there was nothing to reserve), or a
    conflict description on failure. Only reserves files not already held
    by THIS epic — reserve_epic_files()'s unique constraint is on
    file_path alone, so re-passing an already-held file would self-conflict
    against this same epic's own existing lock."""
    if not files_to_edit:
        return None
    result = await db.execute(
        select(EpicFileLock.file_path).where(EpicFileLock.epic_id == epic_id)
    )
    already_held = {row[0] for row in result.all()}
    new_files = [f for f in files_to_edit if f not in already_held]
    if not new_files:
        return None
    return await reserve_epic_files(new_files, epic_id, db)


async def integrate_proposals(
    proposals: list[dict[str, Any]],
    *,
    subtasks: list[dict[str, Any]],
    spawn_depth: dict[int, int],
    dynamic_count: int,
    epic_id: str | None,
    db: AsyncSession | None,
    parent_agent_names: dict[int, str],
    task_id: int | None = None,
    db_subtask_rows: list[Any] | None = None,
) -> tuple[list[int], int]:
    """Called once per wave boundary by run_manager() — never mid-wave —
    with every proposal collected from that wave's outcomes. Mutates
    `subtasks`/`spawn_depth` IN PLACE (appending only — existing entries
    and indices are never touched), the same "accumulate into the caller's
    own structure" convention run_manager() already uses for its own
    `results`/`epic_tokens_in`. Returns (new_indices, updated dynamic_count)
    so the caller knows what to recompute waves for and what count to pass
    into the next call.

    A proposal missing a usable epic_id/db is rejected only if it actually
    declares files_to_edit (nothing to lock -> nothing to reject over);
    every other rejection reason is logged at INFO (not a warning — a
    rejected proposal is an expected, working part of this feature, not an
    error) and simply dropped, never raised.

    task_id/db_subtask_rows (2026-09-25, real gap found by direct reading
    of app.agents.manager._dispatch_one_subtask): when both are given, a
    real Subtask DB row is created for every integrated proposal via
    app.db.repository.add_subtask(), and db_subtask_rows (the caller's own
    list, mutated in place — same convention as subtasks/spawn_depth
    above) is kept in sync at the SAME position as `subtasks`, so
    _dispatch_one_subtask's own status-persistence check
    (`subtask_idx < len(db_subtask_rows)`) reaches dynamically-created
    subtasks too instead of silently never persisting their status and
    leaving zero DB trace of them across a crash. Both optional (None
    keeps the pre-existing in-memory-only behavior) only so this stays
    callable from contexts genuinely without a task_id (there are none in
    this codebase today, but the DB-work-is-optional contract this
    function already has for epic_id/db is preserved rather than silently
    tightened).
    """
    new_indices: list[int] = []
    for proposal in proposals:
        parent_idx = int(proposal.get("_parent_subtask_idx", -1))
        if parent_idx < 0 or parent_idx >= len(subtasks):
            logger.info(
                "Dynamic subtask proposal rejected: invalid parent index %r",
                parent_idx,
            )
            continue
        parent_agent_name = parent_agent_names.get(parent_idx, "")

        built, reason = validate_and_build_subtask(
            proposal,
            subtasks=subtasks,
            spawn_depth=spawn_depth,
            dynamic_count_so_far=dynamic_count,
            parent_idx=parent_idx,
            parent_agent_name=parent_agent_name,
        )
        if built is None:
            logger.info("Dynamic subtask proposal rejected: %s", reason)
            continue

        files_to_edit = built["files_to_edit"]
        if files_to_edit:
            if epic_id is None or db is None:
                logger.info(
                    "Dynamic subtask proposal rejected: no epic_id/db "
                    "available to reserve files_to_edit=%s",
                    files_to_edit,
                )
                continue
            lock_conflict = await reserve_files_for_proposal(files_to_edit, epic_id, db)
            if lock_conflict is not None:
                logger.info("Dynamic subtask proposal rejected: %s", lock_conflict)
                continue

        # Real persistence for crash/recovery (2026-09-25, real gap found by
        # direct reading — see this function's own docstring), attempted
        # BEFORE subtasks.append(): db_subtask_rows must stay in exact
        # position-lockstep with `subtasks` (that's the only correlation
        # _dispatch_one_subtask's own status-persistence check has — see
        # its own comment on why: the decomposer's transient "id" field is
        # not the real DB primary key). If persistence fails, treating the
        # whole proposal as rejected (never appending to `subtasks` either)
        # is what keeps that lockstep intact — a partial "keep in memory,
        # degrade DB tracking" would silently desync every index integrated
        # after this one instead.
        if task_id is not None and db_subtask_rows is not None and db is not None:
            try:
                from app.db.repository import add_subtask

                db_row = await add_subtask(db, task_id, built)
            except Exception:
                logger.warning(
                    "Dynamic subtask proposal rejected: could not persist "
                    "Subtask row for %r",
                    built["title"],
                    exc_info=True,
                )
                continue
            db_subtask_rows.append(db_row)

        new_idx = len(subtasks)
        built["id"] = new_idx + 1
        subtasks.append(built)
        spawn_depth[new_idx] = spawn_depth.get(parent_idx, 0) + 1
        dynamic_count += 1
        new_indices.append(new_idx)

        logger.info(
            "Dynamic subtask integrated: idx=%d title=%r proposed_by=%s parent_idx=%d",
            new_idx,
            built["title"],
            parent_agent_name,
            parent_idx,
        )

    return new_indices, dynamic_count

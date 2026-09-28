"""LangGraph StateGraph: PM → Architect → Decomposer → human_review (interrupt)."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command

from app.agents.pm import pm_node
from app.agents.architect import architect_node
from app.agents.decomposer import decomposer_node
from app.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

# Module-level checkpointer — replaced with AsyncPostgresSaver at startup via init_checkpointer().
# Falls back to MemorySaver if Postgres init fails (e.g. in tests).
_checkpointer: Any = MemorySaver()
_compiled_graph: Any = None
_pg_cm: Any = (
    None  # holds the AsyncPostgresSaver context manager open for the app lifetime
)


async def init_checkpointer(database_url: str) -> None:
    """
    Initialize the LangGraph PostgreSQL checkpointer so pipeline state
    survives server restarts. Called once from FastAPI lifespan startup.

    database_url: the asyncpg DSN from config (postgresql+asyncpg://...).
    Automatically converted to psycopg3 format (postgresql://...).
    """
    global _checkpointer, _compiled_graph, _pg_cm
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        # psycopg3 expects plain postgresql:// (no +asyncpg driver prefix)
        psycopg_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        # Enter the context manager and hold the connection open for the app lifetime
        cm = AsyncPostgresSaver.from_conn_string(psycopg_url)
        saver = await cm.__aenter__()
        await saver.setup()  # creates langgraph checkpoint tables if missing
        _pg_cm = cm
        _checkpointer = saver
        _compiled_graph = None  # force rebuild with new checkpointer
        logger.info(
            "LangGraph PostgreSQL checkpointer initialized — pipeline state is now persistent"
        )
    except Exception as exc:
        logger.warning(
            "PostgreSQL checkpointer init failed, falling back to MemorySaver: %s", exc
        )


async def close_checkpointer() -> None:
    """Close the PostgreSQL checkpointer connection. Called at FastAPI shutdown."""
    global _pg_cm
    if _pg_cm is not None:
        try:
            await _pg_cm.__aexit__(None, None, None)
        except Exception as exc:
            logger.warning("Error closing checkpointer: %s", exc)
        _pg_cm = None


def _route_after_pm(state: PipelineState) -> str:
    if state.get("stage") == "blocked":
        return END
    return "architect"


def _route_after_architect(state: PipelineState) -> str:
    if state.get("stage") == "blocked":
        return END
    return "decomposer"


def _route_after_decomposer(state: PipelineState) -> str:
    if state.get("stage") == "blocked":
        return END
    return "human_review"


class SubtaskEditError(ValueError):
    """Raised when a human-submitted subtask edit/reject is malformed or
    would corrupt the plan's dependency graph."""


def apply_subtask_edits(
    subtasks: list[dict[str, Any]], edits: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """#227 (2026-09-28, GRIDIRON_PARTIAL "Take over a task / edit plan /
    reject one step and resume exactly there") — the real, bounded slice of
    this item this session builds: individually addressable, editable/
    rejectable steps at the EXISTING human_review interrupt, not a full
    per-step-checkpoint graph redesign (the audit's own plan calls that "a
    graph-topology change ... its own project" — genuinely out of scope for
    one session's addition to an already-long list).

    Each edit is {"index": int, "action": "edit"|"reject", ...fields}.
    "edit" overlays the given fields (title/description/type/files_to_edit)
    onto subtasks[index] in place, by POSITION — the same position-lockstep
    convention #44's own dynamic-subtask-creation work already established
    for this exact list (a subtask has no independent stable id beyond its
    list position). "reject" removes that subtask entirely.

    Never silently produces a broken dependency graph: rejecting an index
    that another remaining subtask's own depends_on still references raises
    SubtaskEditError instead of guessing a renumbering — a fabricated fix
    here would be worse than refusing the edit and asking the human to
    reject the dependent step too (or edit its depends_on itself first).

    Pure and non-mutating — returns a new list, never touches the input.
    """
    if not edits:
        return subtasks

    result = [dict(s) for s in subtasks]
    rejected_indices: set[int] = set()

    for edit in edits:
        index = edit.get("index")
        action = edit.get("action", "edit")
        if not isinstance(index, int) or index < 0 or index >= len(subtasks):
            raise SubtaskEditError(f"subtask index {index!r} out of range")
        if action == "reject":
            rejected_indices.add(index)
        elif action == "edit":
            for field in ("type", "title", "description", "files_to_edit"):
                if field in edit:
                    result[index][field] = edit[field]
        else:
            raise SubtaskEditError(f"unknown subtask edit action {action!r}")

    if rejected_indices:
        for i, sub in enumerate(result):
            if i in rejected_indices:
                continue
            depends_on = sub.get("depends_on") or []
            still_referenced = rejected_indices & set(depends_on)
            if still_referenced:
                raise SubtaskEditError(
                    f"cannot reject subtask index(es) {sorted(still_referenced)} — "
                    f"subtask {i} ({sub.get('title', '')!r}) still depends on it"
                )
        result = [s for i, s in enumerate(result) if i not in rejected_indices]

    return result


def human_review_node(state: PipelineState) -> PipelineState:
    """
    Human-in-the-loop checkpoint.

    interrupt() suspends the graph here; ainvoke() returns the state with
    stage='awaiting_approval'.  When the user clicks "Approve Plan" in the
    dashboard, resume_pipeline() calls ainvoke(Command(resume=...)) which
    resumes this node from after the interrupt() call.

    #227 (2026-09-28) — decision may now also carry "subtask_edits": a
    human can edit or reject individual steps of the plan as part of the
    SAME approval decision, applied here via apply_subtask_edits() before
    the plan is finalized. A malformed edit (bad index, or a rejected step
    another step still depends on) blocks the whole resume with a real
    error rather than silently corrupting the plan or the whole-or-nothing
    approve/reject the plan already had.
    """
    updated: PipelineState = {**state, "stage": "awaiting_approval"}

    # Suspend — caller gets state with stage="awaiting_approval"
    decision: Any = interrupt(
        {
            "action": "plan_review_required",
            "subtasks_count": len(state.get("subtasks", [])),
        }
    )

    # After resume: decision = {"approved": True|False, "subtask_edits": [...]}
    approved = isinstance(decision, dict) and bool(decision.get("approved", False))
    subtask_edits = decision.get("subtask_edits") if isinstance(decision, dict) else None
    final_subtasks = state.get("subtasks", [])
    if approved and subtask_edits:
        final_subtasks = apply_subtask_edits(final_subtasks, subtask_edits)
    final_stage = "done" if approved else "rejected"
    return {
        **updated,
        "approved": approved,
        "stage": final_stage,
        "subtasks": final_subtasks,
    }


def build_graph() -> Any:
    graph: StateGraph[PipelineState] = StateGraph(PipelineState)

    graph.add_node("pm", pm_node)
    graph.add_node("architect", architect_node)
    graph.add_node("decomposer", decomposer_node)
    graph.add_node("human_review", human_review_node)

    graph.add_edge(START, "pm")
    graph.add_conditional_edges(
        "pm", _route_after_pm, {"architect": "architect", END: END}
    )
    graph.add_conditional_edges(
        "architect", _route_after_architect, {"decomposer": "decomposer", END: END}
    )
    graph.add_conditional_edges(
        "decomposer",
        _route_after_decomposer,
        {"human_review": "human_review", END: END},
    )
    graph.add_edge("human_review", END)

    return graph.compile(checkpointer=_checkpointer, interrupt_before=["human_review"])


def get_graph() -> Any:
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


async def run_planning_pipeline(
    task_id: int,
    title: str,
    description: str,
    repo_path: str,
    db: Any = None,
) -> PipelineState:
    """
    Run PM → Architect → Decomposer.
    Stops at human_review checkpoint (stage='awaiting_approval').
    Call resume_pipeline() to continue.

    If db is provided, pre-fetches similar past tasks from engineering memory and
    injects the context into the initial state for the Architect Agent to use.
    """
    from app.memory.store import query_similar_tasks, format_memory_context

    memory_context = ""
    if db is not None:
        try:
            # Stage 4 Cluster O Phase 1b (2026-08-05) — repo-scoped read.
            # task_id is already a required param here, so no new param is
            # needed on this function; resolved via the same cached
            # get_task_repo_id() this phase's other change points use.
            from app.db.repository import get_task_repo_id

            repo_id = await get_task_repo_id(db, task_id)
            similar = await query_similar_tasks(description, db=db, repo_id=repo_id)
            memory_context = format_memory_context(similar)
        except Exception as exc:
            logger.warning("Memory query failed before planning: %s", exc)

    # Day 16 — Image Input Pipeline. Pre-fetch reference images (e.g. a
    # website design screenshot) the same way memory_context is pre-fetched
    # above — once, before the graph runs, so pm_node/architect_node can just
    # read state["images"] rather than each needing db access themselves.
    images: list[dict[str, str]] = []
    if db is not None:
        try:
            from app.db.repository import list_task_images

            rows = await list_task_images(db, task_id)
            images = [{"media_type": r.mime_type, "data": r.base64_data} for r in rows]
        except Exception as exc:
            logger.warning("Image fetch failed before planning: %s", exc)

    graph = get_graph()
    config = {"configurable": {"thread_id": f"task-{task_id}"}}

    initial_state: PipelineState = {
        "task_id": task_id,
        "task_title": title,
        "task_description": description,
        "repo_path": repo_path,
        "stage": "pm",
        "memory_context": memory_context,
        "images": images,
    }

    result: PipelineState = await graph.ainvoke(initial_state, config=config)
    return result


async def resume_pipeline(
    task_id: int,
    approved: bool,
    subtask_edits: list[dict[str, Any]] | None = None,
) -> PipelineState:
    """
    Resume the paused graph after human review.
    approved=True  → stage='done', kicks off coder
    approved=False → stage='rejected'

    subtask_edits (#227, 2026-09-28): optional per-step edits/rejections —
    see apply_subtask_edits()'s own docstring for the exact shape and the
    real dependency-graph safety check. None (the default) is the exact
    prior all-or-nothing behavior for every existing caller.
    """
    graph = get_graph()
    config = {"configurable": {"thread_id": f"task-{task_id}"}}
    result: PipelineState = await graph.ainvoke(
        Command(resume={"approved": approved, "subtask_edits": subtask_edits}),
        config=config,
    )
    return result

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


def human_review_node(state: PipelineState) -> PipelineState:
    """
    Human-in-the-loop checkpoint.

    interrupt() suspends the graph here; ainvoke() returns the state with
    stage='awaiting_approval'.  When the user clicks "Approve Plan" in the
    dashboard, resume_pipeline() calls ainvoke(Command(resume=...)) which
    resumes this node from after the interrupt() call.
    """
    updated: PipelineState = {**state, "stage": "awaiting_approval"}

    # Suspend — caller gets state with stage="awaiting_approval"
    decision: Any = interrupt(
        {
            "action": "plan_review_required",
            "subtasks_count": len(state.get("subtasks", [])),
        }
    )

    # After resume: decision = {"approved": True|False}
    approved = isinstance(decision, dict) and bool(decision.get("approved", False))
    final_stage = "done" if approved else "rejected"
    return {**updated, "approved": approved, "stage": final_stage}


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
            similar = await query_similar_tasks(description, db=db)
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


async def resume_pipeline(task_id: int, approved: bool) -> PipelineState:
    """
    Resume the paused graph after human review.
    approved=True  → stage='done', kicks off coder
    approved=False → stage='rejected'
    """
    graph = get_graph()
    config = {"configurable": {"thread_id": f"task-{task_id}"}}
    result: PipelineState = await graph.ainvoke(
        Command(resume={"approved": approved}), config=config
    )
    return result

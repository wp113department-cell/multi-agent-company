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

# MemorySaver: state persists in-process (survives between requests, lost on restart).
# Swap to AsyncPostgresSaver when libpq is available.
_checkpointer = MemorySaver()


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
    decision: Any = interrupt({
        "action": "plan_review_required",
        "subtasks_count": len(state.get("subtasks", [])),
    })

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
    graph.add_conditional_edges("pm", _route_after_pm, {"architect": "architect", END: END})
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


_compiled_graph: Any = None


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
) -> PipelineState:
    """
    Run PM → Architect → Decomposer.
    Stops at human_review checkpoint (stage='awaiting_approval').
    Call resume_pipeline() to continue.
    """
    graph = get_graph()
    config = {"configurable": {"thread_id": f"task-{task_id}"}}

    initial_state: PipelineState = {
        "task_id": task_id,
        "task_title": title,
        "task_description": description,
        "repo_path": repo_path,
        "stage": "pm",
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

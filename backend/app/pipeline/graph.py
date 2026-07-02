"""LangGraph StateGraph: PM → Architect → Decomposer planning pipeline."""
from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from app.agents.pm import pm_node
from app.agents.architect import architect_node
from app.agents.decomposer import decomposer_node
from app.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

# Checkpointer — MemorySaver works identically to Postgres for pipeline logic.
# Swap to AsyncPostgresSaver when libpq is available on the host.
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
    return END


def build_graph() -> Any:
    graph = StateGraph(PipelineState)

    graph.add_node("pm", pm_node)
    graph.add_node("architect", architect_node)
    graph.add_node("decomposer", decomposer_node)

    graph.add_edge(START, "pm")
    graph.add_conditional_edges("pm", _route_after_pm, {"architect": "architect", END: END})
    graph.add_conditional_edges("architect", _route_after_architect, {"decomposer": "decomposer", END: END})
    graph.add_conditional_edges("decomposer", _route_after_decomposer, {END: END})

    return graph.compile(checkpointer=_checkpointer)


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
    """Run the full PM → Architect → Decomposer pipeline for a task."""
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

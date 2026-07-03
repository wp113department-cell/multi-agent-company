"""LangGraph shared state schema for the planning pipeline."""
from __future__ import annotations

from typing import Any, TypedDict


class PipelineState(TypedDict, total=False):
    task_id: int
    task_title: str
    task_description: str
    repo_path: str

    # PM Agent output
    pm_brief: dict[str, Any]

    # Architect Agent output
    architect_plan: dict[str, Any]

    # Decomposer output
    subtasks: list[dict[str, Any]]

    # Engineering memory context (pre-fetched before pipeline runs)
    memory_context: str

    # Control flow
    stage: str        # pm | architect | decomposer | done | blocked
    error: str
    approved: bool

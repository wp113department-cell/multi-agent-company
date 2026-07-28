"""Uniform result envelope returned by every production agent.

The orchestrator (manager.py / pm.py) handles all agents uniformly via this type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    """Uniform result from every production LangGraph agent.

    verified: True ONLY when the graph's verification dict confirms it — never
              from the model's own claim. See base_graph.py for enforcement.
    """

    summary: str
    # Real usage is mixed across agents: some submit_* schemas declare findings
    # as an array of strings (e.g. debugger_agent.py, code_quality_agent.py —
    # `"findings": {"type": "array", "items": {"type": "string"}}`), others pass
    # structured dicts (e.g. changelog_agent.py). `list[Any]` reflects what's
    # actually populated instead of a `list[dict]` hint half the fleet violates.
    findings: list[Any] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    verified: bool = False  # from state["verification"], never from the model
    requires_human_approval: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    status: str = "completed"  # completed | blocked | needs_approval
    raw: dict[str, Any] = field(
        default_factory=dict
    )  # full result dict from submit_* tool

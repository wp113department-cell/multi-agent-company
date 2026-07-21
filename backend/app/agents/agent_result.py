"""Uniform result envelope returned by every production agent.

The orchestrator (manager.py / pm.py) handles all agents uniformly via this type.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentResult:
    """Uniform result from every production LangGraph agent.

    verified: True ONLY when the graph's verification dict confirms it — never
              from the model's own claim. See base_graph.py for enforcement.
    """

    summary: str
    findings: list[dict] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    verified: bool = False  # from state["verification"], never from the model
    requires_human_approval: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    status: str = "completed"  # completed | blocked | needs_approval
    raw: dict = field(default_factory=dict)  # full result dict from submit_* tool

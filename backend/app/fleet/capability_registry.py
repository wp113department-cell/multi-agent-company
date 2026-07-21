"""Capability Registry — Phase F1.

Each agent publishes a CapabilityEntry describing what it can do, what it needs,
and what it produces. fleet_manager.py queries this registry instead of using
hardcoded if/elif dispatch.

Design decisions:
- In-process singleton (no DB) for Day 0 — fast, zero-latency, no migration needed.
- api/registry.py already stores agent reputation/success_rate in Postgres;
  that data is merged here at query time when a db session is available.
- Registry is write-once per name; re-registering the same name updates in place.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentCapability:
    """Static capability contract published by each agent at import time.

    Why Created: Replaces hardcoded dispatch tables in manager.py / dispatcher.py.
    Alternatives Considered: DB-only registry (too slow for hot dispatch path).
    Why Existing Architecture Was Insufficient: dispatcher.py uses _TYPE_TO_TAG
      dict + fallback if/elif — adding an agent requires code change.
    Dependencies: None (no DB, no network).
    Future Owner: Fleet OS team.
    """

    name: str
    description: str
    tools: list[str]
    input_types: list[str]
    output_types: list[str]
    capabilities: list[str]
    limits: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    avg_runtime_s: float = 0.0
    success_rate: float = 1.0
    requires_worktree: bool = False
    requires_db: bool = False
    risk_level: str = "low"


class CapabilityRegistry:
    """Thread-safe in-process capability registry."""

    def __init__(self) -> None:
        self._entries: dict[str, AgentCapability] = {}
        self._lock = threading.Lock()

    def register(self, entry: AgentCapability) -> None:
        with self._lock:
            self._entries[entry.name] = entry

    def get(self, name: str) -> AgentCapability | None:
        with self._lock:
            return self._entries.get(name)

    def find_by_capability(self, capability: str) -> list[AgentCapability]:
        with self._lock:
            return [e for e in self._entries.values() if capability in e.capabilities]

    def find_by_input_type(self, input_type: str) -> list[AgentCapability]:
        with self._lock:
            return [e for e in self._entries.values() if input_type in e.input_types]

    def all(self) -> list[AgentCapability]:
        with self._lock:
            return list(self._entries.values())

    def names(self) -> list[str]:
        with self._lock:
            return list(self._entries.keys())

    def count(self) -> int:
        with self._lock:
            return len(self._entries)


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_registry = CapabilityRegistry()


def get_capability_registry() -> CapabilityRegistry:
    return _registry


def register(entry: AgentCapability) -> None:
    _registry.register(entry)


# ---------------------------------------------------------------------------
# Reference agent registrations (Day 0 — 3 agents)
# Validate architecture before fleet-wide rollout.
# ---------------------------------------------------------------------------

register(
    AgentCapability(
        name="pm",
        description="Product Manager — translates task descriptions into goals, constraints, and acceptance criteria.",
        tools=[
            "read_file",
            "list_files",
            "search_code",
            "search_symbols",
            "get_file_tree",
            "git_log",
            "read_files",
            "file_exists",
            "file_info",
            "find_references",
            "find_todos",
            "search_imports",
            "git_status",
            "git_show",
            "git_blame",
            "analyze_file",
            "submit_brief",
        ],
        input_types=["task_description", "repo_path"],
        output_types=["pm_brief"],
        capabilities=["planning", "requirement_analysis", "goal_extraction"],
        limits={"max_turns": 8},
        dependencies=[],
        avg_runtime_s=15.0,
        success_rate=0.95,
        requires_worktree=False,
        requires_db=False,
        risk_level="low",
    )
)

register(
    AgentCapability(
        name="bug_fix",
        description="Bug Fix specialist — diagnoses and repairs reported bugs using read/edit/test cycle.",
        tools=[
            "read_file",
            "list_files",
            "search_code",
            "search_symbols",
            "get_file_tree",
            "git_log",
            "read_files",
            "file_exists",
            "file_info",
            "find_references",
            "find_todos",
            "search_imports",
            "git_status",
            "git_show",
            "git_blame",
            "analyze_file",
            "edit_file",
            "write_file",
            "git_diff",
            "bash",
            "submit_patch",
        ],
        input_types=["task_id", "error_description", "repo_path"],
        output_types=["AgentResult"],
        capabilities=["bug_fix", "code_edit", "fix_regression_check", "git_diff"],
        limits={"max_turns": 20, "max_retries": 3},
        dependencies=["qa"],
        avg_runtime_s=45.0,
        success_rate=0.82,
        requires_worktree=True,
        requires_db=False,
        risk_level="medium",
    )
)

register(
    AgentCapability(
        name="qa",
        description="QA Agent — runs tests, typecheck, linter in a worktree. Read + bash (test only). No writes.",
        tools=[
            "read_file",
            "list_files",
            "search_code",
            "search_symbols",
            "get_file_tree",
            "git_log",
            "read_files",
            "file_exists",
            "file_info",
            "find_references",
            "find_todos",
            "search_imports",
            "git_status",
            "git_show",
            "git_blame",
            "analyze_file",
            "bash",
            "submit_qa_result",
        ],
        input_types=["task_id", "subtask_id", "files_changed", "worktree_path"],
        output_types=["QAResult"],
        capabilities=["test_execution", "typecheck", "lint", "qa_verification"],
        limits={"max_turns": 12},
        dependencies=[],
        avg_runtime_s=30.0,
        success_rate=0.91,
        requires_worktree=True,
        requires_db=False,
        risk_level="low",
    )
)

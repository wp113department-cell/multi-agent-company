"""agent_roster_doc_agent — Day 53 doc generator.

Gap-closure Day 53 (Stage 2, answers.md Q41 "Agent docs: NOT FOUND — no
agent generates documentation about the other 72 agents; the existing
agent-creation guide is a static, human-written doc"). Uses
list_registered_agents (app.agents.tools) — real introspection of the
actual fleet capability_registry, via ensure_all_agents_registered() so
every real agent module is imported first — as the grounding data, not a
guess from file names or memory of what agents "should" exist.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    _LIST_REGISTERED_AGENTS_TOOL,
    _SUBMIT_DOCS_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    READ_ONLY_TOOLS,
    RECORD_LEARNING_TOOL,
    list_registered_agents,
    make_doc_generator_handlers,
    make_record_learning_handler,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

AGENT_CONTRACT: dict[str, Any] = {
    "name": "agent_roster_doc_agent",
    "description": "Generates and maintains a real agent-roster document from the actual fleet capability_registry — every registered agent's name, description, tools, and risk level.",
    "allowed_tools": [
        "read_file",
        "list_files",
        "get_file_tree",
        "file_exists",
        "list_registered_agents",
        "write_file",
        "submit_docs",
        "record_learning",
    ],
    "input_types": ["task_id", "doc_request", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["writes an agent-roster markdown file"],
    "permissions": ["read_repo", "write_docs"],
    "risk_level": "low",
    "expected_verification": {
        "roster_read": "list_registered_agents must run before writing"
    },
    "dependencies": [],
}

_TOOLS = READ_ONLY_TOOLS + [
    _LIST_REGISTERED_AGENTS_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_DOCS_TOOL,
]

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "list_registered_agents": "roster_read",
        "write_file": "docs_written",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"roster_read": "roster_read"},
    initial={"roster_read": False, "docs_written": False},
)


def make_agent_roster_doc_handlers(repo_path: str) -> dict[str, Any]:
    handlers = make_doc_generator_handlers(repo_path)
    handlers["list_registered_agents"] = list_registered_agents
    handlers["record_learning"] = make_record_learning_handler("agent_roster_doc_agent")
    return handlers


def run_agent_roster_doc_agent(
    task_id: int,
    doc_request: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_agent_roster_doc_handlers(repo)

    message = (
        f"Task #{task_id} — Agent Roster Documentation\n\n{doc_request}\n\n"
        "Process:\n"
        "1. Call list_registered_agents — MANDATORY, this is the real, complete list of "
        "   every registered agent (name, description, tools, capabilities, risk_level). "
        "   Never invent an agent that isn't in this real list, and never omit one that is.\n"
        "2. Group agents sensibly (e.g. by risk_level or by capability) for readability.\n"
        "3. Write the roster as markdown (e.g. docs/AGENTS.md) — one entry per real agent "
        "   with its real description, real tools, and real risk_level.\n"
        "4. Call submit_docs with files_written and summary."
    )

    final_state = run_agent_graph(
        task_id=str(task_id),
        role_name="agent_roster_doc_agent",
        model=settings.model_planner,
        tools=_TOOLS + [RECORD_LEARNING_TOOL],
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        task_description=doc_request[:120],
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=20,
    )

    raw = final_state["result"]
    return AgentResult(
        summary=str(
            raw.get("summary", f"Docs written: {raw.get('files_written', [])}")
        ),
        findings=[],
        files_touched=list(raw.get("files_written", [])),
        verified=bool(final_state["verification"].get("roster_read", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )


def _register() -> None:
    try:
        from app.fleet.capability_registry import AgentCapability, register
        from app.fleet.agent_registry import get_agent_registry

        register(
            AgentCapability(
                name=AGENT_CONTRACT["name"],
                description=AGENT_CONTRACT["description"],
                tools=AGENT_CONTRACT["allowed_tools"],
                input_types=AGENT_CONTRACT["input_types"],
                output_types=AGENT_CONTRACT["output_types"],
                capabilities=["agent_roster_documentation", "fleet_roster_generation"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()

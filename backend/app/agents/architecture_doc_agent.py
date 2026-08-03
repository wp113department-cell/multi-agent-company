"""architecture_doc_agent — Day 53 doc generator.

Gap-closure Day 53 (Stage 2, answers.md Q41 "Architecture docs: NOT FOUND
as a dedicated doc-writer — architecture_reviewer produces findings, not a
maintained ARCHITECTURE.md"). Reuses architecture_reviewer's own real,
existing import-graph/circular-dep/dead-code/call-graph tools (Day 48's
scan mode already proved this pattern works for autonomous re-use) as the
real, introspected data source — never asks the LLM to guess module
relationships from memory. Writes a maintained ARCHITECTURE.md, distinct
from architecture_reviewer's own findings-only output.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    _CALL_GRAPH_TOOL,
    _CIRCULAR_DEP_DETECT_TOOL,
    _DEAD_CODE_DETECT_TOOL,
    _IMPORT_GRAPH_TOOL,
    _LIST_CLASSES_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _PARSE_AST_TOOL,
    _SUBMIT_DOCS_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    READ_ONLY_TOOLS,
    RECORD_LEARNING_TOOL,
    make_arch_reviewer_handlers,
    make_doc_generator_handlers,
    make_record_learning_handler,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

AGENT_CONTRACT: dict[str, Any] = {
    "name": "architecture_doc_agent",
    "description": "Generates and maintains ARCHITECTURE.md from real import-graph/circular-dependency/dead-code/call-graph introspection of the codebase.",
    "allowed_tools": [
        "read_file",
        "list_files",
        "search_code",
        "get_file_tree",
        "read_files",
        "file_exists",
        "file_info",
        "import_graph",
        "circular_dep_detect",
        "dead_code_detect",
        "call_graph",
        "parse_ast",
        "list_functions",
        "list_classes",
        "write_file",
        "submit_docs",
        "record_learning",
    ],
    "input_types": ["task_id", "doc_request", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["writes ARCHITECTURE.md"],
    "permissions": ["read_repo", "write_docs"],
    "risk_level": "low",
    "expected_verification": {
        "graph_read": "import_graph or circular_dep_detect must run before writing"
    },
    "dependencies": [],
}

_TOOLS = READ_ONLY_TOOLS + [
    _IMPORT_GRAPH_TOOL,
    _CIRCULAR_DEP_DETECT_TOOL,
    _DEAD_CODE_DETECT_TOOL,
    _CALL_GRAPH_TOOL,
    _PARSE_AST_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_DOCS_TOOL,
]

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "import_graph": "graph_read",
        "circular_dep_detect": "graph_read",
        "write_file": "docs_written",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"graph_read": "graph_read"},
    initial={"graph_read": False, "docs_written": False},
)


def make_architecture_doc_handlers(repo_path: str) -> dict[str, Any]:
    """architecture_reviewer's real introspection tools + doc-generator's
    write_file (*.md-scoped)/submit_docs, instead of submit_arch_review."""
    handlers = make_arch_reviewer_handlers(repo_path)
    doc_handlers = make_doc_generator_handlers(repo_path)
    handlers["write_file"] = doc_handlers["write_file"]
    handlers["submit_docs"] = doc_handlers["submit_docs"]
    handlers["_docs_result"] = doc_handlers["_docs_result"]
    handlers["record_learning"] = make_record_learning_handler("architecture_doc_agent")
    return handlers


def run_architecture_doc_agent(
    task_id: int,
    doc_request: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_architecture_doc_handlers(repo)

    message = (
        f"Task #{task_id} — ARCHITECTURE.md Generation\n\n{doc_request}\n\n"
        "Process:\n"
        "1. Use get_file_tree to map the real repo structure.\n"
        "2. Use import_graph and circular_dep_detect on the main package(s) — MANDATORY, "
        "   these are the real data this doc is grounded in.\n"
        "3. Use call_graph/dead_code_detect/list_functions/list_classes as needed for detail.\n"
        "4. Write ARCHITECTURE.md describing real module boundaries, real dependency "
        "   direction, and any real circular dependencies found — never an invented "
        "   architecture that doesn't match the actual import graph.\n"
        "5. Call submit_docs with files_written and summary."
    )

    final_state = run_agent_graph(
        task_id=str(task_id),
        role_name="architecture_doc_agent",
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
        verified=bool(final_state["verification"].get("graph_read", False)),
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
                capabilities=[
                    "architecture_documentation",
                    "architecture_doc_generation",
                ],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()

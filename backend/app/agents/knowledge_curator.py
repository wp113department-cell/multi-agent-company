"""knowledge_curator — Day 9 fleet self-improvement agent.

Curates the fleet's persistent engineering memory (memory_embeddings — not the
in-process LessonStore, and not the unrelated per-repo memory_read/memory_write
KV tools) so future memory_hook_node injections stay accurate, deduplicated,
and well-categorized. The concrete mechanism by which this helps agents
"understand what's needed and go the right way": that memory is what gets
injected into every agent's context before it starts work.
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    FLEET_APPLY_TOOLS,
    READ_ONLY_TOOLS,
    make_fleet_apply_handlers,
    make_read_only_handlers,
    make_submit_enhancement_request_handler,
    memory_curate_read,
    memory_curate_write,
    memory_search,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

AGENT_CONTRACT: dict[str, Any] = {
    "name": "knowledge_curator",
    "description": "Curates the fleet's persistent engineering memory (memory_embeddings) — dedupes, recategorizes, and quality-checks entries so future agent runs get accurate context. Never writes code; its apply phase only touches memory rows and, occasionally, role prompts.",
    "allowed_tools": [
        "read_file", "memory_search", "memory_curate_read", "submit_enhancement_request",
        "memory_curate_write", "write_file", "edit_file", "git_commit_change", "submit_fix",
    ],
    "input_types": ["scan_trigger", "enhancement_request_id"],
    "output_types": ["AgentResult"],
    "side_effects": ["files enhancement requests (scan)", "updates memory rows and/or role prompts (apply, post-approval only)"],
    "permissions": ["read_repo", "write_memory"],
    "risk_level": "medium",
    "expected_verification": {"memory_searched": "memory_search or memory_curate_read must run before filing a request"},
    "dependencies": [],
}

_MEMORY_SEARCH_TOOL_SPEC = {
    "name": "memory_search",
    "description": "Semantic search over the fleet's persistent engineering memory.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
        "required": ["query"],
    },
}
_MEMORY_CURATE_READ_TOOL_SPEC = {
    "name": "memory_curate_read",
    "description": "List memory entries for curation review (duplicates, stale/mis-categorized entries).",
    "input_schema": {
        "type": "object",
        "properties": {"category": {"type": "string"}, "limit": {"type": "integer"}},
        "required": [],
    },
}
_MEMORY_CURATE_WRITE_TOOL_SPEC = {
    "name": "memory_curate_write",
    "description": "Update a memory entry during curation (recategorize, or note a supersession).",
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "category": {"type": "string"},
            "note": {"type": "string"},
        },
        "required": ["id"],
    },
}
_SUBMIT_ENHANCEMENT_TOOL_SPEC = {
    "name": "submit_enhancement_request",
    "description": "File a proposed memory-curation action for human review.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "category": {"type": "string", "enum": ["performance", "bug", "orchestration", "knowledge", "quality", "security"]},
            "priority": {"type": "string", "enum": ["emergency", "medium", "low"]},
            "evidence": {"type": "object"},
        },
        "required": ["title", "description", "category", "priority"],
    },
}
_SUBMIT_FIX_TOOL_SPEC = {
    "name": "submit_fix",
    "description": "Signal the curation action is complete.",
    "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
}

SCAN_TOOLS = [READ_ONLY_TOOLS[0], _MEMORY_SEARCH_TOOL_SPEC, _MEMORY_CURATE_READ_TOOL_SPEC, _SUBMIT_ENHANCEMENT_TOOL_SPEC]
_WRITE_FILE_SPEC, _EDIT_FILE_SPEC, _RUN_TESTS_SPEC, _GIT_COMMIT_SPEC = FLEET_APPLY_TOOLS[1:]
APPLY_TOOLS = [READ_ONLY_TOOLS[0], _MEMORY_CURATE_WRITE_TOOL_SPEC, _WRITE_FILE_SPEC, _EDIT_FILE_SPEC, _GIT_COMMIT_SPEC, _SUBMIT_FIX_TOOL_SPEC]

_SCAN_CFG = VerificationConfig(
    set_by={"memory_search": "memory_searched", "memory_curate_read": "memory_searched"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"memory_searched": "memory_searched"},
    initial={"memory_searched": False},
)

_APPLY_CFG = VerificationConfig(
    set_by={"memory_curate_write": "curated", "git_commit_change": "committed"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"curated": "curated"},
    initial={"curated": False, "committed": False},
)


def make_scan_handlers(repo_path: str, trace_id: str = "") -> dict[str, Any]:
    handlers = make_read_only_handlers(repo_path)
    handlers["memory_search"] = memory_search
    handlers["memory_curate_read"] = memory_curate_read
    handlers["submit_enhancement_request"] = make_submit_enhancement_request_handler(
        "knowledge_curator", trace_id=trace_id
    )
    return handlers


def make_apply_handlers(repo_path: str) -> dict[str, Any]:
    handlers = make_fleet_apply_handlers(repo_path)
    handlers["memory_curate_write"] = memory_curate_write
    return handlers


def run_knowledge_curator_scan(trace_id: str = "") -> AgentResult:
    """SCAN phase — autonomous, read-only. Never writes to memory itself."""
    settings = get_settings()
    repo = settings.fleet_self_repo_path
    handlers = make_scan_handlers(repo, trace_id=trace_id)

    msg = (
        "Review the fleet's persistent engineering memory for curation issues: duplicate or "
        "near-duplicate entries, stale entries that no longer reflect reality, entries "
        "mis-categorized (task | architecture | failure | learning), or gaps where an obvious "
        "lesson was never recorded. Use memory_curate_read to browse recent entries and "
        "memory_search to check whether a topic already has coverage before assuming it's "
        "missing. If you find a real curation issue, file submit_enhancement_request with "
        "category=knowledge, describing the specific entries involved and the proposed "
        "action. If memory looks clean, that's a normal outcome — don't invent an issue."
    )

    final_state = run_agent_graph(
        role_name="knowledge_curator",
        model=settings.model_coder,
        tools=SCAN_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_SCAN_CFG,
        initial_message=msg,
        task_description="Engineering memory curation scan",
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=15,
        trace_id=trace_id,
    )

    return AgentResult(
        summary="Curation scan complete" if final_state["submitted"] else "Curation scan complete — memory looks clean",
        findings=[],
        files_touched=[],
        verified=bool(final_state["verification"].get("memory_searched")) or not final_state["submitted"],
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed",
        raw=final_state.get("result", {}),
    )


def run_knowledge_curator_apply(request_id: int, description: str, trace_id: str = "") -> AgentResult:
    """APPLY phase — only ever called after a human approves `request_id`.

    Most approved requests only touch memory rows via memory_curate_write (no git commit
    needed for that). Occasionally a curation finding also warrants a role-prompt tweak —
    write_file/git_commit_change are available for that, but should be the exception."""
    settings = get_settings()
    repo = settings.fleet_self_repo_path
    handlers = make_apply_handlers(repo)

    def submit_h(inp: dict[str, Any]) -> str:
        return "done"
    handlers["submit_fix"] = submit_h

    msg = (
        f"Approved curation action #{request_id}: {description}\n\n"
        "Carry out this specific curation action using memory_curate_write. Only use "
        "write_file/edit_file/git_commit_change if the action specifically calls for a "
        "role-prompt change — most curation actions only touch memory rows. Call submit_fix "
        "when done."
    )

    final_state = run_agent_graph(
        role_name="knowledge_curator",
        model=settings.model_coder,
        tools=APPLY_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_APPLY_CFG,
        initial_message=msg,
        task_description=f"Apply curation #{request_id}",
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=15,
        trace_id=trace_id,
    )

    return AgentResult(
        summary=f"Applied curation #{request_id}",
        findings=[],
        files_touched=[],
        verified=bool(final_state["verification"].get("curated")),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["verification"].get("curated") else "blocked",
        raw=final_state.get("result", {}),
    )


def _register() -> None:
    try:
        from app.fleet.capability_registry import AgentCapability, register
        from app.fleet.agent_registry import get_agent_registry
        register(AgentCapability(
            name=AGENT_CONTRACT["name"],
            description=AGENT_CONTRACT["description"],
            tools=AGENT_CONTRACT["allowed_tools"],
            input_types=AGENT_CONTRACT["input_types"],
            output_types=AGENT_CONTRACT["output_types"],
            capabilities=["knowledge_curation"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry unavailable: %s", exc)


_register()

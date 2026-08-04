"""Architect Agent — LangGraph node: PM brief + repo context → technical plan.

Session 1 migration (2026-07-16):
- Replaced run_agent() with run_agent_graph() — gains all 9 Fleet OS state fields,
  LessonStore, stall detection, run_span metrics, and context trim automatically.
- Added AGENT_CONTRACT (risk_level: low — read-only, no side effects).
- Registered in capability_registry at module level.
- External interface (architect_node signature) unchanged — pipeline/graph.py unaffected.

Pattern from: swe-agent RetryAgent (preserve external interface, swap internal runner).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import (
    READ_ONLY_TOOLS,
    RECORD_LEARNING_TOOL,
    make_read_only_handlers,
    make_record_learning_handler,
)
from app.config import get_settings
from app.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------

AGENT_CONTRACT: dict[str, Any] = {
    "name": "architect",
    "description": "Reads PM brief + codebase to produce a technical plan with impacted files and risks.",
    "allowed_tools": [
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
        "submit_architect_plan",
        "record_learning",
    ],
    "input_types": ["pm_brief", "repo_path", "task_title"],
    "output_types": ["architect_plan"],
    "side_effects": [],
    "permissions": ["read_repo"],
    "risk_level": "low",
    "expected_verification": {},
    "dependencies": ["pm"],
}

# ---------------------------------------------------------------------------
# Submit tool schema
# ---------------------------------------------------------------------------

_SUBMIT_TOOL: dict[str, Any] = {
    "name": "submit_architect_plan",
    "description": "Submit the completed architect plan as structured JSON.",
    "input_schema": {
        "type": "object",
        "properties": {
            "technical_approach": {"type": "string"},
            "impacted_files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["path", "reason"],
                },
            },
            "risks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                        },
                        "description": {"type": "string"},
                    },
                    "required": ["severity", "description"],
                },
            },
            "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
        },
        "required": ["technical_approach", "impacted_files", "risks", "risk_level"],
    },
}

# ---------------------------------------------------------------------------
# Verification contract — read-only agent, no mutation to reset
# ---------------------------------------------------------------------------

_VERIFICATION_CFG = VerificationConfig(
    set_by={"submit_architect_plan": "plan_submitted"},
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"plan_submitted": "plan_submitted"},
    initial={"plan_submitted": False},
)

# ---------------------------------------------------------------------------
# Pipeline node — external interface unchanged from Day 3
# ---------------------------------------------------------------------------


def architect_node(state: PipelineState) -> PipelineState:
    settings = get_settings()
    repo = state.get("repo_path", settings.target_repo_path)

    handlers = make_read_only_handlers(repo)
    handlers["submit_architect_plan"] = lambda inp: "Architect plan submitted"
    handlers["record_learning"] = make_record_learning_handler("architect")

    # Day 18 — Real-Time Streaming.
    stream_task_id = str(state.get("task_id", ""))
    try:
        from app.services.activity_stream import push_agent_switch

        push_agent_switch(stream_task_id, "architect", "planning")
    except Exception:
        pass

    pm_brief = json.dumps(state.get("pm_brief", {}), indent=2)
    memory_context = state.get("memory_context", "")
    memory_block = f"\n\n{memory_context}" if memory_context else ""

    # Day 16 — Image Input Pipeline.
    images = state.get("images", [])
    image_block = (
        f"\n\n{len(images)} reference image(s) are attached below — base the "
        "component structure and impacted files on what they show."
        if images
        else ""
    )

    initial_message = (
        f"Task: {state['task_title']}\n\n"
        f"PM Brief:\n{pm_brief}"
        f"{memory_block}{image_block}\n\n"
        "Use read_file and list_files to explore the codebase, then submit your technical plan "
        "using the submit_architect_plan tool."
    )

    try:
        final_state = run_agent_graph(
            role_name="architect",
            model=settings.model_planner,
            tools=READ_ONLY_TOOLS + [_SUBMIT_TOOL, RECORD_LEARNING_TOOL],
            tool_handlers=handlers,
            verification_cfg=_VERIFICATION_CFG,
            initial_message=initial_message,
            task_description=state["task_title"],
            repo_path=repo,
            model_haiku=settings.model_router,
            enable_planning=True,
            enable_memory=True,
            enable_reflection=True,
            enable_lesson=True,
            human_approval_required=False,
            images=images,
            max_turns=15,
            task_id=stream_task_id,
        )
        logger.info(
            "Architect Agent done — tokens_in=%d tokens_out=%d submitted=%s",
            final_state.get("tokens_in", 0),
            final_state.get("tokens_out", 0),
            final_state.get("submitted", False),
        )
    except Exception as exc:
        logger.exception("Architect Agent failed")
        return {**state, "stage": "blocked", "error": f"Architect Agent failed: {exc}"}

    plan_result = final_state.get("result", {})
    if not plan_result or not final_state.get("submitted"):
        return {
            **state,
            "stage": "blocked",
            "error": "Architect Agent did not submit a plan",
        }

    # Strip internal Fleet OS keys before storing in pipeline state
    clean_plan = {k: v for k, v in plan_result.items() if not k.startswith("_")}

    # MASTER_AGENT_v2.md Phase 1.1 — architect is the one architecture-tagged
    # agent that runs through this pipeline node rather than
    # app/api/specialized_agents.py's dispatch (which the other 3 named
    # architecture agents use, wired via app/memory/hooks.py instead), so it
    # needs its own direct write here — this pipeline has no other memory-write
    # hook to piggyback on.
    technical_approach = str(clean_plan.get("technical_approach", ""))
    if technical_approach:
        try:
            from app.memory.store import embed_architecture_note_sync

            # Stage 4 Cluster O Phase 1b (2026-08-05) — repo-scoped write.
            # Reuses the same cached sync resolver run_agent_graph() uses
            # (app/db/repository.py::get_task_repo_id_sync) rather than
            # threading a new param through PipelineState — stream_task_id
            # is already the same value that resolver expects. Non-numeric
            # (the synthetic "architect-{title}" fallback) correctly
            # resolves to unscoped/global, same as every other synthetic-id
            # case in this codebase.
            from app.db.repository import get_task_repo_id_sync

            repo_id: int | None = None
            if stream_task_id:
                try:
                    repo_id = get_task_repo_id_sync(int(stream_task_id))
                except (ValueError, TypeError):
                    repo_id = None

            embed_architecture_note_sync(
                task_id=stream_task_id or f"architect-{state['task_title'][:40]}",
                content=technical_approach,
                agent_name="architect",
                repo_id=repo_id,
            )
        except Exception:
            logger.debug(
                "architect_node: embed_architecture_note_sync skipped", exc_info=True
            )

    return {**state, "architect_plan": clean_plan, "stage": "decomposer"}


# ---------------------------------------------------------------------------
# Capability registry registration
# ---------------------------------------------------------------------------


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
                capabilities=["architecture_design", "technical_planning"],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register("architect")
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()

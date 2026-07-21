"""RAG Engineer Agent — designs RAG pipelines and writes retrieval code.

Verification contract:
  - codebase_read: set True when read_file or search_code used to understand existing code
  - code_written: set True when write_file is called
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import READ_ONLY_TOOLS, make_chat_handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "rag_engineer_agent",
    "description": "Designs and implements RAG pipelines: chunking strategy, embedding model selection, vector store setup, and retrieval strategy.",
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
        "search_imports",
        "write_file",
        "run_python_snippet",
        "submit_rag_design",
    ],
    "input_types": ["task_id", "description", "repo_path"],
    "output_types": ["AgentResult"],
    "side_effects": ["may write pipeline implementation files"],
    "permissions": ["read_repo", "write_repo", "execute_code"],
    "risk_level": "medium",
    "expected_verification": {
        "codebase_read": "must inspect existing infrastructure before designing RAG pipeline"
    },
    "dependencies": [],
}

_SUBMIT_RAG_TOOL: dict[str, Any] = {
    "name": "submit_rag_design",
    "description": "Submit the RAG pipeline design.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "1-2 sentence overview"},
            "chunking_strategy": {
                "type": "string",
                "description": "e.g. recursive character, sentence, semantic",
            },
            "embedding_model": {
                "type": "string",
                "description": "Model name (e.g. voyage-code-2, text-embedding-3-small)",
            },
            "vector_store": {
                "type": "string",
                "description": "e.g. pgvector, Qdrant, Chroma, FAISS",
            },
            "retrieval_strategy": {
                "type": "string",
                "description": "e.g. top-k cosine, MMR, hybrid BM25+dense",
            },
            "implementation_notes": {"type": "array", "items": {"type": "string"}},
            "files_written": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "summary",
            "chunking_strategy",
            "embedding_model",
            "vector_store",
            "retrieval_strategy",
        ],
    },
}

_RAG_TOOLS = READ_ONLY_TOOLS + [
    {
        "name": "write_file",
        "description": "Write a file to the repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_python_snippet",
        "description": "Execute a Python snippet to test retrieval logic.",
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
    _SUBMIT_RAG_TOOL,
]

_VERIFICATION_CFG = VerificationConfig(
    set_by={
        "read_file": "codebase_read",
        "search_code": "codebase_read",
        "write_file": "code_written",
    },
    reset_by=(),
    reset_keys=(),
    enforce_in_result={"codebase_read": "codebase_read"},
    initial={"codebase_read": False, "code_written": False},
)


def make_rag_engineer_handlers(repo_path: str) -> dict[str, Any]:
    base = make_chat_handlers(repo_path)
    submitted: dict[str, Any] = {}

    def submit_rag_h(inp: dict[str, Any]) -> str:
        submitted.update(inp)
        return f"RAG design submitted: {inp.get('vector_store', '?')} + {inp.get('embedding_model', '?')}"

    base["submit_rag_design"] = submit_rag_h
    base["_rag_result"] = submitted
    return base


def run_rag_engineer_agent(
    task_id: int,
    description: str,
    repo_path: str | None = None,
    on_heartbeat: Any = None,
    on_tool_call: Any = None,
) -> AgentResult:
    settings = get_settings()
    repo = repo_path or str(settings.target_repo_path)
    handlers = make_rag_engineer_handlers(repo)
    submitted = handlers["_rag_result"]

    message = (
        f"Task #{task_id} — RAG Pipeline Design\n\n"
        f"{description}\n\n"
        "Process:\n"
        "1. Use read_file / search_code to understand existing data sources and embedding infrastructure — MANDATORY.\n"
        "2. Design the chunking strategy (chunk size, overlap, splitter type).\n"
        "3. Choose the embedding model based on the content type and existing infrastructure.\n"
        "4. Select the vector store considering existing setup (pgvector if PostgreSQL exists).\n"
        "5. Define the retrieval strategy (top-k, MMR, hybrid). Write implementation code if possible.\n"
        "6. Call submit_rag_design with all design decisions."
    )

    final_state = run_agent_graph(
        role_name="rag_engineer_agent",
        model=settings.model_coder,
        tools=_RAG_TOOLS,
        tool_handlers=handlers,
        verification_cfg=_VERIFICATION_CFG,
        initial_message=message,
        task_description=description[:120],
        repo_path=repo,
        model_haiku=settings.model_router,
        enable_planning=True,
        enable_memory=True,
        enable_reflection=True,
        enable_lesson=True,
        max_turns=20,
    )

    raw = submitted if submitted else final_state["result"]
    return AgentResult(
        summary=f"RAG design: {raw.get('vector_store', '?')} | {raw.get('embedding_model', '?')} | {raw.get('retrieval_strategy', '?')}. {raw.get('summary', '')}",
        findings=raw.get("implementation_notes", []),
        files_touched=raw.get("files_written", []),
        verified=bool(final_state["verification"].get("codebase_read", False)),
        requires_human_approval=False,
        tokens_in=final_state["tokens_in"],
        tokens_out=final_state["tokens_out"],
        status="completed" if final_state["submitted"] else "blocked",
        raw=raw,
    )


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
                capabilities=[
                    "rag_pipeline_design",
                    "vector_store_selection",
                    "retrieval_engineering",
                ],
                risk_level=AGENT_CONTRACT["risk_level"],
                dependencies=AGENT_CONTRACT["dependencies"],
            )
        )
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()

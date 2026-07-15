"""RAG Engineer Agent — designs RAG pipelines and writes retrieval code.

Verification contract:
  - codebase_read: set True when read_file or search_code used to understand existing code
  - code_written: set True when write_file is called
"""
from __future__ import annotations

from typing import Any

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.agents.tools import READ_ONLY_TOOLS, make_chat_handlers
from app.config import get_settings

_SUBMIT_RAG_TOOL: dict[str, Any] = {
    "name": "submit_rag_design",
    "description": "Submit the RAG pipeline design.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "1-2 sentence overview"},
            "chunking_strategy": {"type": "string", "description": "e.g. recursive character, sentence, semantic"},
            "embedding_model": {"type": "string", "description": "Model name (e.g. voyage-code-2, text-embedding-3-small)"},
            "vector_store": {"type": "string", "description": "e.g. pgvector, Qdrant, Chroma, FAISS"},
            "retrieval_strategy": {"type": "string", "description": "e.g. top-k cosine, MMR, hybrid BM25+dense"},
            "implementation_notes": {"type": "array", "items": {"type": "string"}},
            "files_written": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "chunking_strategy", "embedding_model", "vector_store", "retrieval_strategy"],
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
    enforce_in_result={},
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

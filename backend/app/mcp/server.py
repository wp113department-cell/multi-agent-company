"""MCP stdio server — exposes repo intelligence tools over JSON-RPC 2.0."""

from __future__ import annotations

import json
import sys
import logging
from typing import Any

from app.config import get_settings
from app.repo_tools.scanner import index_repository, build_call_graph
from app.repo_tools.context_builder import build_context

logger = logging.getLogger(__name__)

# Tool manifest — declared once, returned on initialize
_TOOLS = [
    {
        "name": "index_repository",
        "description": "Index the repository and return file + symbol counts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to repo (default: TARGET_REPO_PATH)",
                },
            },
        },
    },
    {
        "name": "search_symbols",
        "description": "Search for symbols by name across the indexed repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Symbol name or partial name",
                },
                "repo_path": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "build_context",
        "description": "Build context for a task — returns relevant files, dependencies, symbols.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_description": {"type": "string"},
                "repo_path": {"type": "string"},
            },
            "required": ["task_description"],
        },
    },
    {
        "name": "query_dependencies",
        "description": "Return files that a given file imports (direct dependencies).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Relative file path"},
                "repo_path": {"type": "string"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "semantic_search",
        "description": "Search for files most relevant to a query using keyword scoring (falls back gracefully when Voyage embeddings are not pre-built).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query",
                },
                "repo_path": {"type": "string"},
                "top_k": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_file_summary",
        "description": "Return the list of symbols (functions, classes, variables) defined in a file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative file path within the repo",
                },
                "repo_path": {"type": "string"},
            },
            "required": ["file_path"],
        },
    },
]


def _get_repo(params: dict[str, Any]) -> str:
    return params.get("repo_path") or get_settings().target_repo_path


def _handle(method: str, params: dict[str, Any]) -> Any:
    settings = get_settings()  # noqa: F841

    if method == "tools/list":
        return {"tools": _TOOLS}

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_params = params.get("arguments", {})
        repo = _get_repo(tool_params)

        if tool_name == "index_repository":
            idx = index_repository(repo)
            total_symbols = sum(len(f.symbols) for f in idx.files.values())
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"files": len(idx.files), "symbols": total_symbols}
                        ),
                    }
                ]
            }

        if tool_name == "search_symbols":
            query = tool_params.get("query", "").lower()
            idx = index_repository(repo)
            matches = []
            for rel_path, fi in idx.files.items():
                for sym in fi.symbols:
                    if query in sym.name.lower():
                        matches.append(
                            {
                                "file": rel_path,
                                "name": sym.name,
                                "kind": sym.kind,
                                "line": sym.line_start,
                            }
                        )
            return {"content": [{"type": "text", "text": json.dumps(matches[:50])}]}

        if tool_name == "build_context":
            idx = index_repository(repo)
            ctx = build_context(
                task_description=tool_params["task_description"], index=idx
            )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "relevant_files": ctx.relevant_files,
                                "dependency_chain": ctx.dependency_chain,
                                "related_symbols": ctx.related_symbols,
                                "summary": ctx.summary,
                            }
                        ),
                    }
                ]
            }

        if tool_name == "query_dependencies":
            file_path = tool_params.get("file_path", "")
            idx = index_repository(repo)
            edges = build_call_graph(idx)
            deps = edges.get(file_path, [])
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"file": file_path, "dependencies": deps}),
                    }
                ]
            }

        if tool_name == "semantic_search":
            import re

            query = tool_params.get("query", "")
            top_k = int(tool_params.get("top_k", 20))
            idx = index_repository(repo)
            query_tokens = [w.lower() for w in re.split(r"\W+", query) if len(w) > 2]
            scores: dict[str, float] = {}
            for rel_path, fi in idx.files.items():
                symbol_names = [s.name for s in fi.symbols]
                combined = (
                    rel_path.lower() + " " + " ".join(s.lower() for s in symbol_names)
                )
                scores[rel_path] = sum(1.0 for tok in query_tokens if tok in combined)
            sorted_files = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            results = [{"file": p, "score": s} for p, s in sorted_files if s > 0][
                :top_k
            ]
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"results": results, "query": query}),
                    }
                ]
            }

        if tool_name == "get_file_summary":
            file_path = tool_params.get("file_path", "")
            idx = index_repository(repo)
            file_info = idx.files.get(file_path)
            if file_info is None:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"error": f"File not found: {file_path}"}
                            ),
                        }
                    ]
                }
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "file": file_path,
                                "language": file_info.language,
                                "symbols": [
                                    {
                                        "name": s.name,
                                        "kind": s.kind,
                                        "line": s.line_start,
                                    }
                                    for s in file_info.symbols
                                ],
                                "imports": file_info.imports,
                            }
                        ),
                    }
                ]
            }

        return {"error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}}

    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "gridiron-repo-intelligence", "version": "0.1.0"},
        }

    return {"error": {"code": -32601, "message": f"Unknown method: {method}"}}


def run_stdio_server() -> None:
    """Run MCP server reading JSON-RPC from stdin, writing to stdout."""
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": str(e)},
            }
            print(json.dumps(resp), flush=True)
            continue

        req_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params", {})

        try:
            result = _handle(method, params)
            if "error" in result:
                resp = {"jsonrpc": "2.0", "id": req_id, "error": result["error"]}
            else:
                resp = {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as e:
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": str(e)},
            }

        print(json.dumps(resp), flush=True)


if __name__ == "__main__":
    run_stdio_server()

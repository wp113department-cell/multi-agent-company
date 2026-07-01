/**
 * Gridiron Repo Intelligence MCP Server
 *
 * Stdio transport — newline-delimited JSON-RPC 2.0.
 * Register with Claude Code:
 *   claude mcp add gridiron-repo-intelligence -- npx tsx /path/to/packages/mcp-server/src/index.ts
 *
 * Tools exposed:
 *   index_repository   — scan repo, return file + symbol counts
 *   search_symbols     — find symbols by name query
 *   build_context      — scored relevant files + call graph for a task
 *   semantic_search    — vector similarity search (requires VOYAGE_API_KEY)
 */

import readline from "readline";
import path from "path";
import {
  indexRepository,
  searchSymbols,
  buildSymbolGraph,
  semanticSearch,
} from "@gridiron/repo-intelligence";
import { buildContext } from "@gridiron/context-builder";
import { getPool } from "@gridiron/shared-db";

// ── MCP protocol types ─────────────────────────────────────────────────────

interface JsonRpcRequest {
  jsonrpc: "2.0";
  id: string | number | null;
  method: string;
  params?: unknown;
}

interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: string | number | null;
  result?: unknown;
  error?: { code: number; message: string; data?: unknown };
}

function send(obj: JsonRpcResponse): void {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

function ok(id: string | number | null, result: unknown): void {
  send({ jsonrpc: "2.0", id, result });
}

function err(id: string | number | null, code: number, message: string, data?: unknown): void {
  send({ jsonrpc: "2.0", id, error: { code, message, data } });
}

// ── Tool definitions ───────────────────────────────────────────────────────

const TOOLS = [
  {
    name: "index_repository",
    description:
      "Scan and index a repository using AST parsing. Returns file count, symbol count, and indexing timestamp. Call this before other tools to ensure a fresh index.",
    inputSchema: {
      type: "object",
      properties: {
        repoPath: { type: "string", description: "Absolute path to the repository root" },
      },
      required: ["repoPath"],
    },
  },
  {
    name: "search_symbols",
    description:
      "Search for functions, classes, interfaces, and types in the indexed repository by name (case-insensitive substring match).",
    inputSchema: {
      type: "object",
      properties: {
        repoPath: { type: "string", description: "Absolute path to the repository root" },
        query: { type: "string", description: "Symbol name to search for" },
        limit: { type: "number", description: "Max results to return (default: 20)" },
      },
      required: ["repoPath", "query"],
    },
  },
  {
    name: "build_context",
    description:
      "Build a rich context object for an AI coding task: returns the most relevant files (keyword + semantic scoring), their dependency chain, related symbols, and call-graph edges. Use this before generating a plan or writing code.",
    inputSchema: {
      type: "object",
      properties: {
        repoPath: { type: "string", description: "Absolute path to the repository root" },
        taskTitle: { type: "string", description: "Short title of the dev task" },
        taskDescription: { type: "string", description: "Detailed description of the task" },
      },
      required: ["repoPath", "taskTitle"],
    },
  },
  {
    name: "semantic_search",
    description:
      "Vector-similarity search over the repository. Returns files ranked by semantic relevance to the query. Requires VOYAGE_API_KEY env var and a prior embedding generation run.",
    inputSchema: {
      type: "object",
      properties: {
        repoPath: { type: "string", description: "Absolute path to the repository root" },
        query: { type: "string", description: "Natural-language description of what you are looking for" },
        limit: { type: "number", description: "Max results to return (default: 10)" },
      },
      required: ["repoPath", "query"],
    },
  },
];

// ── Tool handlers ──────────────────────────────────────────────────────────

async function handleIndexRepository(args: Record<string, unknown>) {
  const repoPath = String(args["repoPath"] ?? "");
  if (!repoPath) throw new Error("repoPath is required");
  const index = await indexRepository(path.resolve(repoPath));
  return {
    repoPath: index.repoPath,
    indexedAt: index.indexedAt.toISOString(),
    totalFiles: index.files.length,
    totalSymbols: index.symbols.length,
    languages: [...new Set(index.files.map((f) => f.language))].sort(),
  };
}

async function handleSearchSymbols(args: Record<string, unknown>) {
  const repoPath = String(args["repoPath"] ?? "");
  const query = String(args["query"] ?? "");
  const limit = Number(args["limit"] ?? 20);
  if (!repoPath || !query) throw new Error("repoPath and query are required");
  const index = await indexRepository(path.resolve(repoPath));
  const symGraph = buildSymbolGraph(index);
  const results = searchSymbols(symGraph, query).slice(0, limit);
  return { query, totalMatches: results.length, symbols: results };
}

async function handleBuildContext(args: Record<string, unknown>) {
  const repoPath = String(args["repoPath"] ?? "");
  const taskTitle = String(args["taskTitle"] ?? "");
  const taskDescription = String(args["taskDescription"] ?? "");
  if (!repoPath || !taskTitle) throw new Error("repoPath and taskTitle are required");

  const fakeTask = {
    taskId: "mcp-context",
    title: taskTitle,
    description: taskDescription || null,
    priority: "medium" as const,
    status: "pending" as const,
    assignedAgent: null,
    project: null,
    filesTouched: [],
    plan: null,
    diff: null,
    finalSummary: null,
    createdAt: new Date(),
    updatedAt: new Date(),
    logs: [],
  };

  const ctx = await buildContext(fakeTask, repoPath);
  return {
    summary: ctx.summary,
    relevantFiles: ctx.relevantFiles.slice(0, 10).map((f) => ({
      filePath: f.filePath,
      score: f.score,
      matchedKeywords: f.matchedKeywords,
      importCentrality: f.importCentrality,
    })),
    dependencyChain: ctx.dependencyChain,
    relatedSymbols: ctx.relatedSymbols,
    callGraphEdges: ctx.callGraphEdges,
    semanticMatches: ctx.semanticMatches,
    indexStats: {
      ...ctx.indexStats,
      indexedAt: ctx.indexStats.indexedAt.toISOString(),
    },
  };
}

async function handleSemanticSearch(args: Record<string, unknown>) {
  const repoPath = String(args["repoPath"] ?? "");
  const query = String(args["query"] ?? "");
  const limit = Number(args["limit"] ?? 10);
  if (!repoPath || !query) throw new Error("repoPath and query are required");
  const db = getPool();
  const results = await semanticSearch(query, path.resolve(repoPath), db, limit);
  return {
    query,
    voyageKeyPresent: !!process.env["VOYAGE_API_KEY"],
    totalMatches: results.length,
    results: results.map((r) => ({ filePath: r.filePath, similarity: r.similarity })),
  };
}

// ── Request dispatcher ─────────────────────────────────────────────────────

async function handleRequest(req: JsonRpcRequest): Promise<void> {
  const { id, method, params } = req;
  const args = (params as Record<string, unknown>) ?? {};

  try {
    switch (method) {
      case "initialize":
        ok(id, {
          protocolVersion: "2024-11-05",
          capabilities: { tools: {} },
          serverInfo: { name: "gridiron-repo-intelligence", version: "1.0.0" },
        });
        break;

      case "notifications/initialized":
        // No response needed for notifications
        break;

      case "tools/list":
        ok(id, { tools: TOOLS });
        break;

      case "tools/call": {
        const toolName = String((args["name"] as string) ?? "");
        const toolArgs = (args["arguments"] as Record<string, unknown>) ?? {};
        let result: unknown;
        switch (toolName) {
          case "index_repository":
            result = await handleIndexRepository(toolArgs);
            break;
          case "search_symbols":
            result = await handleSearchSymbols(toolArgs);
            break;
          case "build_context":
            result = await handleBuildContext(toolArgs);
            break;
          case "semantic_search":
            result = await handleSemanticSearch(toolArgs);
            break;
          default:
            err(id, -32601, `Unknown tool: ${toolName}`);
            return;
        }
        ok(id, { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] });
        break;
      }

      case "ping":
        ok(id, {});
        break;

      default:
        err(id, -32601, `Method not found: ${method}`);
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    err(id, -32603, `Internal error: ${msg}`);
  }
}

// ── Stdin loop ─────────────────────────────────────────────────────────────

const rl = readline.createInterface({ input: process.stdin, terminal: false });

rl.on("line", (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  let req: JsonRpcRequest;
  try {
    req = JSON.parse(trimmed) as JsonRpcRequest;
  } catch {
    send({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } });
    return;
  }
  void handleRequest(req);
});

rl.on("close", () => process.exit(0));

process.stderr.write("[gridiron-mcp] Gridiron Repo Intelligence MCP server ready (stdio)\n");

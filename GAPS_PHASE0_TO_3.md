# Gaps Plan — Phase 0 through Phase 3
**Created: 2026-07-01. Do NOT start until tokens are refreshed.**
**Status: WAITING TO BUILD — plan is complete, implementation not started.**

This document lists every functional gap identified by comparing `files/phase.md` against what actually exists (per `PROJECT.md`). Items are grouped by priority and sequenced for build order.

---

## PRIORITY 1 — Core Phase 3 Gaps (build these first)

### 1. Call Graph — `packages/repo-intelligence/src/call-graph.ts`
**What the spec says:** "Build Call Graph (which functions call which, across files)"
**What we have:** Symbol definitions only — we know WHERE functions are defined but not WHERE they are called from.
**What to build:**
- New file: `packages/repo-intelligence/src/call-graph.ts`
- Function: `buildCallGraph(index: RepoIndex, project: Project): CallGraph`
- Approach: For each TS source file, collect all named imports (identifier → source file). Then for each function body, find call expressions and match callee name against the imports map. If it hits → cross-file call edge.
- Types to add to `types.ts`:
  ```ts
  CallEdge { callerFile, callerFn, calleeFile, calleeFn }
  CallGraph { edges: CallEdge[]; callerMap: Map<string, string[]>; calleeMap: Map<string, string[]> }
  ```
- Export from `packages/repo-intelligence/src/index.ts`
- Export: `buildCallGraph`, `getCallees`, `getCallers`, `CallGraph`, `CallEdge`
- No new dependencies needed — ts-morph already installed, use `SyntaxKind.CallExpression`
- Add `callGraph` field to `ContextResult` in `packages/context-builder/src/context-builder.ts` (callers/callees of top relevant files)

### 2. Embedding Pipeline — `packages/repo-intelligence/src/embeddings.ts`
**What the spec says:** "Build embedding pipeline: code summaries + documentation → embedded and stored. Semantic search: returns relevant files, not just keyword matches."
**What we have:** `code_embeddings` table exists with `vector(1536)` column. Zero data in it. No generation code.
**What to build:**
- New file: `packages/repo-intelligence/src/embeddings.ts`
- Embedding provider: **Voyage AI** (`voyage-code-2` model, 1536 dims — matches our schema). API: `POST https://api.voyageai.com/v1/embeddings`. Env var: `VOYAGE_API_KEY`. Fails gracefully (logs warning, skips) when key is absent.
- Function: `generateEmbeddings(index: RepoIndex, db: Pool): Promise<void>`
  - For each file: content = `"${filePath}\n${summary}\n${symbols.map(s=>s.name).join(", ")}"`. Max 2000 chars.
  - Compute SHA-256 hash of content. Skip if `code_embeddings` already has row with same `file_path` + `content_hash`.
  - Batch calls to Voyage (20 files per request). Upsert into `code_embeddings`.
- Function: `semanticSearch(query: string, db: Pool, limit?: number): Promise<SemanticSearchResult[]>`
  - Embed the query string via Voyage API.
  - SQL: `SELECT file_path, content, 1 - (embedding <=> $1::vector) AS similarity FROM code_embeddings ORDER BY embedding <=> $1::vector LIMIT $2`
  - Returns `[{ filePath, similarity, content }]`
- Add `SemanticSearchResult` type to `types.ts`
- Export from `index.ts`: `generateEmbeddings`, `semanticSearch`
- Add `VOYAGE_API_KEY=` to `.env.example`
- Update `packages/context-builder/src/context-builder.ts`:
  - If `VOYAGE_API_KEY` is set AND embeddings exist → call `semanticSearch(task description)` to augment `relevantFiles`
  - Merge semantic results with keyword-scored results (deduplicate by filePath, take union of top 15)

### 3. MCP Server — `packages/mcp-server/`
**What the spec says:** "Expose the graph as its own MCP server other agents can query"
**What we have:** Graph exposed only as a TypeScript package import — unusable by external agents.
**What to build:**
- New package: `packages/mcp-server/`
  - `package.json`: name `@gridiron/mcp-server`, type: module, deps: `@gridiron/repo-intelligence`, `@gridiron/context-builder`, `zod`
  - `tsconfig.json`: extends root tsconfig.base.json
  - `src/index.ts`: **stdio MCP server** (reads JSON-RPC from stdin, writes to stdout — standard MCP transport)
- MCP tools to expose (4 tools):
  1. `index_repository` — `{ repoPath: string }` → calls `indexRepository()`, returns file count + symbol count
  2. `search_symbols` — `{ repoPath, query }` → calls `searchSymbols()`, returns matching symbols
  3. `build_context` — `{ taskTitle, taskDescription, repoPath }` → calls `buildContext()`, returns relevantFiles + summary
  4. `semantic_search` — `{ query, repoPath }` → calls `semanticSearch()`, returns ranked files
- MCP protocol implementation:
  - Handle `initialize` request → respond with `{ protocolVersion: "2024-11-05", capabilities: { tools: {} }, serverInfo: { name: "gridiron-repo-intelligence", version: "1.0.0" } }`
  - Handle `tools/list` → return all 4 tool definitions with JSON schemas
  - Handle `tools/call` → dispatch to the right function, return result
  - Handle newline-delimited JSON (one JSON object per line)
- Add to `turbo.json` pipeline: `typecheck`, `lint`
- Add to `pnpm-workspace.yaml` if not already covered by `packages/*`
- Registration instructions (add to `PROJECT.md`): `claude mcp add gridiron-repo-intelligence -- node packages/mcp-server/dist/index.js` (or `tsx packages/mcp-server/src/index.ts` for dev)

---

## PRIORITY 2 — Operational Gaps

### 4. Incremental Re-indexing API — `apps/web/app/api/repo/reindex/route.ts`
**What the spec says:** "Incremental re-indexing on every merge to main"
**What to build:**
- New API route: `POST /api/repo/reindex`
  - Fire-and-forget: call `invalidateContextCache(repoPath)` + `indexRepository(repoPath)` + `generateEmbeddings(index, db)` in background
  - Returns 202 `{ message: "Reindex started" }`
- New API route: `GET /api/repo/reindex`
  - Returns last index time from a lightweight query (we can store it in a simple `system_settings` table, or just return the newest `indexed_at` from `code_embeddings`)
- True incremental (only changed files): use `git diff --name-only HEAD~1 HEAD` to get changed files → only re-embed those files. Full graph re-index still happens (fast, in-memory).
- Add "Reindex Repository" button to the dashboard nav (small, secondary button)

### 5. Weekly Re-index Schedule — `apps/worker/src/index.ts`
**What the spec says:** "Full re-index on weekly schedule"
**What to build:**
- In `apps/worker/src/index.ts`, add a weekly reindex check:
  - Store last reindex timestamp in a file (`/tmp/gridiron-last-reindex`) or as an env-settable interval
  - Check every poll cycle: if `Date.now() - lastReindexAt > 7 * 24 * 60 * 60 * 1000` → trigger `indexRepository + generateEmbeddings`
  - Log `[worker] Weekly reindex triggered`

### 6. Pipeline Resume from Last Good Stage — `packages/planning-pipeline/src/pipeline.ts`
**What the spec says:** "Add Postgres checkpointing (crashed runs resume, not restart)"
**What we have:** DB state is persisted per stage but `runPlanningPipeline` always starts from pm_agent.
**What to build:**
- At the start of `runPlanningPipeline`, call `getPipelineState(taskId)` first.
- If existing state found with `pmBrief` populated → skip PM Agent stage.
- If existing state found with `architectPlan` populated → skip Architect Agent stage.
- If existing state found with `subtasks` populated → skip Decomposer, go straight to `awaiting_approval`.
- Effectively: resume from the last successfully completed stage, not from scratch.

---

## PRIORITY 3 — Phase 0/1 Gaps (deferred items, low risk)

### 7. GitHub Branch Protection Rules
**Status:** GitHub settings (not code). Set manually in GitHub repo settings → `main` branch → require PR before merging.
**Action:** Do this manually in the GitHub repo UI after pushing. Not a code task.

### 8. Supabase
**Status:** Deliberately deferred. Local Docker Postgres is production-quality for this phase. Migrate when client needs cloud deployment.
**Action:** None now.

### 9. MCP filesystem/git servers (Phase 1 spec)
**Status:** Our `packages/repo-tools` (readFile, listFiles, grepFiles, gitLog, gitDiff) does the same job without MCP protocol overhead. The agents call these directly.
**Action:** The Phase 3 MCP server (item #3 above) closes this gap architecturally — once the MCP server is built, agents CAN query via MCP protocol.

### 10. Inngest (Phase 1/4 spec)
**Status:** Deliberately deferred. `setImmediate` + `apps/worker` polling is sufficient for single-agent local dev. Inngest/BullMQ is Phase 4 scope.
**Action:** None now. Revisit in Phase 4 when event bus is built.

### 11. Agent Evaluation Tests (10 sample tasks)
**Status:** Blocked on `ANTHROPIC_API_KEY`. Tests are designed and documented in `PROJECT.md` (14 live tests).
**Action:** Run as soon as API key is available.

---

## Build Order (when tokens refresh)

Execute in this exact sequence — each step depends on the previous:

```
Step 1:  Call Graph types (add CallEdge, CallGraph to types.ts)
Step 2:  call-graph.ts (buildCallGraph, getCallees, getCallers)
Step 3:  Export call graph from repo-intelligence/src/index.ts
Step 4:  Add SemanticSearchResult type to types.ts
Step 5:  embeddings.ts (generateEmbeddings, semanticSearch)
Step 6:  Add VOYAGE_API_KEY to .env.example
Step 7:  Export embeddings from repo-intelligence/src/index.ts
Step 8:  Update context-builder to use semantic search + call graph
Step 9:  MCP server package scaffold (package.json, tsconfig.json)
Step 10: MCP server src/index.ts (stdio transport, 4 tools)
Step 11: Reindex API route (POST + GET /api/repo/reindex)
Step 12: Pipeline resume logic (skip already-completed stages)
Step 13: Weekly reindex in apps/worker
Step 14: Run pnpm turbo run typecheck lint test — must stay at 32+/32 pass
Step 15: Update PROJECT.md with all new items
Step 16: Commit + push
```

---

## Files to Create (new)

| File | Package |
|---|---|
| `packages/repo-intelligence/src/call-graph.ts` | repo-intelligence |
| `packages/repo-intelligence/src/embeddings.ts` | repo-intelligence |
| `packages/mcp-server/package.json` | mcp-server (new) |
| `packages/mcp-server/tsconfig.json` | mcp-server (new) |
| `packages/mcp-server/src/index.ts` | mcp-server (new) |
| `apps/web/app/api/repo/reindex/route.ts` | apps/web |

## Files to Edit (existing)

| File | Change |
|---|---|
| `packages/repo-intelligence/src/types.ts` | Add CallEdge, CallGraph, SemanticSearchResult types |
| `packages/repo-intelligence/src/index.ts` | Export call-graph + embeddings functions |
| `packages/context-builder/src/context-builder.ts` | Add semantic search + call graph to context result |
| `packages/context-builder/src/index.ts` | Re-export new types if needed |
| `packages/planning-pipeline/src/pipeline.ts` | Add resume-from-last-stage logic |
| `apps/worker/src/index.ts` | Add weekly reindex |
| `.env.example` | Add VOYAGE_API_KEY= |
| `PROJECT.md` | Update with new capabilities + MCP registration instructions |

---

## Key Decisions Already Made

- **Voyage AI for embeddings** (not OpenAI): `voyage-code-2` model, 1536 dims, matches our `vector(1536)` schema. VOYAGE_API_KEY env var. Chosen because Anthropic recommends Voyage for code search specifically.
- **Stdio MCP transport** (not HTTP/SSE): Standard MCP protocol, works with `claude mcp add` command. Simpler than running a separate HTTP server.
- **Call graph via import-matching** (not full type resolution): ts-morph with `skipFileDependencyResolution: true` is already set for performance. We track imports → match call expressions against import map. Gives accurate cross-file calls without expensive full compilation.
- **Pipeline resume**: Check existing DB state at start of `runPlanningPipeline`, skip stages where output already exists.

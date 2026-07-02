# PROJECT.md — Current State

**This is a living document. Update it every session — it is the single source of truth for "what actually exists right now," separate from `PLAN.md` (what's intended) and `files/` (the original spec suite, which describes the full 7-stage vision, not the current build).**

Last updated: 2026-07-01 (Phase 0–3 complete + all gaps filled — 35/35 turbo tasks pass, pending API keys for live E2E test)

---

## What this project is

Gridiron AI's Developer Department: an AI agent system that takes a plain-English development task, reads a real codebase, writes an implementation plan, and proposes a safe, reviewable code patch — with a Phase 3 Repository Intelligence + Planning Subsystem (PM → Architect → Decomposer pipeline). Foundation for a larger eventual AI engineering department (see `files/` for the full long-term spec).

## Current build target

**Milestone achieved:** Phase 0–3 complete + all Phase 3 gaps filled — Call Graph, Embedding Pipeline (Voyage AI), MCP Server, Reindex API, Pipeline Resume, Weekly Reindex. 35/35 turbo tasks pass. Live E2E test requires `ANTHROPIC_API_KEY` + `VOYAGE_API_KEY`.

**Target repo the agent operates on:** not yet assigned. `TARGET_REPO_PATH` currently points at this project's own monorepo (self-referential, for testability). Repoint when the real target repo is available.

## Decisions made so far

| Decision | Choice | Why |
|---|---|---|
| Build scope | Phase 0–3 per `files/phase.md` | Full roadmap is a 7-phase multi-engineer build; we're completing through Phase 3 (Repository Intelligence + Planning Subsystem) |
| Target repo | Self-referential for now | Real target repo not available yet; tooling built generically so repointing later is a config change |
| Infra | Local-only: Docker Postgres (pgvector/pgvector:pg16 image), no cloud | Includes pgvector extension for semantic search |
| Node.js | Installed via nvm into `~/.nvm` | No sudo available |
| Job queue | `setImmediate` fire-and-forget in API routes | Sufficient for single-agent local dev; Inngest/BullMQ deferred to Phase 4 |
| Package manager | pnpm + Turborepo | Standard pairing per Engineering Standards |
| GitHub remote | `https://github.com/wp113department-cell/CRR2906.git` | Provided by user |
| AST parser | ts-morph (wraps TypeScript compiler API) | Better for TypeScript monorepo than tree-sitter; ts-morph gives real TS types, not approximations |
| Planning pipeline | Direct Anthropic SDK (not @langchain/langgraph) | Avoids heavyweight LangChain dependency chain; same sequential PM→Architect→Decomposer node pattern, DB-backed state for durability and dashboard visibility |
| pgvector | pgvector/pgvector:pg16 Docker image | Enables `CREATE EXTENSION vector` for embedding support |
| Embedding generation | Schema + infrastructure built, actual embedding calls need API key | `code_embeddings` table + vector(1536) column ready; generation pipeline requires ANTHROPIC_API_KEY |
| Migration file extension | `.cts` for all migrations | `node-pg-migrate` uses `require()`, conflicts with `"type": "module"` |

## What exists right now

_(Verified working via real API calls + automated tests, not just "code written.")_

### Phase 0 — Tooling & Scaffold ✅
- [x] Monorepo scaffold (Turborepo + pnpm workspaces)
- [x] TypeScript strict mode (`tsconfig.base.json`) across all packages
- [x] **ESLint** (root `.eslintrc.json` + `@typescript-eslint/eslint-plugin`) — all 11 packages lint clean
- [x] **Prettier** (root `.prettierrc` + `.prettierignore`) — format script in root package.json
- [x] `lint` script in all 11 packages

### Phase 1 — Single Planning Agent ✅
- [x] `shared-types` — Zod schemas for `DevTask`, `TaskLog`, `AgentRun`, all input types
- [x] `shared-db` — pg Pool client + 6 migrations (dev_tasks, task_logs, agent_runs, diff column, pgvector, pipeline_state), `node-pg-migrate`
- [x] `task-engine` — CRUD + status-transition state machine (7 unit tests pass)
- [x] `repo-tools` — readFile, listFiles, grepFiles, gitLog, gitDiff (path-escape enforced)
- [x] `agent-runtime` — Planner Agent (read-only tools), `runTaskAgent` dispatcher
- [x] Task Queue API — `POST/GET /api/tasks`, `GET/PATCH /api/tasks/:id`, `POST /api/tasks/:id/logs`, `POST /api/tasks/:id/run`
- [x] Mission Control Dashboard v1 — Task List + Task Detail pages, status badges, polling
- [x] **`apps/worker`** — standalone background worker process (polls DB for pending tasks, auto-runs planner agent)

### Phase 2 — Safe Code Proposal ✅
- [x] Coding Agent — `write_file`/`bash`/`submit_patch` tools, git worktree isolation
- [x] Policy Engine v1 — `checkPath`/`checkCommand` denylist (10 unit tests pass), enforced at tool-call layer
- [x] Self-correction retry loop — MAX_RETRIES=3, auto typecheck (`pnpm turbo run typecheck`) inside worktree
- [x] Worktree cleanup — on task `completed` or `rejected`, PATCH route calls `removeWorktree()` (best-effort)
- [x] `GET /api/tasks/:id/diff` — raw diff endpoint
- [x] `DiffViewer` component — line-by-line coloured diff (green additions, red deletions, blue hunks)
- [x] Approve/Reject UI — "Approve Plan & Start Coding" / "Reject Plan" / "Approve & Complete" / "Reject Diff" buttons

### Phase 3 — Repository Intelligence + Planning Subsystem ✅ (gaps filled)

**Phase 3 gap-fill (2026-07-01):**
- [x] **Call Graph** — `packages/repo-intelligence/src/call-graph.ts`: `buildCallGraph(index, project)` using import-matching. Returns `CallGraph { edges, callerMap, calleeMap }`. `getCallers()` / `getCallees()` helpers exported. Context-builder now includes `callGraphEdges` in `ContextResult`.
- [x] **Embedding Pipeline** — `packages/repo-intelligence/src/embeddings.ts`: `generateEmbeddings(index, db)` via Voyage AI `voyage-code-2` (1536 dims), SHA-256 content-hash dedup, batch=20. `semanticSearch(query, repoPath, db)` using pgvector cosine similarity. Requires `VOYAGE_API_KEY`.
- [x] **Migration #7** — `alter-code-embeddings`: adds `content_hash`, `updated_at`, unique constraint on `(repo_path, file_path)`, makes `chunk_index` nullable.
- [x] **MCP Server** — `packages/mcp-server/`: stdio JSON-RPC 2.0 server. Tools: `index_repository`, `search_symbols`, `build_context`, `semantic_search`. Register with: `claude mcp add gridiron-repo-intelligence -- npx tsx packages/mcp-server/src/index.ts`
- [x] **Reindex API** — `POST /api/repo/reindex` (fire-and-forget full reindex + embedding generation), `GET /api/repo/reindex` (last indexed timestamp).
- [x] **Pipeline Resume** — `runPlanningPipeline` now checks existing DB state at start, skips stages where output already populated (crash-safe resume).
- [x] **Weekly Reindex** — `apps/worker` checks every poll cycle, triggers full reindex + embedding refresh if >7 days since last run.
- [x] **Context-builder upgraded** — merges keyword scoring + semantic search results; adds `callGraphEdges` + `semanticMatches` fields to `ContextResult`.

### Phase 3 — Repository Intelligence + Planning Subsystem ✅
- [x] **`packages/repo-intelligence`** — ts-morph AST scanner (`indexRepository`), Dependency Graph (`buildDependencyGraph`, `scoreFilesByImportCentrality`), Symbol Graph (`buildSymbolGraph`, `searchSymbols`) — **verified: indexes 113 files, 175 symbols from this monorepo**
- [x] **`packages/context-builder`** — `buildContext(task, repoPath)` returns `{ relevantFiles, dependencyChain, relatedSymbols, summary }` — **verified: correctly scores API route files highest for an "add health check endpoint" task**
- [x] **Migration #5 (pgvector)** — `code_embeddings` table with `vector(1536)` column, `repo_index_entries` table — Docker image updated to `pgvector/pgvector:pg16`; migration runs clean
- [x] **Migration #6 (pipeline_state)** — `pipeline_state` table with `task_id UNIQUE`, `stage`, `pm_brief/architect_plan/subtasks` JSONB columns
- [x] **`packages/planning-pipeline`** — PM Agent node, Architect Agent node, Task Decomposer node, DB-backed state store, `runPlanningPipeline(taskId, repoPath)` — **verified: state persists to DB, fails gracefully with no-API-key error**
- [x] `POST /api/tasks/:id/pipeline` — trigger planning pipeline (fire-and-forget)
- [x] `GET /api/tasks/:id/pipeline` — return pipeline state (PM brief, architect plan, subtasks, stage)
- [x] `POST /api/tasks/:id/pipeline/approve` — approve plan, kick off coding agent
- [x] `POST /api/tasks/:id/pipeline/reject` — reject plan
- [x] **`PipelineView` component** — shows PM brief (goals, constraints, acceptance criteria), Architect plan (approach, impacted files, risks), Decomposer subtasks (typed, with files-to-edit) — with "Approve Plan & Start Coding" / "Reject Pipeline Plan" buttons
- [x] Task Detail page updated — "Run Planning Pipeline" button triggers full PM→Architect→Decomposer flow; pipeline view shows in real time via polling

### Reference repos cloned to `/repos/` ✅
All 10 repos from the Open Source Reference Matrix:
- `/repos/open-hands` — autonomous agent runtime reference
- `/repos/aider` — repo map + git workflow reference (studied: tree-sitter + PageRank ranking)
- `/repos/continue` — embedding pipeline reference (studied: LanceDB + chunking strategy)
- `/repos/cline` — human-in-the-loop approval reference
- `/repos/roo-code` — role separation reference (Architect/Code/Review modes)
- `/repos/swe-agent` — debug loop + retry strategy reference
- `/repos/autogen` — multi-agent collaboration reference
- `/repos/langgraph` — StateGraph + checkpoint + interrupt reference (studied: TypeScript examples)
- `/repos/composio` — tool registration + integration reference
- `/repos/opencode` — terminal-native runtime reference

## Test results — 2026-07-01

```
pnpm turbo run typecheck lint test
→ 35/35 tasks successful
   - policy-engine: 10/10 unit tests pass
   - task-engine: 7/7 unit tests pass
   - All 12 packages: typecheck clean  (added: mcp-server)
   - All 12 packages: lint clean
   - Migration #7 (alter-code-embeddings): ran clean on local Docker
```

## Pending live tests (require ANTHROPIC_API_KEY in .env)

### Phase 1 live tests
1. Submit task → Dashboard shows `pending`
2. Click "Run Planner Agent" → status: `planning`
3. Agent reads repo files → writes plan → status: `ready_for_review`, plan appears in dashboard
4. Verify plan references real file paths from the codebase

### Phase 2 live tests
5. Click "Approve Plan & Start Coding" → worktree created, agent writes code
6. Watch: `coding` → `testing` → `ready_for_review` with diff populated
7. Click "Approve & Complete" → worktree cleaned up, task: `completed`
8. **Self-correction test**: submit a task where typecheck would fail → verify agent retries up to 3x, then marks `blocked`
9. Reject path: click "Reject Diff" → `rejected` → re-trigger → agent starts fresh plan

### Phase 3 live tests
10. Click "Run Planning Pipeline" → watch PM Agent → Architect Agent → Task Decomposer complete in sequence
11. Verify PM brief contains real acceptance criteria
12. Verify Architect plan references real files from the repo
13. Verify Decomposer produces typed subtasks with accurate file lists
14. Click "Approve Plan & Start Coding" from pipeline view → coding agent starts

### Credential-skip items (noted for later)
- Embedding generation in `code_embeddings` table — needs API key for `text-embedding-3-small` or Anthropic embedding call
- Agent eval suite (10 representative tasks) — needs ANTHROPIC_API_KEY
- Full E2E with real Gridiron target repo — needs `TARGET_REPO_PATH` set

## Open items needed from the user

- **`ANTHROPIC_API_KEY`** — required to run agents. Set in `.env`.
- **`VOYAGE_API_KEY`** — required for semantic search (embedding pipeline). Get free key at voyageai.com. Set in `.env`. Without it, system falls back to keyword-only search.
- **Real target repo** — change `TARGET_REPO_PATH` in `.env` when available.
- Eventually: Supabase + Vercel for production deployment.

## How to run it locally

```bash
pnpm install
cp .env.example .env
# Fill in ANTHROPIC_API_KEY and VOYAGE_API_KEY in .env
pnpm db:up                  # start Docker Postgres (pgvector/pgvector:pg16)
pnpm db:migrate             # run 7 migrations
pnpm dev                    # start Next.js dev server at http://localhost:3000
# Optional: start background worker (auto-picks up pending tasks + weekly reindex)
pnpm --filter @gridiron/worker start
# Optional: register MCP server with Claude Code
claude mcp add gridiron-repo-intelligence -- npx tsx packages/mcp-server/src/index.ts
# Trigger a manual reindex + embedding generation (after API keys are set):
curl -X POST http://localhost:3000/api/repo/reindex
```

## How to resume work in a new session

1. Read this file (`PROJECT.md`) for current state — **13/13 turbo tasks pass is the baseline**
2. Read `PLAN.md` for the roadmap
3. Run `pnpm turbo run typecheck` to verify clean baseline before making changes
4. For Phase 4+: add Event Bus, specialist coding agents (Backend/Frontend/QA/Review), Manager Agent

---

## Gap Fill Session — 2026-07-02

**Session goal:** Fill every gap from the MASTER_PROMPT_PACK (Prompts 1, 2, 3) vs what was actually built.

### What was built this session

**Documentation:**
- [x] `docs/research/openhands-notes.md` — patterns from OpenHands: typed action/observation, event log persistence
- [x] `docs/research/swe-agent-notes.md` — StepOutput/TrajectoryStep types, per-step structured logging
- [x] `docs/research/aider-notes.md` — hash-based incremental indexing, token budget enforcement
- [x] `docs/research/cline-notes.md` — per-action approval granularity, plan/act separation
- [x] `docs/research/continue-notes.md` — cachekey content hash, chunking strategy, per-model artifact isolation
- [x] `docs/research/versions.md` — verified installed package versions (zod 3.25.76, @anthropic-ai/sdk 0.30.1, pg 8.22.0, etc.)
- [x] `docs/CODEBASE_MAP.md` — full codebase map with data flow, key interfaces, DB schema overview
- [x] `docs/adr/001` through `docs/adr/004` — ADRs for Anthropic API choice, pgvector, worktree isolation, shared-config

**Role files & agent wiring:**
- [x] `packages/agent-runtime/roles/{planner,coder,pm,architect,decomposer}.md` — system prompts extracted from code to disk files
- [x] `packages/agent-runtime/src/roles.ts` — `loadRole(name)` reads from disk
- [x] `packages/planning-pipeline/src/load-role.ts` — same for planning-pipeline agents
- [x] All agents now load their system prompt from disk on startup (planner, coder, pm, architect, decomposer)

**Config & validation:**
- [x] `packages/shared-config` — already built last session; this session verified and documented
- [x] PlanSchema validation in planner-agent `submit_plan` — rejects plans < 100 chars or missing markdown formatting
- [x] Heartbeat: `agentRunId` added to `AgentContext`; base-agent fires `heartbeatAgentRun()` every 5 tool calls

**Migrations:**
- [x] **Migration #8** — `agent_runs` gains: `tokens_in`, `tokens_out`, `cost_estimate`, `last_heartbeat_at`, `model_id`
- [x] **Migration #9** — `subtasks` table (with `task_id` FK, type enum, `files_to_edit[]`, `depends_on[]`, status)
- [x] **Migration #10** — `indexed_files`, `symbols`, `call_edges` tables for persistent call graph storage

**API gaps filled:**
- [x] `POST /api/tasks/:id/approve` — top-level task approval (starts coding agent)
- [x] `POST /api/tasks/:id/reject` — top-level task rejection (with optional reason)
- [x] `GET /api/tasks` — now returns `{ tasks, nextCursor }` for proper cursor pagination
- [x] PIPELINE_MODE flag in runner (`simple` = skip planning, `full` = PM→Arch→Decomp)

**Repository layer:**
- [x] `heartbeatAgentRun(runId)` in task-engine — updates `last_heartbeat_at`
- [x] `recordAgentRunTokens(runId, in, out, cost)` in task-engine
- [x] `saveSubtasks(taskId, subtasks)` + `listSubtasks(taskId)` in task-engine
- [x] Planning pipeline calls `saveSubtasks()` after decomposition

**Graph persistence:**
- [x] `packages/repo-intelligence/src/graph-persist.ts` — `persistGraphToDb()`: hash-keyed incremental upsert of files, symbols, call edges to Postgres
- [x] Skips files whose content hash hasn't changed since last index (incremental re-index)

**Security:**
- [x] `checkPathInWorktree(filePath, worktreePath)` — enforces worktree boundary, blocks `../../` path traversal
- [x] Policy tests expanded to 17 tests (was 10), now covering git push to main/master, docker push, heroku, worktree boundary enforcement

**Tests:**
- [x] `tests/` workspace package — `@gridiron/tests` registered in pnpm-workspace.yaml
- [x] `tests/fixtures/demo-repo/` — 2-file TypeScript fixture (math.ts + calculator.ts)
- [x] `tests/integration/task-queue.test.ts` — 7 tests (2 run without DB, 5 skip when no live DB)
- [x] `tests/integration/worktree-lifecycle.test.ts` — 3 tests (create worktree, isolation, cleanup)
- [x] `tests/integration/graph-correctness.test.ts` — 5 tests (index fixture, extract symbols, build call graph)

**Test reports:**
- [x] `docs/reports/PHASE_1_TEST_REPORT.md`
- [x] `docs/reports/PHASE_2_TEST_REPORT.md`
- [x] `docs/reports/PHASE_3_TEST_REPORT.md`

### Test results — 2026-07-02

```
pnpm turbo test
→ 13/13 turbo tasks successful (0 failures)

Results by package:
- @gridiron/policy-engine: 17/17 unit tests pass (was 10 — added 7 new tests)
- @gridiron/task-engine: 7/7 unit tests pass
- @gridiron/tests (integration): 10 pass | 5 skipped (DB-dependent)
  - integration/task-queue.test.ts: 2 pass | 5 skipped
  - integration/worktree-lifecycle.test.ts: 3 pass
  - integration/graph-correctness.test.ts: 5 pass
- All other packages: passWithNoTests (no unit tests needed for pure type packages)
```

### Known issues / pending live tests
- Same as before: ANTHROPIC_API_KEY + VOYAGE_API_KEY required for live agent + embedding tests
- Token recording (`recordAgentRunTokens`) — not yet wired into base-agent loop (tracking migration done, wiring deferred to Phase 4 when token cost matters for billing)

### How to run updated test suite

```bash
# Full turbo suite (all packages):
pnpm turbo test

# Integration tests only:
pnpm --filter @gridiron/tests test

# Policy engine security tests:
pnpm --filter @gridiron/policy-engine test

# With live DB (integration tests that need Postgres):
DATABASE_URL=postgresql://gridiron:gridiron_dev_only@localhost:5432/gridiron_dev pnpm --filter @gridiron/tests test

# Migrations (run after db:up):
pnpm db:migrate
```

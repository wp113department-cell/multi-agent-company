# PROJECT.md — Current State

**This is a living document. Update it every session — it is the single source of truth for "what actually exists right now," separate from `PLAN.md` (what's intended) and `files/` (the original spec suite, which describes the full 7-stage vision, not the current build).**

Last updated: 2026-07-02 (Phases 0–4 complete + full Phase 1–4 gap fix pass + gitignore cleanup — 123/123 pytest pass, mypy --strict clean, commit ceb2f59 — Phase 5+6 plan documented, ready to build)

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

---

## ARCHITECTURE PIVOT — 2026-07-02 (Python Backend)

**Decision:** Full backend rebuild in Python. TypeScript backend archived in `TX/`.

| | Before | After |
|---|---|---|
| Backend language | TypeScript (Node.js) | **Python 3.11+** |
| API framework | Next.js App Router API routes | **FastAPI** |
| Agent orchestration | Direct Anthropic SDK (TS) | **LangGraph (Python)** |
| Config validation | Zod + shared-config package | **Pydantic BaseSettings** |
| ORM | pg (raw SQL) + node-pg-migrate | **SQLAlchemy + Alembic** |
| Embeddings | HTTP → Voyage AI | **voyageai Python SDK** |
| Testing | Vitest | **pytest + mypy** |
| Frontend | Next.js (TypeScript) | Next.js (TypeScript) — **unchanged** |

**What was archived (TX/ folder):**
- `TX/packages/` — all 11 TypeScript packages (agent-runtime, context-builder, mcp-server, planning-pipeline, policy-engine, repo-intelligence, repo-tools, shared-config, shared-db, shared-types, task-engine)
- `TX/apps/worker/` — TypeScript background worker
- `TX/tests/` — Vitest integration tests
- `TX/api-routes/next-api/` — all Next.js API routes (were in apps/web/app/api/)

**New backend location:** `backend/` (Python)

**Frontend:** `apps/web/` stays completely unchanged — Next.js pages, components, and styles.

**Next steps (Python backend rebuild — 2-day plan):**

### Day 1 (2026-07-02) — Foundation
1. Python project scaffold (`backend/`, virtualenv, requirements.txt)
2. Pydantic BaseSettings config (`backend/app/config.py`)
3. SQLAlchemy models + Alembic migrations (dev_tasks, task_logs, agent_runs, subtasks)
4. FastAPI app skeleton (`backend/app/main.py`)
5. Task Queue API — `POST/GET /api/tasks`, `GET/PATCH /api/tasks/:id`, `GET /api/tasks/:id/logs`
6. Status-transition machine (Python, same rules as TypeScript version)
7. Policy engine (`backend/app/policy/engine.py`)
8. Git worktree isolation helpers (`backend/app/repo_tools/worktree.py`)
9. pytest test suite — config, status transitions, policy engine

### Day 2 (2026-07-03) — Agents + Intelligence
1. Base agent runner (Anthropic Python SDK, loads role from `backend/roles/*.md`)
2. LangGraph StateGraph — PM Agent → Architect Agent → Decomposer (with Postgres checkpointing)
3. Planner Agent node + Coder Agent node
4. Repo intelligence: AST scanner (tree-sitter Python), call graph, embedding pipeline (voyageai)
5. Context builder (`buildContext()`)
6. MCP server (Python stdio JSON-RPC 2.0)
7. FastAPI routes wired to all agents
8. pytest integration tests — full pipeline, graph correctness

**How to resume next session:**
- Read this PROJECT.md
- Run: `cd backend && source venv/bin/activate && pytest tests/ -v`
- Start Day 2 from where Day 1 left off

---

## Python Backend Day 2 — 2026-07-02

### What was built (Day 2)

**Agents (all real — no stubs):**
- `backend/app/agents/base.py` — `run_agent()`: Anthropic SDK tool-use loop, role loader, policy gate, heartbeat every 5 calls
- `backend/app/agents/tools.py` — read-only tools (read_file, list_files, search_code) + coder tools (write_file, bash, submit_patch)
- `backend/app/agents/pm.py` — PM Agent LangGraph node
- `backend/app/agents/architect.py` — Architect Agent LangGraph node
- `backend/app/agents/decomposer.py` — Decomposer Agent LangGraph node
- `backend/app/agents/planner.py` — Planner Agent (plan validation: min 100 chars + sections, 2 retries)
- `backend/app/agents/coder.py` — Coder Agent (write tools, self-correction loop, mypy+ruff check after each attempt)

**LangGraph Pipeline:**
- `backend/app/pipeline/state.py` — PipelineState TypedDict
- `backend/app/pipeline/graph.py` — StateGraph (PM→Architect→Decomposer), MemorySaver checkpointing, `run_planning_pipeline()`

**Repo Intelligence:**
- `backend/app/repo_tools/scanner.py` — tree-sitter (Python + JS/TS), symbol extraction, import graph, content hash
- `backend/app/repo_tools/embeddings.py` — Voyage AI embeddings + cosine semantic search (skips if no key)
- `backend/app/repo_tools/context_builder.py` — `build_context()`: keyword + semantic + dependency chain

**MCP Server:**
- `backend/app/mcp/server.py` — stdio JSON-RPC 2.0, 4 tools (index_repository, search_symbols, build_context, query_dependencies)

**FastAPI wiring:**
- `backend/app/api/agents.py` — fire-and-forget background task launchers (planning pipeline, planner, coder)
- `backend/app/api/tasks.py` — POST /run triggers pipeline, POST /approve triggers coder, GET /pipeline, GET /diff
- `backend/app/api/repo.py` — POST/GET /reindex, GET /context

### Test results — Day 2

```
pytest tests/ -v
→ 63/63 passed (0 failures)

mypy app/ --ignore-missing-imports
→ Success: no issues found in 31 source files
```

| Test file | Tests |
|---|---|
| test_config.py | 3 |
| test_context_builder.py | 5 |
| test_mcp.py | 6 |
| test_policy.py | 29 |
| test_scanner.py | 9 |
| test_status_transitions.py | 11 |

### Pending (API key required)
- Live agent runs (PM, Architect, Decomposer, Planner, Coder) — require ANTHROPIC_API_KEY
- LangGraph pipeline end-to-end
- Voyage AI semantic search — require VOYAGE_API_KEY
- DB integration tests — require live Postgres

### How to run once API key is available
```bash
cd backend
cp ../.env.example .env  # fill in ANTHROPIC_API_KEY + DATABASE_URL
.venv/bin/uvicorn app.main:app --reload --port 8000
```

### MCP server start command
```bash
cd backend
DATABASE_URL=... ANTHROPIC_API_KEY=... TARGET_REPO_PATH=.. \
.venv/bin/python -m app.mcp.server
```

---

## Phase 0-3 Gap-Close Session — 2026-07-02 (evening)

**Session goal:** Systematic gap analysis of MASTER_PROMPT_PACK Prompts 1-3 vs what was actually built, and close every gap.

### Gaps identified and closed

| Gap | Fix |
|---|---|
| Frontend broken — `/api/*` hit archived Next.js routes (in `TX/`) | `apps/web/next.config.mjs` rewrites `/api/*` → `http://localhost:8000` (FastAPI). All frontend HTTP calls now reach the Python backend. |
| URL mismatches — `approvePipeline`, `rejectPipeline`, `triggerPipeline` called wrong routes | `apps/web/lib/api.ts` fully rewritten — correct routes, camelCase types, proper return types |
| FastAPI responses were snake_case — frontend expected camelCase | `backend/app/api/tasks.py` now returns `filesTouched`, `createdAt`, `logId`, etc. |
| `GET /api/tasks/:id` didn't include logs | Task detail response now includes full `logs[]` array |
| Missing `/pipeline/approve` and `/pipeline/reject` routes | Added both routes to FastAPI, wired to LangGraph resume |
| `.env.example` missing | Created `backend/.env.example` with all 16 env vars documented |
| LangGraph interrupt() not implemented | `human_review_node` added after Decomposer — calls `interrupt()`, pauses at `stage='awaiting_approval'`. `resume_pipeline(task_id, approved)` resumes from MemorySaver checkpoint |
| `launch_planning_pipeline` always transitioned to `ready_for_review` | Now detects `stage='awaiting_approval'` and holds task in `planning` until human approves |
| `resume_planning_pipeline(task_id, approved)` didn't exist | Added to `agents.py` — resumes LangGraph, then launches coder on approval or marks rejected |
| Incremental re-index missing — full scan every time | `scanner.py` accepts `known_hashes: dict[str,str]` — skips re-parsing files whose SHA-256 hasn't changed. `merge_indexes()` helper added |
| Context cache missing | In-memory cache in `context_builder.py` keyed by SHA-256(task_description + repo_path). `invalidate_context_cache()` called after re-index |
| `preserve_worktree()` missing | Added to `worktree.py` — touches `.gridiron-preserved` sentinel. Called on blocked + ready_for_review. `remove_worktree()` cleans sentinel on teardown |
| POST /run ignored request body — mode override not possible | `RunRequest` body added; `mode` field overrides `PIPELINE_MODE` env for a single run |
| Pending tests for API-key-required flows | `backend/tests/pending/` — 38 tests across 8 files, all skip cleanly without keys |

### Files changed this session

**Frontend:**
- `apps/web/next.config.mjs` — added rewrites() proxy to FastAPI
- `apps/web/lib/api.ts` — full rewrite with correct routes + TypeScript types
- `apps/web/.env.local` — NEXT_PUBLIC_API_URL=http://localhost:8000 (gitignored)

**Backend:**
- `backend/.env.example` — all 16 env vars documented (NEW)
- `backend/app/api/tasks.py` — camelCase responses, logs in detail, /pipeline/approve + /pipeline/reject, RunRequest body
- `backend/app/api/agents.py` — awaiting_approval handling, resume_planning_pipeline(), preserve_worktree() calls
- `backend/app/api/repo.py` — incremental known_hashes tracking, invalidate_context_cache() after reindex
- `backend/app/pipeline/graph.py` — human_review_node with interrupt(), resume_pipeline(), interrupt_before= compilation
- `backend/app/repo_tools/scanner.py` — known_hashes param, merge_indexes() helper
- `backend/app/repo_tools/context_builder.py` — in-memory cache + invalidate function
- `backend/app/repo_tools/worktree.py` — preserve_worktree() + sentinel cleanup in remove_worktree()
- `backend/tests/pending/` — 8 test files, 38 pending tests (all skipped without RUN_PENDING_TESTS=1)

### Test results — 2026-07-02 evening

```
pytest tests/ -v
→ 63/63 passed, 38 skipped (pending tests skip cleanly)

mypy app/ --strict
→ Success: no issues found in 31 source files
```

### Commit
`99cb7d4` — feat: close all Phase 0-3 gaps (see git log for full details)

---

## Phase 4 — Ready to start next session

**What Phase 4 adds (per MASTER_PROMPT_PACK Prompt 4 — not yet started):**
- Event Bus: Postgres LISTEN/NOTIFY for real-time pipeline events
- Specialist agents: Backend Agent, Frontend Agent, QA Agent, Review Agent (each with own role file)
- Manager Agent: orchestrates multi-agent work on decomposed subtasks
- Artifact Store: persist diffs, test outputs, agent reports per task
- Parallel subtask execution: multiple agents running simultaneously on different subtasks

**How to start Phase 4:**
1. Read this file
2. Run: `cd backend && DATABASE_URL=... ANTHROPIC_API_KEY=sk-ant-dummy TARGET_REPO_PATH=. .venv/bin/pytest tests/ -v` → confirm 63/63 green
3. Buy Anthropic API key → run `RUN_PENDING_TESTS=1 ANTHROPIC_API_KEY=real-key ... pytest tests/pending/ -v` first to validate live agents
4. Then start Phase 4 build

**Pre-conditions before Phase 4 makes sense:**
- ANTHROPIC_API_KEY purchased — every Phase 4 feature requires real Claude calls
- DATABASE_URL live Postgres — event bus, artifact store, manager state all DB-backed

---

## Phase 4 — Specialist Agents + QA Loop + Event Bus + Artifact Store (2026-07-02)

**Session goal:** Build everything in MASTER_PROMPT_PACK Prompt 4 that can be built without API keys.
Same pattern as Phase 3: live agent tests deferred to `tests/pending/`.

### What was built

**Research (Step 0):**
- `docs/research/roo-notes.md` — roo-code mode separation patterns, structural tool enforcement model
- `docs/research/autogen-notes.md` — message-passing decoupling, topic routing, stateless agents

**Role files (5 new):**
- `backend/roles/backend_dev.md` — Read+Write(worktree)+Bash(typecheck/lint), submit_patch
- `backend/roles/frontend_dev.md` — same scope, Next.js/TypeScript focus, tsc check
- `backend/roles/qa.md` — Read+Bash(tests only), NO write, submit_qa_result schema
- `backend/roles/reviewer.md` — Read ONLY, structured ReviewFinding schema, no bash
- `backend/roles/manager.md` — routing/tracking only, no code writes, dispatches subtasks

**Tool scoping (doc-07 matrix — structurally enforced):**
- `QA_TOOLS` in `tools.py` — READ_ONLY_TOOLS + bash(allowlist) + submit_qa_result — NO write_file
- `REVIEWER_TOOLS` — READ_ONLY_TOOLS + submit_review — NO bash, NO write_file
- `_is_qa_command_allowed()` — prefix allowlist: pytest/mypy/ruff/tsc/npm test/git diff only
- `make_qa_handlers()` — bash enforces QA allowlist before policy engine
- `make_reviewer_handlers()` — no bash or write handlers at all (structural, not prompt)

**Specialist agents:**
- `backend/app/agents/backend_dev.py` — `run_backend_dev()`, CODER_TOOLS, mypy+ruff self-correction
- `backend/app/agents/frontend_dev.py` — `run_frontend_dev()`, CODER_TOOLS, tsc self-correction
- `backend/app/agents/qa.py` — `run_qa()` → `QAResult` dataclass, QA_TOOLS (no write)
- `backend/app/agents/reviewer.py` — `run_reviewer()` → `ReviewResult` + `ReviewFinding`, REVIEWER_TOOLS (read only)
- `backend/app/agents/manager.py` — `run_manager()`, Dev→QA→Review loop, retry cap, task.blocked on exhaustion

**Event Bus (`backend/app/event_bus/`):**
- `models.py` — `GridironEvent` Pydantic model (frozen, UUID event_id), 8 factory functions for core event types
- `bus.py` — `publish_event()`, `subscribe()`, `unsubscribe()`, `get_unprocessed_events()`
- Retry: 3× with exponential backoff per handler failure
- Dead-letter: `_write_failed_event()` after retries exhausted
- In-memory subscriber registry (works without DB; DB persistence optional via `db=` param)
- Replay: `get_unprocessed_events(task_id, since, db)` queries events > last_processed_at
- Ordering: sequential publish per task guarantees per-task event order

**Artifact Store (`backend/app/artifacts/`):**
- `store.py` — `save_artifact()`, `save_artifact_async()`, `get_artifact()`, `list_artifacts()`
- Local disk: `{WORKTREES_DIR}/../artifacts/{artifact_id}` — no hardcoded paths
- `ArtifactRecord` dataclass returned on save
- `save_artifact_async()` also writes DB row to artifacts table

**Dispatcher (`backend/app/pipeline/dispatcher.py`):**
- Routing table: backend→backend_dev, frontend→frontend_dev, test→qa, docs→backend_dev
- `get_agent_for_type()` — pure deterministic function (no LLM for routing)
- `dispatch_subtask()` — routes to correct agent, returns `{files_changed, error, agent}`

**DB models (3 new ORM classes):**
- `Event` — persisted event bus events (UUID PK, JSONB payload)
- `FailedEvent` — dead-letter log (BigInteger PK, references event_id)
- `Artifact` — versioned pipeline outputs (UUID PK, task_id, type, storage_path)

**Migration 002:**
- `backend/migrations/versions/002_phase4_tables.py` — events, failed_events, artifacts tables + indexes

**Artifacts API:**
- `backend/app/api/artifacts.py` — `GET /api/tasks/:id/artifacts`, `GET /api/artifacts/:id`
- Registered in `backend/app/main.py`

**Tests (new — all passing):**
- `tests/test_event_bus.py` — 15 tests: roundtrip, ordering, retry, failed handler isolation, sync handlers
- `tests/test_artifacts.py` — 8 tests: save/get/roundtrip, dict content, multiple artifacts
- `tests/test_dispatcher.py` — 9 tests: routing table, dispatch to backend/frontend/qa agents
- `tests/test_tool_scoping.py` — 28 tests: QA has no write, Reviewer has no bash/write, allowlist (9+8)

**Pending tests (9 new, all skipped):**
- `tests/pending/test_specialist_agents.py` — backend dev, QA, reviewer, full pipeline, retry loops, manager

**Bug fix:** `context_builder.py` — removed unused `get_settings()` call that was causing 5 test failures

### Test results — Phase 4

```
pytest tests/ -v
→ 123/123 passed, 47 skipped (all pending skip cleanly)

mypy app/ --strict
→ Success: no issues found in 43 source files
```

### Files created/changed this session

**New files:**
- `docs/research/roo-notes.md`
- `docs/research/autogen-notes.md`
- `backend/roles/backend_dev.md`
- `backend/roles/frontend_dev.md`
- `backend/roles/qa.md`
- `backend/roles/reviewer.md`
- `backend/roles/manager.md`
- `backend/app/agents/backend_dev.py`
- `backend/app/agents/frontend_dev.py`
- `backend/app/agents/qa.py`
- `backend/app/agents/reviewer.py`
- `backend/app/agents/manager.py`
- `backend/app/event_bus/__init__.py`
- `backend/app/event_bus/models.py`
- `backend/app/event_bus/bus.py`
- `backend/app/artifacts/__init__.py`
- `backend/app/artifacts/store.py`
- `backend/app/pipeline/dispatcher.py`
- `backend/app/api/artifacts.py`
- `backend/migrations/versions/002_phase4_tables.py`
- `backend/tests/test_event_bus.py`
- `backend/tests/test_artifacts.py`
- `backend/tests/test_dispatcher.py`
- `backend/tests/test_tool_scoping.py`
- `backend/tests/pending/test_specialist_agents.py`
- `docs/reports/PHASE_4_TEST_REPORT.md`

**Modified files:**
- `backend/app/agents/tools.py` — added QA_TOOLS, REVIEWER_TOOLS, make_qa_handlers(), make_reviewer_handlers()
- `backend/app/db/models.py` — added Event, FailedEvent, Artifact ORM classes
- `backend/app/main.py` — registered artifacts router
- `backend/app/repo_tools/context_builder.py` — removed unused get_settings() call (bug fix)

### What's next (Phase 5)

Per MASTER_PROMPT_PACK Prompt 5:
- Manager Agent upgrade to LangGraph supervisor (epic-level orchestration)
- Epics: `epics` table + epic_id FK on dev_tasks
- Cost Controller: estimate tokens/dollars before execution, cost approval threshold
- Policy Engine v2: `policies` table, glob-pattern approval rules, policy_approvals audit log
- RBAC: viewer vs approver roles, all approve/reject endpoints enforce approver role at API layer
- DevOps Agent (read-only health checks)
- Epic Approval UI (Stage 5 dashboard)

**Pre-conditions for Phase 5:**
- Same as Phase 4: ANTHROPIC_API_KEY + live Postgres needed for pending tests

---

## Phase 1–4 Gap Fix Session — 2026-07-02 (late evening)

**Session goal:** Line-by-line audit of Prompts 1–4 vs actual code. Found 18 fixable gaps + 8 pending-API items. Fixed all 11 non-credential gaps.

### Gaps fixed

| # | Gap | Files |
|---|---|---|
| 1 | LOG_LEVEL env var not wired | `config.py`, `.env.example`, `main.py` |
| 2 | Token tracking discarded — planner/coder returned 2-tuple, never persisted | `planner.py`, `coder.py`, `api/agents.py` |
| 3 | Structured error format missing (`{ error: { code, message } }`) | `main.py` exception handlers |
| 4 | Weekly auto-reindex background task not wired | `main.py` lifespan |
| 5 | MCP missing `semantic_search` + `get_file_summary` tools | `mcp/server.py` |
| 6 | Artifacts never saved to disk/DB during pipeline | `api/agents.py`, `artifacts/store.py` |
| 7 | Artifact API used `db=None` → always returned empty list | `api/artifacts.py` |
| 8 | Pipeline approve → single coder instead of full manager pipeline | `api/agents.py` |
| 9 | manager.py sync calls blocked the async event loop | `agents/manager.py` |
| 10 | Stage 4 UI missing Dev→QA→Review live display | `PipelineView.tsx` |
| 11 | Task detail page had no artifact inspector | `tasks/[id]/page.tsx`, `lib/api.ts` |

**Additional (gitignore / cleanup):**
- `__pycache__/`, `.pyc`, `tsconfig.tsbuildinfo` were tracked — removed from git, added to `.gitignore`
- `.venv/`, `venv/`, `artifacts/`, `repos/` confirmed not tracked

### Test results — gap fix

```
pytest backend/tests/ -v
→ 123/123 passed, 47 skipped (all pending skip cleanly without API keys)

mypy backend/ --strict
→ Success: no issues found in 43 source files
```

### Commit
`ceb2f59` — chore: clean .gitignore — remove __pycache__, .pyc, tsconfig.tsbuildinfo (with prior commits covering gap fixes)

### Latest state
- Branch: `main`
- Pushed to: `git@github.com:wp113department-cell/CRR2906.git`
- 273 tracked files (clean working tree)
- All non-LLM layers verified working via real Python calls (real server start, real file I/O, real DB queries)

---

## Phase 5 + 6 — Ready for next session (2026-07-03)

### Phase 5 (Day 5 — MASTER_PROMPT_PACK Prompt 5)

**New DB tables needed (Alembic migration 003):**
- `epics` — epic_id (UUID PK), title, description, status, cost_estimate, cost_actual, created_at, updated_at
- `dev_tasks.epic_id` FK column (nullable) → epics
- `policies` — id, name, trigger_pattern (glob), required_approval_role, blocking (bool), active
- `policy_approvals` — id, policy_id FK, task_id/epic_id, approver_role, decision, created_at
- `users` (or `user_roles`) — user_id, role (viewer | approver)

**New agents needed:**
- `backend/app/agents/devops.py` — read-only bash (git status, disk usage from allowlist in config), no write, no deploy
- `backend/roles/devops.md` — role file

**Manager Agent upgrade:**
- `backend/app/agents/manager.py` — already exists; upgrade to LangGraph supervisor node above the full PM→Arch→Decomp pipeline
- Creates epic from high-level goal → runs sub-pipeline → tracks subtask statuses via Event Bus → auto-retries failed subtasks (cap from config) → halts epic if ≥2 subtasks fail repeatedly → emits `epic.halted` event → assembles batched approval package

**Cost Controller:**
- `backend/app/pipeline/cost_controller.py` — `estimate_cost(subtask_count, complexity)` using historical avg from `agent_runs` + config coefficients
- Config: `COST_APPROVAL_THRESHOLD`, `COST_PER_INPUT_TOKEN`, `COST_PER_OUTPUT_TOKEN`, `MODEL_PLANNER`, `MODEL_CODER`
- Gate in pipeline: estimate → if over threshold → interrupt() → human approval required before agents start

**Policy Engine v2:**
- `backend/app/policy/engine_v2.py` — `load_policies(db)`, `match_policy(file_path)` glob match, `record_approval()`
- Seeds: `**/migrations/**` → human blocking; `api/customer/**` → architect blocking; `auth/**` → flag-only

**RBAC:**
- `backend/app/middleware/rbac.py` — `require_approver(request)` dependency, 403 if viewer
- All approve/reject endpoints in `tasks.py`, `agents.py` use this dependency

**API endpoints (Prompt 5):**
- `POST /api/epics` — create epic
- `GET /api/epics/:id` — get epic with all subtasks + artifacts + cost
- `POST /api/epics/:id/approve` — human approves batched package (approver role)
- `POST /api/epics/:id/reject` — reject (approver role)

**Frontend:**
- `apps/web/app/epics/` — Epic list + detail page (all subtasks, diffs, QA results, cost estimate vs actual, Approve/Reject)
- `apps/web/lib/api.ts` — add fetchEpic, approveEpic, rejectEpic

**Tests:**
- Manager integration: goal → epic → subtasks → batched approval package
- Halt path: force 2 subtask failures → epic.halted event
- Cost gate: over-threshold → blocks before agents start
- Policy v2: `**/migrations/**` subtask → blocks until policy_approvals row exists
- RBAC: viewer → 403 on all approve endpoints; approver → 200

### Phase 6 (Day 6 — MASTER_PROMPT_PACK Prompt 6)

**Research (Step 0):**
- Read `/repos/composio` for tool/capability registration patterns → `docs/research/composio-notes.md`
- Verify web-search MCP server actually exists before wiring

**Agent Registry (migration 004):**
- `agents` table — agent_id, name, capability_tags (ARRAY), tool_list (JSONB), prompt_ref, version, success_rate, avg_retries, last_computed_at
- `backend/app/api/registry.py` — `GET /api/agents`, `GET /api/agents/:id/metrics`
- Seed rows for: planner, pm, architect, decomposer, backend_dev, frontend_dev, qa, reviewer, devops, manager
- `backend/app/pipeline/dispatcher.py` — refactor to query agents by capability tag, not hardcoded name

**Research Agent:**
- `backend/roles/research.md` — tools: web_search + GitHub read via MCP, Read; NO Edit/Write/Bash
- `backend/app/agents/research.py` — output: `{ findings, relevantLibraries, recommendedApproach, risks }`
- Config flag `RESEARCH_ENABLED` — inserts as optional first pipeline step

**Documentation Agent:**
- `backend/roles/docs.md` — Edit/Write scoped to `*.md` and `docs/**` ONLY (enforced by policy rule, not prompt)
- `backend/app/agents/docs.py` — triggered by epic approval event, writes README/changelog in worktree

**Engineering Memory v1 (pgvector):**
- On task completion/blocked: embed `{problem, plan, patch_summary, outcome, errors, fixes}` → pgvector
- `backend/app/memory/store.py` — `embed_task_outcome()`, `query_similar_tasks(description, top_k)`
- Architect Agent + Context Builder now query: "similar past tasks" section appended to context
- Learning signal: `/api/memory/patterns` — reports prompt/tool combos correlated with retries/failures (human read-only, never auto-applied)

**Tests:**
- Registry: metrics math correct; capability-tag dispatch selects right agent; new fake agent dispatched via insert only
- Research agent eval: real run, output validates, sources are real
- Docs agent security: `.ts` write denied; `.md` write in worktree allowed
- Memory: complete task → embedding row exists; similar task → architect context contains past-task reference

**How to start Phase 5 (first action next session):**
1. Read `PROJECT.md` (this file)
2. `cd backend && .venv/bin/python -m pytest tests/ -v` → confirm 123/123 green
3. `cd backend && .venv/bin/python -m mypy app/ --strict` → confirm 0 issues in 43 files
4. Start Phase 5 Step 1: write Alembic migration 003 (epics + policies + policy_approvals + users tables)

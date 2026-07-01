# PROJECT.md — Current State

**This is a living document. Update it every session — it is the single source of truth for "what actually exists right now," separate from `PLAN.md` (what's intended) and `files/` (the original spec suite, which describes the full 7-stage vision, not the current build).**

Last updated: 2026-07-01 (Phase 0 + 1 + 2 + 3 complete — all 32 turbo tasks pass, pending API key for live E2E test)

---

## What this project is

Gridiron AI's Developer Department: an AI agent system that takes a plain-English development task, reads a real codebase, writes an implementation plan, and proposes a safe, reviewable code patch — with a Phase 3 Repository Intelligence + Planning Subsystem (PM → Architect → Decomposer pipeline). Foundation for a larger eventual AI engineering department (see `files/` for the full long-term spec).

## Current build target

**Milestone achieved:** Phase 0 (ESLint/Prettier/tooling) + Phase 1 (Task Queue API, Planner Agent, Dashboard v1, Worker process) + Phase 2 (Worktree isolation, Coding Agent, Policy Engine, Diff Review UI, self-correction retry loop) + Phase 3 (Repository Intelligence, Context Builder, pgvector schema, PM→Architect→Decomposer pipeline, Pipeline Dashboard) — all verified via typecheck + lint + unit tests. Full live E2E test requires `ANTHROPIC_API_KEY`.

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
→ 32/32 tasks successful
   - policy-engine: 10/10 unit tests pass
   - task-engine: 7/7 unit tests pass
   - All 11 packages: typecheck clean
   - All 11 packages: lint clean
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
- **Real target repo** — change `TARGET_REPO_PATH` in `.env` when available.
- Eventually: Supabase + Vercel for production deployment.

## How to run it locally

```bash
pnpm install
cp .env.example .env
# Fill in ANTHROPIC_API_KEY in .env
pnpm db:up                  # start Docker Postgres (pgvector/pgvector:pg16)
pnpm db:migrate             # run 6 migrations
pnpm dev                    # start Next.js dev server at http://localhost:3000
# Optional: start background worker (auto-picks up pending tasks)
pnpm --filter @gridiron/worker start
```

## How to resume work in a new session

1. Read this file (`PROJECT.md`) for current state — **32/32 pass is the baseline**
2. Read `PLAN.md` for the roadmap
3. Run `pnpm turbo run typecheck` to verify clean baseline before making changes
4. For Phase 4+: add Event Bus, specialist coding agents (Backend/Frontend/QA/Review), Manager Agent

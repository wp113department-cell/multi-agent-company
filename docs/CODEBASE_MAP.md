# Gridiron Codebase Map

> Generated 2026-07-02. Update when packages are added or major refactors occur.

## Directory Layout

```
/
├── apps/
│   ├── web/          Next.js 14 App Router — dashboard UI + REST API
│   └── worker/       Long-running poll loop — picks up pending tasks and runs agents
│
├── packages/
│   ├── shared-config/       Zod-validated env loader (single source of truth for all config)
│   ├── shared-types/        TypeScript interfaces — DevTask, AgentRun, SubTask, etc.
│   ├── shared-db/           Postgres pool + query helpers + migrations
│   ├── task-engine/         Task CRUD, status transitions, task_logs append
│   ├── agent-runtime/       Anthropic tool-use loop, worktree isolation, policy enforcement
│   ├── planning-pipeline/   PM Agent → Architect Agent → Task Decomposer (DB-backed)
│   ├── repo-tools/          Agent tools: read_file, write_file, run_command, git_diff
│   ├── repo-intelligence/   Call graph (ts-morph) + Voyage AI embeddings (pgvector)
│   ├── context-builder/     Combines graph + embeddings → ContextResult for agents
│   ├── policy-engine/       Pre-tool denylist: blocks writes to .env, git push, rm -rf, etc.
│   └── mcp-server/          stdio MCP server (JSON-RPC 2.0) exposing 4 repo intel tools
│
├── docs/
│   ├── CODEBASE_MAP.md      (this file)
│   ├── research/            Notes from reading reference repos (openhands, aider, cline, etc.)
│   ├── adr/                 Architecture Decision Records
│   └── reports/             Per-phase test reports
│
├── tests/
│   └── fixtures/
│       └── demo-repo/       Minimal TypeScript repo used by integration tests
│
└── repos/                   Cloned reference repos (READ-ONLY — do not copy code)
```

## Data Flow: Task Lifecycle

```
User creates task (POST /api/tasks)
  │
  ▼
worker polls pending tasks
  │
  ▼ [PIPELINE_MODE=full]
planning-pipeline
  ├── PM Agent (Claude Sonnet) → PmBrief
  ├── Architect Agent (Claude Sonnet) → ArchitectPlan
  └── Decomposer (Claude Sonnet) → SubTask[]
  │
  ▼
context-builder
  ├── repo-intelligence: graph query (ts-morph call graph)
  └── repo-intelligence: embedding search (pgvector cosine similarity)
  │
  ▼
agent-runtime (coding agent, Claude Sonnet)
  ├── Runs in isolated git worktree (WORKTREES_DIR/task-{id})
  ├── Tools: read_file, write_file, run_command, git_diff, done
  ├── policy-engine checks every tool call before execution
  └── All actions logged to task_logs
  │
  ▼
Task status → needs_review (human approval required)
  │
  ▼ [POST /api/tasks/:id/approve]
Changes merged to main repo (human action)
```

## Key Interfaces

### `DevTask` (`packages/shared-types/src/index.ts`)
```typescript
{ id, title, description, status, repo_path, worktree_path, created_at, updated_at }
```
Status flow: `pending → planning → in_progress → needs_review → done | failed | blocked`

### `AgentRun` (`packages/shared-types/src/index.ts`)
```typescript
{ id, task_id, agent_type, model_id, status, started_at, ended_at, tokens_in?, tokens_out?, cost_estimate? }
```

### `ContextResult` (`packages/context-builder/src/index.ts`)
```typescript
{ summary, relevantFiles: [{filePath, score}], relatedSymbols, dependencyChain }
```

### `ArchitectPlan` (`packages/planning-pipeline/src/types.ts`)
```typescript
{ technicalApproach, impactedSystems, impactedFiles, risks, testingStrategy, implementationNotes }
```

## Config (all from `packages/shared-config/src/index.ts`)

| Env Var | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | Postgres connection string | required |
| `ANTHROPIC_API_KEY` | Claude API key | required |
| `MODEL_PLANNER` | Model for PM/Architect/Decomposer | `claude-sonnet-4-6` |
| `MODEL_CODER` | Model for coding agent | `claude-sonnet-4-6` |
| `MODEL_ROUTER` | Model for router/triage (cheap) | `claude-haiku-4-5-20251001` |
| `VOYAGE_API_KEY` | Voyage AI embeddings | optional |
| `TARGET_REPO_PATH` | Repo to work on | `.` |
| `WORKTREES_DIR` | Where worktrees are created | `/tmp/gridiron/worktrees` |
| `MAX_RETRIES` | Self-correction retries before blocked | `3` |
| `PIPELINE_MODE` | `simple` = skip planning, `full` = PM→Arch→Decomp | `full` |
| `CONTEXT_BUDGET_CHARS` | Max chars for agent context | `40000` |

## Database Schema Overview

Managed by `node-pg-migrate` in `packages/shared-db/migrations/`:

| Table | Purpose |
|---|---|
| `dev_tasks` | Core task records |
| `agent_runs` | One row per agent invocation (supports multiple per task) |
| `task_logs` | Append-only structured log entries |
| `subtasks` | Sub-tasks produced by the Decomposer |
| `code_embeddings` | pgvector embeddings (voyage-code-2, 1536 dims) |
| `files` | File index for call graph persistence |
| `symbols` | Symbol index (functions, classes) |
| `edges` | Call graph edges (caller → callee) |

## MCP Server Tools (4 tools)

Exposed via `packages/mcp-server/src/index.ts` on stdio:
1. `get_context` — build ContextResult for a query
2. `search_code` — semantic embedding search
3. `get_call_graph` — outbound calls from a symbol
4. `reindex_repo` — trigger full re-index

## Test Strategy

- Unit tests: `vitest` per-package (`packages/*/src/*.test.ts`)
- Integration tests: `tests/integration/` — require real Postgres (test DB)
- Security tests: `packages/policy-engine/src/policy.test.ts`
- No E2E browser tests (Phase 0-3 scope)

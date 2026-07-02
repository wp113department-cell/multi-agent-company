# Phase 3 Test Report — Repo Intelligence, Planning Pipeline, MCP Server

**Date:** 2026-07-02  
**Phase:** Phase 3 — Repo Intelligence (call graph + embeddings), Context Builder, Planning Pipeline, MCP Server

## What Was Tested

Phase 3 covers: `packages/repo-intelligence`, `packages/context-builder`, `packages/planning-pipeline`, `packages/mcp-server`.

## Test Commands Run

```bash
pnpm --filter @gridiron/repo-intelligence typecheck
pnpm --filter @gridiron/context-builder typecheck
pnpm --filter @gridiron/planning-pipeline typecheck
pnpm --filter @gridiron/mcp-server typecheck
pnpm --filter @gridiron/tests test  # integration/graph-correctness.test.ts
```

## Results

### Integration Tests (graph correctness, fixture repo)
| File | Tests | Result |
|---|---|---|
| integration/graph-correctness.test.ts | 5 | ✅ PASS |

### Typecheck
| Package | Result |
|---|---|
| @gridiron/repo-intelligence | ✅ PASS |
| @gridiron/context-builder | ✅ PASS |
| @gridiron/planning-pipeline | ✅ PASS |
| @gridiron/mcp-server | ✅ PASS |

## Graph Correctness Coverage (5 tests, demo-repo fixture)

Fixture: `tests/fixtures/demo-repo/` — 2 TypeScript files:
- `src/math.ts` — exports `add()`, `multiply()`, `divide()`
- `src/calculator.ts` — imports math functions, exports `Calculator` class

| Test | Result |
|---|---|
| Indexes demo-repo and finds expected files (math.ts, calculator.ts) | ✅ PASS |
| Extracts symbols from math.ts (add, multiply, divide) | ✅ PASS |
| Extracts Calculator class from calculator.ts | ✅ PASS |
| Builds call graph with edges from calculator to math | ✅ PASS |
| Content hash changes when file content changes (incremental re-index basis) | ✅ PASS |

## Embedding Tests (skipped — require VOYAGE_API_KEY)
Voyage AI embedding tests are skipped when `VOYAGE_API_KEY` is not set. The embedding pipeline (`generateEmbeddings`) is unit-testable by setting the key.

## Planning Pipeline Tests (skipped — require ANTHROPIC_API_KEY + live DB)
PM Agent, Architect Agent, and Decomposer require live Anthropic API calls. These are integration-tested by running the pipeline end-to-end when both `ANTHROPIC_API_KEY` and `DATABASE_URL` are configured.

## Known Issues
- None (all non-skipped tests pass)

## Additional Phase 3 Work (this session — Gap Fill)
The following items were implemented to fill gaps identified from the MASTER_PROMPT_PACK spec:
1. ✅ `shared-config` package — single Zod-validated env loader wired into all agents
2. ✅ Role files (`packages/agent-runtime/roles/*.md`) — agents load system prompts from disk
3. ✅ Migration #8 — `tokens_in`, `tokens_out`, `cost_estimate`, `last_heartbeat_at`, `model_id` on `agent_runs`
4. ✅ Migration #9 — `subtasks` table, pipeline writes subtasks to DB
5. ✅ Migration #10 — `indexed_files`, `symbols`, `call_edges` tables with incremental re-index support
6. ✅ `persistGraphToDb()` in repo-intelligence — persists call graph to Postgres
7. ✅ API: `POST /api/tasks/:id/approve` and `POST /api/tasks/:id/reject`
8. ✅ API: cursor pagination with `nextCursor` in GET /api/tasks response
9. ✅ PIPELINE_MODE flag in runner (simple = skip planning, full = PM→Arch→Decomp)
10. ✅ Heartbeat logging in agent loop (`heartbeatAgentRun()` every 5 tool calls)
11. ✅ PlanSchema validation in planner-agent `submit_plan` tool
12. ✅ `checkPathInWorktree()` in policy engine for path traversal enforcement

## Verdict
✅ PASS — Phase 3 tests green

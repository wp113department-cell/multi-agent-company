# Dependency Version Pinning Reference

Verified from installed `node_modules` via `pnpm list` on 2026-07-02.

## Runtime Dependencies

| Package | Installed Version | Notes |
|---|---|---|
| `zod` | 3.25.76 | Schema validation — everywhere |
| `@anthropic-ai/sdk` | 0.30.1 | Anthropic Messages API with tool-use |
| `pg` | 8.22.0 | Postgres client for Node |
| `node-pg-migrate` | 7.9.1 | Migration runner |
| `ts-morph` | 24.0.0 | TypeScript AST / call graph |
| `glob` | 11.0.3 | File pattern matching |
| `next` | 14.2.35 | Next.js App Router (apps/web) |
| `react` | 18.3.1 | React runtime |
| `react-dom` | 18.3.1 | React DOM |
| `@tanstack/react-query` | 5.101.2 | Client-side data fetching + polling |
| `tailwindcss` | 3.4.19 | CSS utility framework |

## Dev/Build Dependencies

| Package | Installed Version | Notes |
|---|---|---|
| `typescript` | 5.9.3 | Strict mode compiler |
| `vitest` | 2.1.9 | Unit/integration test runner |
| `tsx` | 4.x | TS execution for scripts/CLI |
| `turbo` | 2.10.0 | Turborepo monorepo build system |
| `eslint` | 8.57.1 | Linter |
| `prettier` | 3.9.4 | Formatter |
| `@typescript-eslint/*` | 6.21.0 | TypeScript ESLint rules |
| `dotenv-cli` | 7.4.4 | Inject .env into migration commands |
| `ts-node` | 10.9.2 | Used by node-pg-migrate config |
| `dotenv` | 16.6.1 | env loading |

## Voyage AI (external, no npm package)

- API: `https://api.voyageai.com/v1/embeddings`
- Model: `voyage-code-2` — 1536 dimensions, code-optimized
- Used in: `packages/repo-intelligence/src/embeddings.ts`
- Auth: `VOYAGE_API_KEY` env var via shared-config

## Workspace Packages (all v0.1.0)

All are private workspace packages linked via `workspace:*`:
- `@gridiron/shared-config` — Zod-validated env loader
- `@gridiron/shared-types` — TypeScript interfaces (DevTask, AgentRun, etc.)
- `@gridiron/shared-db` — Postgres pool + query helpers
- `@gridiron/task-engine` — Task CRUD + task_logs
- `@gridiron/agent-runtime` — Anthropic tool-use loop + worktree management
- `@gridiron/planning-pipeline` — PM → Architect → Decomposer pipeline
- `@gridiron/repo-tools` — File read/write/git tools for agents
- `@gridiron/repo-intelligence` — Call graph (ts-morph) + embeddings (Voyage AI)
- `@gridiron/context-builder` — Combines graph + embeddings into ContextResult
- `@gridiron/policy-engine` — Denylist-based pre-tool safety checks
- `@gridiron/mcp-server` — stdio MCP server exposing 4 repo intelligence tools
- `apps/web` (`@gridiron/web`) — Next.js 14 dashboard + REST API
- `apps/worker` (`@gridiron/worker`) — Task polling loop + agent dispatch

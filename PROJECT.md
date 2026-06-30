# PROJECT.md — Current State

**This is a living document. Update it every session — it is the single source of truth for "what actually exists right now," separate from `PLAN.md` (what's intended) and `files/` (the original spec suite, which describes the full 7-stage vision, not the current build).**

Last updated: 2026-06-30 (Day 1-4 of `PLAN.md` complete)

---

## What this project is

Gridiron AI's Developer Department: an AI agent system that takes a plain-English development task, reads a real codebase, writes an implementation plan, and proposes a safe, reviewable code patch — the foundation for a larger eventual AI engineering department (see `files/` for the full long-term spec). Full scope/stage reasoning is in `PLAN.md`.

## Current build target

**Milestone:** "Foundation + safe patch proposal" — Stage 0 + Stage 1 + Stage-2-lite of the original 7-stage spec, scoped down to a 1-2 week solo AI-assisted build. Details and day-by-day plan: `PLAN.md`.

**Target repo the agent operates on:** not yet assigned. `TARGET_REPO_PATH` currently points at this project's own monorepo (self-referential, for testability). Repoint when the real target repo is available.

## Decisions made so far

| Decision | Choice | Why |
|---|---|---|
| Build scope | Stage 0+1+2-lite only, not the full 7-stage roadmap | Full roadmap is an 11-12 month, multi-engineer build per the spec's own estimate; compressing it into 1-2 weeks produces a broken shell, not a working system |
| Target repo | Self-referential for now | Real target repo not available yet; tooling built generically so repointing later is a config change, not a rewrite |
| Infra | Local-only: Docker Postgres, no cloud | Fastest to start; matches ADR-005's "trivially self-hostable" plain-Postgres approach; cloud accounts can be provisioned later without an architecture change |
| Node.js | Installed via nvm into `~/.nvm`, symlinked into `~/.local/bin` (already on PATH) | No sudo available on this machine |
| Job queue (Inngest) | Deferred, not built yet | Stage 1 spec itself says "no concurrency cap needed yet at single-agent, single-task-at-a-time scale" — a simple trigger-on-create is sufficient until that's no longer true |
| Package manager | pnpm (via corepack) | Standard pairing with Turborepo per `04_Engineering_Standards_Conventions.md` |
| GitHub remote | `https://github.com/wp113department-cell/CRR2906.git` | Provided by user |
| `dev_tasks.status` enum | Extended beyond `09_Database_Design_Specification.md`'s literal CHECK list to add `ready_for_review` and `rejected` | The spec's own `04` (definition-of-done table) and `08` (POST /tasks/:id/reject) require these two states; `09`'s enum just didn't list them. Documented in `shared-types/src/dev-task.ts`. |
| Migration file extension | `.cts` instead of `.ts` for `shared-db/migrations/*` | `node-pg-migrate`'s ts-node loader uses `require()`, which conflicts with the package's `"type": "module"`; `.cts` forces CommonJS for just that directory without affecting the rest of the package |
| Internal package imports | No `.js` extension on relative imports (e.g. `from "./dev-task"`, not `"./dev-task.js"`) | Packages are consumed as raw TS source (via `transpilePackages` in Next.js), not pre-compiled; webpack's resolver doesn't do the TS `moduleResolution: bundler` extension-rewrite trick that `.js`-suffixed imports rely on. Extensionless imports work correctly across tsc, vitest, and webpack. |
| `apps/web/.env` | Symlinked to `../../.env` | Next.js only reads `.env` from the app's own directory, not the monorepo root |

## What exists right now

_(Updated as work lands. Verified working as of this entry via real API calls + automated tests, not just "code written.")_

- [x] Monorepo scaffold (Turborepo + pnpm workspaces) — `apps/web`, `packages/{shared-types,shared-db,task-engine,agent-runtime,repo-tools,policy-engine}` (last two are empty dirs, not yet built)
- [x] Local Postgres (Docker, `docker-compose.yml`, `pnpm db:up`)
- [x] `shared-types` package — Zod schemas for `DevTask`, `TaskLog`, `AgentRun`, `CreateTaskInput`, `UpdateTaskInput`, `CreateTaskLogInput`
- [x] `shared-db` package — pg `Pool` client + 3 migrations (`dev_tasks`, `task_logs`, `agent_runs`), run via `node-pg-migrate` (`pnpm db:migrate`)
- [x] `task-engine` package — row↔domain mapping, CRUD repository functions, status-transition state machine with 7 passing unit tests (`pnpm --filter @gridiron/task-engine test`)
- [x] Task Queue API (`08_API_Specification.md` Stage 1) — `POST/GET /api/tasks`, `GET/PATCH /api/tasks/:id`, `POST /api/tasks/:id/logs`. Verified end-to-end via curl: create → list → get-with-logs → status update → invalid-transition correctly rejected with 409.
- [x] Mission Control Dashboard v1 — Task List page (status filter chips, polling every 4s, new-task form) and Task Detail page (plan, files touched, final summary, log timeline, polling every 3s), both at `apps/web/app/tasks/`
- [ ] `agent-runtime` package (Claude Agent SDK wiring) — **next up, Day 5, needs `ANTHROPIC_API_KEY`**
- [ ] `repo-tools` package (filesystem/git MCP)
- [ ] Planner Agent (plan-only, read-only)
- [ ] Agent-eval test suite
- [ ] Git worktree isolation + patch generation
- [ ] Policy Engine v1 (PreToolUse denylist)
- [ ] Diff viewer + Approve/Reject flow
- [ ] Test runner + retry loop
- [ ] Full logging/audit trail (logging plumbing exists; agent-side coverage pending agent-runtime)

**How to run it locally:** `pnpm install` → `cp .env.example .env` → `pnpm db:up` → `pnpm db:migrate` (run inside `packages/shared-db`) → `pnpm dev` (from repo root, or `pnpm --filter @gridiron/web dev`) → http://localhost:3000/tasks.

**Verification run on 2026-06-30:** `pnpm turbo run typecheck test` — 8/8 tasks pass across all 4 packages (typecheck clean on `shared-types`, `shared-db`, `task-engine`, `web`; 7/7 unit tests pass on `task-engine`). Live dev server smoke-tested: full task lifecycle (create → list → detail-with-logs → status transition → rejected invalid transition) confirmed against the real local Postgres instance, not mocked.

## Open items needed from the user

- **`ANTHROPIC_API_KEY`** — required before Day 5 (agent runtime work begins). Agent runs consume real API credits.
- **Real target repo** — local path or GitHub `owner/repo`, whenever it's ready.
- Eventually: Supabase + Vercel account details, once we're past local-only dev.

## How to resume work in a new session

1. Read this file (`PROJECT.md`) for current state.
2. Read `PLAN.md` for the roadmap and what's next.
3. Check the "What exists right now" checklist above against the actual repo (`git log`, `ls`) — don't trust a stale checkbox over the real filesystem state.
4. Continue from the next unchecked `PLAN.md` day.

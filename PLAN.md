# PLAN — Gridiron Developer Department (Build Roadmap)

**This is a living document. Update it whenever scope, sequencing, or status changes.**
**Companion doc:** `PROJECT.md` (current state, decisions, what's actually built right now).
**Source specs:** `files/00_README.md` through `files/20_Testing_Strategy.md`, `files/Gridiron Agent OS - Open Source Reference Matrix .md`, `files/main_client_share_file.md`.

---

## Locked scope decisions (2026-06-30)

The full 20-document spec describes a 7-stage, ~11-12 month, 2-6 engineer build. We are **not** attempting that compressed into 1-2 weeks — that would produce a shallow shell where nothing fully works. Instead, scope is locked to what the client brief itself calls the **first milestone**, built solo with AI-assisted ("vibe") coding:

- **In scope (this build):** Stage 0 (repo mapping) + Stage 1 (task queue, single planning agent, dashboard v1, logging) + Stage 2-lite (worktree-isolated patch proposal, diff viewer, basic Policy Engine v1 denylist, retry limits). This matches `files/main_client_share_file.md`'s "First milestone": *"A single developer agent that can receive a task, understand the repo, create a good plan, inspect files, and produce a safe implementation proposal."*
- **Out of scope (future, not started):** LangGraph multi-agent orchestration, Repository Intelligence Service (AST graph), Event Bus, Policy Engine v2, Manager/Executive Agents, Agent Registry, Engineering Memory, multi-agent specialist roles (Frontend/QA/Review/DevOps/Research/Docs), parallel epic execution, cost controller. These are Stage 3-7 in the spec and are **deliberately deferred**, not forgotten — see `files/03_Technical_Execution_Roadmap.md`.
- **Target repo:** not available yet. Building repo-inspection/patch tooling generically, initially pointed at this project's own monorepo (self-referential/dogfooding) so it's testable end-to-end now. The target path is a config value (`TARGET_REPO_PATH`) — repoint to the real Gridiron product repo the moment it's available. No architecture decision here depends on the target repo's specifics.
- **Infra:** local-only. Docker Postgres (not Supabase yet), no Vercel/cloud deploy yet. Swappable later — plain Postgres connection string, per ADR-005.
- **Requires from user before Day 5 (agent runtime work):** an `ANTHROPIC_API_KEY` for Claude Agent SDK calls. Agent runs consume real API credits.

---

## Day-by-day plan

Each day's work ends with: code runs, is tested, and `PROJECT.md` is updated. Days are work units, not calendar guarantees — if a day's slice is genuinely done early, pull the next one forward.

| Day | Goal | Builds | Done when |
|---|---|---|---|
| 1 | Environment + monorepo skeleton | Node toolchain (done), Turborepo + pnpm workspace, folder structure per `04_Engineering_Standards_Conventions.md`, git init, Docker Postgres running | `pnpm install` and `pnpm dev` both succeed from a clean clone; Postgres reachable |
| 2 | Schema + shared packages | `shared-types` (Zod: `DevTask`, `TaskLog`, `AgentRun`), `shared-db` (pg client + `node-pg-migrate` migrations for `dev_tasks`, `task_logs`, `agent_runs` per `09_Database_Design_Specification.md`) | Migrations run clean against local Postgres; schemas unit-tested |
| 3 | Task Queue API | `task-engine` package + Next.js API routes: `POST/GET /tasks`, `GET /tasks/:id`, `PATCH /tasks/:id`, `POST /tasks/:id/logs` per `08_API_Specification.md` | Integration test: create task → fetch → log → status transition, against real test DB |
| 4 | Dashboard v1 | `apps/web` Task List + Task Detail pages, status badges, polling, per `15_Mission_Control_Dashboard_Specification.md` Stage 1 | Can create/view tasks through the UI, not just curl |
| 5 | Agent runtime foundation | `agent-runtime` package: Claude Agent SDK wiring, shared base agent template (safety rules, logging, heartbeat) per `06_Agent_SDK_Specification.md`; `repo-tools`: filesystem + git MCP wired in, read-only | Agent can be invoked manually and reads real files from `TARGET_REPO_PATH` |
| 6 | Planner Agent end-to-end | Planner role file (plan-only, read-only tools), task pickup loop, plan saved to `dev_tasks.plan`, status `pending → planning → ready_for_review/blocked` | Submit a plain-English task through the dashboard → get back a plan referencing real files |
| 7 | Agent-eval suite + hardening | 8-10 representative test tasks per `20_Testing_Strategy.md`, run against the Planner; fix systematic plan-quality issues found | Plans for all eval tasks reference real files and are internally consistent |
| 8 | Worktree isolation + patch generation | Git worktree creation/teardown (ADR-004), coding agent role (scoped `Edit`/`Write`/`Bash`), patch/diff produced into worktree, never against main checkout | Agent proposes a real diff in an isolated worktree for a small task |
| 9 | Policy Engine v1 + diff review | PreToolUse hook denylist (`.env*`, `secrets/**`, `.github/workflows/**`, `rm -rf`, deploy commands) per `13_Policy_Engine_Specification.md`; diff viewer + Approve/Reject API+UI per `08`/`15` | Denylist blocks a deliberate bad write in a test; diff viewer shows a real proposed patch end-to-end |
| 10 | Test runner + retry loop | Run typecheck/lint/test inside the worktree after a patch, capture results, basic self-correction loop (max 3 retries) per `04`/`20` | A deliberately broken patch gets caught by typecheck and the agent retries within its limit, then escalates to `blocked` if still failing |
| 11 | Logging/audit completeness + end-to-end pass | Every tool call/decision logged to `task_logs` with category+metadata; heartbeat on `agent_runs`; full Stage 1+2-lite E2E test (submit → plan → patch → diff → approve) | A cold run of the full flow works with nothing manually patched mid-run |
| 12-14 | Buffer: hardening, docs, repoint to real repo when available | Fix whatever broke in day 11's E2E pass; update all docs; if target repo becomes available, repoint `TARGET_REPO_PATH` and re-run the eval suite against it | `PROJECT.md` accurately describes a working system a new engineer (or agent) could pick up |

---

## Explicit non-goals for this build (do not scope-creep into these)

- No LangGraph orchestration — not needed until multi-step planning (PM→Architect→Decomposer) exists (Stage 3). A single Planner agent doesn't need a graph.
- No Inngest/job queue infra yet — Stage 1's actual requirement is "no concurrency cap needed at single-agent, single-task-at-a-time scale." A simple poll-or-trigger-on-create mechanism is sufficient; revisit only if this becomes a real bottleneck.
- No Event Bus — single agent, nothing to decouple yet (Stage 4 concept).
- No Agent Registry, no Manager/Executive Agent, no specialist Frontend/QA/Review/DevOps/Research/Docs agents — Stage 4-7. Adding them later is additive (new role files + dispatch table entries), not a rewrite, per `06_Agent_SDK_Specification.md`'s own design.
- No Supabase/Vercel/cloud deploy — local Postgres + local dev server is sufficient to prove the system works; cloud deploy is a config/infra step, not an architecture decision, and shouldn't consume build days until the foundation is solid.

## Next decision points to revisit with the user

- When the real target Gridiron repo becomes available — repoint and re-validate.
- When ready to move past local-only — which hosting (Vercel) and DB (Supabase) accounts to provision.
- Whether to proceed into Stage 3+ (Repository Intelligence, multi-agent) after this milestone ships, and at what pace.

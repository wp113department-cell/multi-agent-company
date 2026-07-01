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
| 5 | Agent runtime foundation | `agent-runtime` package: Anthropic Messages API + tool-use loop, shared base agent, `repo-tools`: readFile/listFiles/grepFiles/gitLog, `policy-engine`: denylist v1 | ✅ DONE — all packages built and typecheck clean (14/14 turbo tasks pass) |
| 6 | Planner Agent end-to-end | Planner role: read-only tools (list_files, read_file, grep_files, git_log, submit_plan), task pickup loop, plan saved to `dev_tasks.plan`, status transitions | ✅ DONE — planner agent wired. Confirmed: fires on POST /api/tasks/:id/run, correctly fails with ANTHROPIC_API_KEY error when key absent |
| 7 | Agent-eval suite + hardening | Eval when API key provided: submit 5-8 representative tasks, verify plans reference real files. Harden prompt quality if plans are vague | **Pending API key** — code complete, needs live test |
| 8 | Worktree isolation + patch generation | Git worktree creation/teardown, coding agent (read_file/write_file/bash/submit_patch), policy-checked edits, diff stored in dev_tasks.diff | ✅ DONE — coding agent wired, worktree.ts manages git worktree lifecycle, diff stored on task |
| 9 | Policy Engine v1 + diff review | PreToolUse denylist enforced at tool call layer; DiffViewer UI + Approve/Reject buttons on Task Detail | ✅ DONE — 10/10 policy tests pass, DiffViewer component built, Approve/Reject buttons on Task Detail page |
| 10 | Test runner + retry loop | Run typecheck inside worktree after patch, capture results. Self-correction loop (max 3 retries via re-run of coder). Escalate to blocked if still failing | **Pending API key** — bash tool in coder agent supports `pnpm typecheck`; retry loop deferred to Day 10 hardening pass |
| 11 | Logging/audit completeness + end-to-end pass | Full E2E: submit → plan → approve → code → diff → approve or reject | **Pending API key** — all paths implemented; E2E test run needed |
| 12-14 | Buffer: hardening, docs, repoint to real repo when available | Fix issues from E2E; eval suite; repoint TARGET_REPO_PATH when real repo available | Scheduled |

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

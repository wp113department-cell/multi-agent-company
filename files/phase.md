# AI Developer Agent System — Complete Phase-wise Build Plan
### From Zero to Full AI Engineering Department

---

## PHASE 0 — Foundation & Repository Mapping
> Goal: Set up the project properly and understand the codebase before building anything.

- [ ] Set up Turborepo monorepo structure
- [ ] Create folder/package structure (`apps/web`, `packages/task-engine`, `packages/agent-runtime`, `packages/repo-tools`, `packages/policy-engine`, `packages/shared-types`, `packages/shared-db`)
- [ ] Set up TypeScript + ESLint + Prettier across all packages
- [ ] Set up GitHub repository + branch protection rules
- [ ] Set up Supabase project (database)
- [ ] Connect environment variables and secrets management
- [ ] Study and document the real Gridiron codebase:
  - Main entry points
  - Existing workers and agents
  - Queue systems
  - API routes and services
  - Test commands
  - Folder patterns to follow
- [ ] Produce a written Technical Architecture Report of the codebase

**You have at the end of Phase 0:** A clean, professional project scaffold and a full map of the codebase the agents will work on.

---

## PHASE 1 — Single Planning Agent
> Goal: One AI agent that reads a task, reads the codebase, and produces a written plan. No code changes yet.

**Task Queue**
- [ ] Create `dev_tasks` database table (taskId, title, description, priority, status, assignedAgent, project, filesTouched, plan, finalSummary, createdAt, updatedAt)
- [ ] Create `task_logs` database table (logId, taskId, category, message, metadata, createdAt)
- [ ] Create `agent_runs` database table (runId, taskId, agentType, status, checkpointId, startedAt, completedAt)
- [ ] Build Task Queue API:
  - POST `/tasks` — create a task
  - GET `/tasks` — list all tasks
  - GET `/tasks/:id` — get single task with full log timeline
  - PATCH `/tasks/:id` — update task status/fields
  - POST `/tasks/:id/logs` — append a log entry

**Agent Runtime**
- [ ] Install and configure Claude Agent SDK
- [ ] Connect Anthropic API key
- [ ] Set up MCP filesystem server (agent reads files)
- [ ] Set up MCP git server (agent reads git history/structure)
- [ ] Wire Inngest for background job execution
- [ ] Build agent trigger: when task status = `pending`, automatically start the agent
- [ ] Write the Planner Agent role file with system prompt
- [ ] Agent workflow: receive task → read relevant files → produce written plan → save plan → mark `ready_for_review`

**Repo-Reading Tools**
- [ ] Agent can list all files in the repo
- [ ] Agent can search files by keyword
- [ ] Agent can read file contents
- [ ] Agent can understand folder structure

**Mission Control Dashboard v1**
- [ ] Set up Next.js app with Tailwind CSS + TanStack Query
- [ ] Task List page (all tasks, status badges, filterable by status/project)
- [ ] Task Detail page (task description + generated plan + log timeline)
- [ ] Submit new task form

**Test Suite**
- [ ] Unit tests for Task Queue API
- [ ] Agent evaluation tests: run 10 sample tasks, verify plans reference real files and are accurate

**You have at the end of Phase 1:** A working AI agent you can give a task to in plain English and get back a real written plan referencing actual files in your codebase.

---

## PHASE 2 — Safe Code Proposal
> Goal: The agent proposes real code changes in a completely isolated environment. Nothing touches the real codebase until a human approves it.

**Git Worktree Isolation**
- [ ] Configure all coding agents to run with `isolation: worktree` (every change lands in a temporary, disposable copy of the repo)
- [ ] Worktree is preserved on `blocked` tasks, torn down on `completed`

**Patch Generation**
- [ ] Enable `Edit`/`Write` tools scoped to worktree only
- [ ] Enable `Bash` tool scoped to typecheck/lint/test commands only (no destructive commands)
- [ ] Agent produces a real code diff as output

**Policy Engine v1 (Safety Guardrails)**
- [ ] Build PreToolUse hook that runs before every Write/Edit/Bash call
- [ ] Hard deny list: `.env`, `.env.*`, `**/secrets/**`, `.github/workflows/**`, any deploy commands
- [ ] Enforced in application code — cannot be talked around by prompt
- [ ] Max retry limit: 3 attempts before task is marked `blocked`

**Automated Test Runner + Self-Correction Loop**
- [ ] After code change, agent automatically runs: typecheck → lint → test → build
- [ ] Agent reads failures, identifies cause, fixes, reruns
- [ ] After 3 failed attempts: mark task `blocked`, preserve logs, surface for human review

**Diff Viewer + Approval UI**
- [ ] Add diff viewer to Task Detail page (side-by-side or unified view)
- [ ] Approve button → calls `POST /tasks/:id/approve` → patch is ready for merge
- [ ] Reject button → calls `POST /tasks/:id/reject` → agent can be re-triggered with feedback
- [ ] `GET /tasks/:id/diff` API endpoint
- [ ] `filesTouched` field updated for every task showing which files the agent touched

**`tasks/:id/approve` and `/reject` endpoints**
- [ ] On approve: mark task `completed`, preserve worktree diff for merge
- [ ] On reject: mark task with feedback, allow re-trigger

**You have at the end of Phase 2:** An AI developer that takes a task, reads your real code, writes a plan, proposes a tested code change in a sealed sandbox, runs its own tests, fixes its own errors up to 3 times, and waits for your approval before anything is real.

---

## PHASE 3 — Repository Intelligence + Planning Subsystem
> Goal: The agent stops guessing about the codebase and actually understands it. Planning is split into dedicated specialist steps.

**Repository Intelligence Service**
- [ ] Set up AST-based code graph engine (Tree-sitter parsing)
- [ ] Build Repository Scanner (indexes all files on startup + incrementally on each merge)
- [ ] Build Dependency/Import Graph (which files import which)
- [ ] Build Call Graph (which functions call which, across files)
- [ ] Build Symbol Graph (every function, class, type — where defined, where used)
- [ ] Expose the graph as its own MCP server other agents can query
- [ ] Incremental re-indexing on every merge to `main`
- [ ] Full re-index on weekly schedule

**Context Builder**
- [ ] Build `buildContext(task)` function: queries the graph, returns `{ relevantFiles, dependencies, summary }` for any task
- [ ] Context Cache: results are cached per task so Backend Agent and QA Agent don't re-index the same files

**Vector Embeddings (pgvector)**
- [ ] Add pgvector extension to Postgres
- [ ] Build embedding pipeline: code summaries + documentation → embedded and stored
- [ ] Semantic search: "what touches the email discovery system?" returns relevant files, not just keyword matches

**Planning Subsystem (LangGraph)**
- [ ] Set up LangGraph `StateGraph` with shared state schema
- [ ] Add Postgres checkpointing (crashed runs resume, not restart)
- [ ] Build Product Manager Agent node: raw request → goals, constraints, acceptance criteria (Zod-validated output)
- [ ] Build Architect Agent node: PM output + context builder → impacted systems, risks, technical approach
- [ ] Build Task Decomposer node: architect output → typed subtasks (backend / frontend / test / docs)
- [ ] Add human-in-the-loop `interrupt()` after Task Decomposer: show full plan + subtask breakdown in dashboard before any coding starts

**Dashboard — Phase 3 additions**
- [ ] Pipeline view in Task Detail: PM output → Architect output → subtask breakdown, each inspectable
- [ ] Human approval checkpoint shown in UI before coding agents start

**You have at the end of Phase 3:** The system accurately identifies which files a feature touches (from the real code graph, not a guess), and produces a PM brief + technical plan + subtask breakdown before any code is written.

---

## PHASE 4 — Specialist Coding Agents + QA Loop
> Goal: Multiple AI agents implement, test, and fix code — together.

**Specialist Agent Roles**
- [ ] Shared base agent template (common safety rules, logging, error handling, heartbeat)
- [ ] Backend Developer Agent role file (scoped tools: Edit/Write in worktree, Bash for tests only)
- [ ] Frontend Developer Agent role file (same scope, different focus)
- [ ] QA Agent role file (Bash for test commands only, no Edit/Write)
- [ ] Code Review Agent role file (Read only — structurally cannot edit anything)

**Skills System**
- [ ] Set up Claude Code Skills (versioned `SKILL.md` files agents load on demand)
- [ ] Example: "Run Migrations Safely" skill any backend agent can load without re-implementing it

**Event Bus**
- [ ] Set up Postgres `LISTEN/NOTIFY` as the event bus
- [ ] Define event types: `task.planned`, `architecture.ready`, `subtask.assigned`, `qa.passed`, `qa.failed`, `review.completed`, `task.blocked`
- [ ] Events table in database (eventId, eventType, taskId, payload, emittedBy, createdAt)
- [ ] Agents stop calling each other directly — they emit events and subscribe to events
- [ ] Failed event handling: retry 3 times → write to `failed_events` log table

**Artifact Store**
- [ ] `artifacts` table (artifactId, taskId, type, version, storagePath, createdByAgent, createdAt)
- [ ] Every pipeline step writes its output as a versioned artifact: plan, patch, test results, review findings
- [ ] Object storage connected (Supabase Storage / S3)

**Context Cache**
- [ ] Once Backend Agent resolves context for a task, QA and Reviewer reuse the same cache
- [ ] Significant token and cost savings

**Agent Dispatch Logic**
- [ ] On `subtask.assigned` event, dispatch to the correct agent based on subtask type
- [ ] Each agent spawned with `isolation: worktree`

**QA + Self-Correction Loop**
- [ ] QA Agent runs on `qa` subtasks: typecheck → lint → test → build
- [ ] On failure: emit `qa.failed` → originating dev agent attempts fix → rerun → cap at 3 retries → emit `task.blocked`
- [ ] Code Review Agent runs on `review.completed`: outputs structured findings (blocking / non-blocking / suggestion) as a versioned artifact

**Dashboard — Phase 4 additions**
- [ ] Full pipeline view per task: PM → Architect → Decomposer → Dev → QA → Review
- [ ] Every artifact individually inspectable and downloadable from the dashboard

**You have at the end of Phase 4:** A real multi-agent team — Backend Agent writes code, QA Agent tests it, Code Review Agent reviews it, all automatically, with the human only needing to approve the final result.

---

## PHASE 5 — Developer Manager Agent + Cost Control
> Goal: One agent coordinates everything. You manage one agent, not many.

**Developer Manager Agent**
- [ ] Build Manager Agent as a LangGraph supervisor node above the Phase 3–4 pipeline
- [ ] Manager creates an "epic" from a high-level goal
- [ ] Manager tracks all child subtask statuses in real time
- [ ] Manager retries failed subtasks automatically
- [ ] If 2+ subtasks fail repeatedly: halt entire epic, notify human
- [ ] Manager assembles a single batched approval package when all subtasks complete

**Cost Controller**
- [ ] Before epic execution begins, Manager produces an estimate: expected tokens, approximate dollar cost, expected runtime
- [ ] Based on subtask count and complexity (refined over time using historical data)
- [ ] Epics above a configurable cost threshold require explicit human approval before agents start
- [ ] Cost estimate vs. actual shown on Epic Approval screen

**Policy Engine v2 (Full Rules Engine)**
- [ ] Migrate from hard-coded denylist to config-driven `policies` table (triggerPattern, requiredApprovalRole, blocking)
- [ ] Example rules: "changes to customer-facing APIs require Architect sign-off," "database migrations require human approval before QA runs," "auth changes require Security review"
- [ ] Adding a new rule = one database insert, not a code change
- [ ] Manager Agent and Architect Agent both check this table before proceeding

**DevOps Agent**
- [ ] Build DevOps Agent with read-only environment/build health checks
- [ ] No deploy credentials ever wired — deploy remains a human action permanently

**Epic Approval View (Dashboard)**
- [ ] New top-level "Epics" page
- [ ] Each epic shows: all subtasks, all diffs, all QA results, all review findings, cost estimate vs. actual
- [ ] Single Approve/Reject action covers the whole epic
- [ ] Human approval gate is enforced at the application layer — cannot be bypassed

**APIs — Phase 5 additions**
- [ ] `POST /epics` — create an epic
- [ ] `GET /epics/:id` — full epic detail
- [ ] `POST /epics/:id/approve` — single approval covering entire epic

**You have at the end of Phase 5:** Describe one feature in plain English → receive one clean approval screen covering everything the agents built → approve once → done.

---

## PHASE 6 — Research Agent + Documentation Agent + Agent Registry
> Goal: The department is fully rounded out. Agents research before building, document after shipping, and the whole fleet is managed from one place.

**Research Agent**
- [ ] Build Research Agent with web search + GitHub MCP read access
- [ ] Output schema: findings, relevant APIs/libraries, recommended approach, risks
- [ ] Insert Research Agent as the first step in the pipeline (Research → PM → Architect → Decomposer → Agents)
- [ ] Agent reads GitHub repos, technical docs, and competitor approaches before planning begins

**Documentation Agent**
- [ ] Build Documentation Agent with Write access scoped to `*.md` files and doc folders only
- [ ] Automatically triggered after every approved merge
- [ ] Updates README files, task logs, project state docs

**Agent Registry**
- [ ] `agents` table (agentId, name, type, version, capabilities[], tools[], promptRef, owner, successRate, avgRetries, lastUpdated)
- [ ] Capability tags per agent (e.g., `git`, `docker`, `sql`, `browser`)
- [ ] Manager Agent dispatches by capability tag, not hard-coded agent names
- [ ] Agent Registry page in dashboard: list all agents, versions, capabilities, live success-rate metrics

**Engineering Memory v1**
- [ ] Embed completed tasks: problem, plan, patch, outcome, errors, fixes
- [ ] Store in pgvector
- [ ] Architect Agent queries Engineering Memory alongside the Repository Intelligence Service
- [ ] Future tasks similar to past ones benefit from what was learned

**APIs — Phase 6 additions**
- [ ] `GET /agents` — list all registered agents with capabilities and metrics
- [ ] `GET /agents/:id/metrics` — success rate, avg retries, recent run history

**Full pipeline now:**
Research → PM Agent → Architect Agent → Task Decomposer → Backend/Frontend/QA/Review Agents → Documentation Agent → Manager Agent → Human Approval

**You have at the end of Phase 6:** A complete AI engineering department — it researches before building, documents after shipping, and every agent in the system is tracked and measured.

---

## PHASE 7 — Parallel Execution at Scale + Executive Agent
> Goal: Many features move through the pipeline at the same time. One plain-language entry point for any goal.

**Executive Agent**
- [ ] Build Executive Agent as the single top-level entry point
- [ ] Accepts a plain-language goal from any stakeholder (technical or not)
- [ ] Creates one or more epics and hands them to the Manager Agent
- [ ] Reports progress and results in plain business language, not engineering detail
- [ ] `POST /goals` and `GET /goals/:id` API endpoints

**Concurrency Infrastructure**
- [ ] Migrate from Inngest to Redis + BullMQ for high-throughput job scheduling
- [ ] Migrate Event Bus from Postgres `LISTEN/NOTIFY` to Redis Streams (if load requires it)
- [ ] Per-epic worktree namespacing (concurrent epics never touch the same files)
- [ ] Concurrency cap: start at 10–20 concurrent epics, scale up as stability is confirmed
- [ ] Migrate vector search from pgvector to Qdrant (if embedding volume requires it)

**Productivity Dashboard**
- [ ] Metrics page: tasks completed, average time per pipeline stage, failure rates by agent type/version
- [ ] Data pulled from Agent Registry metrics
- [ ] Daily batch review queue: completed epics reviewed together on a schedule rather than one at a time

**APIs — Phase 7 additions**
- [ ] `POST /goals` — Executive Agent entry point
- [ ] `GET /goals/:id` — plain-language progress and results summary

**Final organization at Phase 7:**
```
Executive Agent
      ↓
Developer Manager Agent
      ↓
Research → PM → Architect → Decomposer
      ↓
Backend / Frontend / QA / DevOps / Code Review / Documentation Agents
      ↓
HUMAN APPROVAL
      ↓
Merge → Deploy
```

**You have at the end of Phase 7:** A full AI engineering department. Describe a product or feature, the department researches it, plans it, builds it, tests it, reviews it, documents it, and brings it to you for one final approval.

---

## Safety Rules — Permanent Across Every Phase

These never change, at any phase, no matter how advanced the system becomes:

- No agent ever deploys to production without explicit human approval
- No agent ever touches `.env` files, secrets, or deployment configs
- Every code change happens in an isolated git worktree until a human approves it
- Every agent action is logged with timestamp, task ID, and agent identity — full audit trail
- Max 3 self-correction retries before a task is escalated to a human
- No agent modifies its own rules or governing logic without a human reviewing the change

---

## Technology Used Across All Phases

| What | Technology |
|---|---|
| AI Model | Claude API (Anthropic) |
| Agent Framework | Claude Agent SDK |
| Multi-Agent Orchestration | LangGraph |
| Tool/Data Access | MCP (Model Context Protocol) |
| Relational Database | PostgreSQL (via Supabase) |
| Vector Search | pgvector → Qdrant at scale |
| Background Jobs | Inngest → Redis + BullMQ at scale |
| Event Bus | Postgres LISTEN/NOTIFY → Redis Streams at scale |
| Frontend Dashboard | Next.js + TypeScript + Tailwind CSS |
| Backend API | Next.js API routes → NestJS at scale |
| Monorepo | Turborepo |
| Error Tracking | Sentry |
| Object Storage | Supabase Storage / S3-compatible |
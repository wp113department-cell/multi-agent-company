# GRIDIRON AI DEVELOPER DEPARTMENT — MASTER PROMPT PACK
### 8 Prompts → 8 Days → Full Production System
**How to use:** Paste ONE prompt per day into Claude Code (opened in your project root). Do not paste the next prompt until the previous one gave you a ✅ GREEN FLAG and updated `project.md`. Every prompt is self-contained, self-testing, and self-documenting.

---

## ⚙️ SETUP — DO THIS ONCE BEFORE PROMPT 1

Create a file named `CLAUDE.md` in your project root and paste the block below into it. Claude Code automatically reads `CLAUDE.md` on every session — this makes the global rules permanent so you never have to repeat them.

```markdown
# CLAUDE.md — Permanent Project Rules (Gridiron Developer Department)

## SOURCE OF TRUTH
- The 20 spec documents (00–20 .md files) in this project are the source of truth. If your plan conflicts with them, the docs win.
- `project.md` is the LIVE STATE FILE. Read it at the START of every session. Update it at the END of every session. Never delete history from it — append.

## ZERO HALLUCINATION RULES (mandatory, every session)
1. NEVER invent an API, package, method, or config option. Before using ANY npm package: run `npm view <package> version` to confirm it exists and pin the real latest stable version in package.json.
2. Before using any Claude Agent SDK, LangGraph, Inngest, Supabase, or MCP API: read the actual installed package's TypeScript types in node_modules (or its README) and code against those types, not memory.
3. If you are unsure whether something exists, CHECK (read files, run commands) — never guess.
4. Every file path you reference must actually exist. Verify with ls/glob before importing.
5. After writing any code, you MUST run it (typecheck at minimum) before claiming it works. "It should work" is banned — only "it ran and passed" counts.

## ZERO HARDCODING RULES
1. No secrets, API keys, URLs, model names, thresholds, retry limits, or ports in source code. Everything goes through a single typed config module (`packages/shared-config`) that reads env vars and validates with Zod at boot. Missing required env = crash at startup with a clear message, never a silent default for secrets.
2. Model names live in config (e.g. MODEL_PLANNER, MODEL_CODER, MODEL_ROUTER) so we can swap models without code changes.
3. Policy rules, retry limits, concurrency caps: config or database tables, never inline constants.
4. Ship a complete `.env.example` with every variable documented.

## MODEL TIERING (cost control — mandatory)
- ROUTER/TRIAGE/HEARTBEAT/SUMMARY work → Claude Haiku (cheapest)
- CODING/QA/REVIEW agents → Claude Sonnet (best cost/quality for code)
- ARCHITECT/PM/MANAGER reasoning → Claude Sonnet (upgrade to Opus only via env var if quality demands it)
- Always enable prompt caching on system prompts and repeated context. Use the Context Cache (one context resolution per task, reused by all agents on that task).

## REAL AGENTS ONLY
- Every "agent" is a real Claude Agent SDK `query()` run with real tools, real MCP servers, and real scoped permissions — never a stub, never a mocked LLM response in production code paths (mocks allowed ONLY inside test files).

## /repos REFERENCE RULE
- The `/repos` folder contains 10 cloned open-source projects (openhands, aider, continue, opencode, cline, roo-code, swe-agent, autogen, langgraph, composio). They are ARCHITECTURAL REFERENCES ONLY.
- You may READ them to understand patterns. You must NEVER copy, port, or paraphrase their source code into ours. All Gridiron code is original. (See Gridiron Open Source Reference Matrix doc.)

## ENGINEERING STANDARDS (from doc 04)
- TypeScript strict mode everywhere, no implicit any. Zod schema for every agent output — validated before accepted.
- Monorepo: Turborepo. Structure: apps/web + packages/{task-engine, agent-runtime, repo-tools, policy-engine, event-bus, shared-types, shared-db, shared-config}.
- Conventional Commits. Every phase = its own git branch `stage-N/description`, merged only after tests pass.
- Simple > clever. Small files, pure functions, no dead code, no TODO-stubs left behind.

## PERMANENT SAFETY RULES (never relax, any phase)
- No agent writes to `.env*`, `secrets/**`, `.github/workflows/**` — enforced by PreToolUse hook in CODE, not prompt.
- No agent ever gets deploy credentials. Deploy is a human action forever.
- All agent code changes happen in isolated git worktrees until human approval.
- Max 3 self-correction retries → then status `blocked`, logs preserved.
- Every agent action logged to task_logs with timestamp + task_id + agent identity.

## END-OF-SESSION PROTOCOL (every prompt, no exceptions)
1. Run the FULL test suite (this phase + ALL previous phases' tests). All must pass.
2. Write `docs/reports/PHASE_<N>_TEST_REPORT.md` — what was tested, commands run, real output, pass/fail.
3. Update `project.md`: phase status, what was built, files created/changed, test results, known issues, exact next steps.
4. Git commit everything with a conventional commit message.
5. Print the final verdict: "✅ GREEN FLAG — PHASE N COMPLETE" only if every test passed, or "🔴 RED FLAG" with the exact remaining issues. Never print green flag with failing tests.
```

Also create an empty `project.md` in the root with just: `# Project State — Gridiron Developer Department\nStatus: not started`. Prompt 1 takes it from there.

---
---

# 📋 PROMPT 1 (DAY 1) — Foundation + Task Queue + First Planning Agent
*(Covers phase.md PHASE 0 + PHASE 1 together — they belong in one session)*

```
Read CLAUDE.md and project.md first. Today you build Phase 0 + Phase 1 of the Gridiron AI Developer Department, per the spec docs 01–09, 14, 15, 16, 20 in this project.

== STEP 0: RESEARCH BEFORE BUILDING (do not skip) ==
1. Read /repos/openhands — study ONLY: agent lifecycle, session/run state model, how runs transition between states. Write 1 page of notes to docs/research/openhands-notes.md (concepts only, zero code copied).
2. Read /repos/swe-agent — study ONLY: how it structures the plan step and trajectory logging. Notes to docs/research/swe-agent-notes.md.
3. Verify current stable versions with `npm view <pkg> version` for: @anthropic-ai/claude-agent-sdk, next, inngest, zod, @supabase/supabase-js, drizzle-orm (or node-pg-migrate), @tanstack/react-query, tailwindcss, vitest, turbo. Record exact versions in docs/research/versions.md. Pin these versions.
4. Read the installed @anthropic-ai/claude-agent-sdk type definitions after install to learn the real query() options shape, hooks API, and permission modes. Code against the real types.

== STEP 1: MONOREPO SCAFFOLD (Phase 0) ==
- Turborepo with: apps/web (Next.js App Router + TypeScript + Tailwind + TanStack Query) and packages/{task-engine, agent-runtime, repo-tools, shared-types, shared-db, shared-config}.
- TypeScript strict everywhere, shared tsconfig, ESLint + Prettier, root scripts: typecheck, lint, test, build (all runnable via turbo).
- packages/shared-config: single Zod-validated env loader. Vars (all in .env.example, documented): DATABASE_URL, ANTHROPIC_API_KEY, MODEL_PLANNER, MODEL_ROUTER, INNGEST_EVENT_KEY, INNGEST_SIGNING_KEY, TARGET_REPO_PATH (absolute path of the codebase agents will analyze), MAX_RETRIES=3, LOG_LEVEL. No hardcoded values anywhere else.
- packages/shared-db: Postgres client + versioned migrations (drizzle-kit or node-pg-migrate — pick one, justify in an ADR appended to docs/adr/). Migration 001 creates exactly the Stage 1 tables from doc 09: dev_tasks, task_logs, agent_runs — same columns, same CHECK constraints, same indexes.
- Works against Supabase Postgres via DATABASE_URL, but uses ZERO Supabase-specific features (plain Postgres, per ADR-005).

== STEP 2: CODEBASE MAP (Phase 0 deliverable) ==
Analyze the repository at TARGET_REPO_PATH (if env not set, analyze THIS monorepo itself as the target). Produce docs/CODEBASE_MAP.md: main folders, entry points, workers/queues, API routes, test commands, patterns to follow. Every file path in it must be real — verify each with ls before writing it.

== STEP 3: TASK QUEUE API (Phase 1) ==
In packages/task-engine + exposed via Next.js API routes, implement doc 08 Stage 1 exactly:
POST /api/tasks, GET /api/tasks (filter by status/project, cursor pagination limit 20 max 100), GET /api/tasks/:id (with full ordered task_logs), PATCH /api/tasks/:id, POST /api/tasks/:id/logs.
- Zod validation on every request body. Errors as { error: { code, message } }. Correct status codes (201/400/404/409/500).
- Status transitions validated in code: pending→planning→ready_for_review|blocked|failed only (Stage 1 set). Illegal transition = 409.

== STEP 4: PLANNING AGENT (Phase 1 — REAL agent) ==
In packages/agent-runtime:
- Inngest function triggered on task creation (emit event from POST /tasks): picks up pending task → sets status planning → runs the Planner Agent → saves plan → sets ready_for_review (or blocked with reason).
- Planner Agent = real Claude Agent SDK query() run, model from MODEL_PLANNER config, READ-ONLY tools (Read, Glob, Grep only — no Edit/Write/Bash), cwd = TARGET_REPO_PATH, maxTurns capped via config.
- System prompt (write it as a versioned file packages/agent-runtime/roles/planner.md): produce a plan with sections — Task Interpretation, Files To Inspect (must be REAL paths it actually read), Implementation Steps, Risks/Unknowns, Test Strategy. Output validated against a Zod PlanSchema; invalid output = one retry, then blocked.
- EVERY tool call and decision logged to task_logs (category: planning / files_inspected / error / summary) with metadata. Heartbeat: agent_runs.status updated on an interval so a stalled run is detectable (doc 16).

== STEP 5: MISSION CONTROL v1 (Phase 1) ==
apps/web per doc 15 Stage 1: Task List page (status badges, consistent colors: amber blocked, green completed, red failed; filters), Task Detail page (description + rendered plan + chronological log timeline, polling every few seconds), New Task form. Clean, minimal, professional UI. Every agent output shows which agent/run/timestamp produced it.

== STEP 6: TESTS (must all pass before green flag) ==
- Unit tests (Vitest): config loader, status-transition logic, Zod schemas, task-engine handlers.
- Integration tests: full Task Queue API against a real test database (create → transition → logs → fetch) — use a disposable Postgres (docker or a test schema).
- Agent evaluation test (doc 20): create 3 sample tasks against this monorepo as target repo; run the real Planner Agent; assert programmatically that each saved plan (a) validates against PlanSchema, (b) every file path mentioned in "Files To Inspect" actually exists on disk, (c) task ended in ready_for_review. This is the anti-hallucination gate.
- E2E smoke (Playwright): submit task via UI → plan appears on detail page.

== STEP 7: END-OF-SESSION PROTOCOL ==
Follow CLAUDE.md protocol exactly: run everything, write docs/reports/PHASE_1_TEST_REPORT.md with real command output, update project.md (phase table: Phase 0 ✅, Phase 1 ✅, files built, env vars added, how to run, next = Phase 2), commit on branch stage-1/foundation, print ✅ GREEN FLAG only if all tests genuinely passed.
```

---
---

# 📋 PROMPT 2 (DAY 2) — Safe Code Proposal: Worktrees, Patches, Policy Engine v1, Self-Fix Loop, Diff Approval

```
Read CLAUDE.md and project.md. Verify Phase 1 first: run the full existing test suite. If anything fails, FIX IT before starting Phase 2 — never build on red. Today = phase.md PHASE 2, per docs 13 (Policy Engine v1), 08 (Stage 2 API), 15 (Stage 2 UI), 17, 20.

== STEP 0: RESEARCH ==
1. /repos/aider — study: repo-map concept, diff/patch generation strategy, git workflow. Notes → docs/research/aider-notes.md. Concepts only.
2. /repos/cline — study: plan/act separation and approval workflow. Notes → docs/research/cline-notes.md.
3. Read the installed Agent SDK types for: hooks (PreToolUse), permission modes, and how to scope allowed tools per query. Confirm the real API shape before wiring anything.

== STEP 1: GIT WORKTREE ISOLATION (packages/repo-tools) ==
- WorktreeManager: createWorktree(taskId) → new branch agent/task-<id> + isolated worktree under a configurable WORKTREES_DIR (env, not hardcoded); getDiff(taskId) → unified diff vs base branch; teardown(taskId); preserve(taskId).
- Rules: worktree preserved on blocked, preserved until approval decision on ready_for_review, torn down after completed. All operations via a proper git library or child_process git with full error handling — verify every git command's exit code, no silent failures.

== STEP 2: POLICY ENGINE v1 (packages/policy-engine) ==
- A PreToolUse hook (real Agent SDK hook API) that runs before EVERY Edit/Write/Bash call:
  DENY path matches: .env, .env.*, **/secrets/**, .github/workflows/** 
  DENY bash matching: deploy, kubectl, terraform, rm -rf, git push, npm publish, curl/wget to external hosts, and any command not on the ALLOWLIST.
  Bash ALLOWLIST (config, not hardcoded): the target repo's typecheck/lint/test/build scripts only.
  Additional structural guard: any Edit/Write with a resolved absolute path OUTSIDE the task's worktree = DENY.
- On deny: tool call blocked in code, denial logged to task_logs (category: policy_denied) with the rule that fired, agent receives a clear denial message and must report, not retry around it.
- Policy engine is pure, unit-testable functions + the hook wrapper. This is enforced at application layer — a prompt can never bypass it.

== STEP 3: CODER AGENT + SELF-CORRECTION LOOP ==
- Extend the pipeline: after plan is approved-to-code (add POST /api/tasks/:id/start-coding for now — human triggers coding from the plan in the UI), status → coding.
- Coder Agent: real SDK query(), model MODEL_CODER (add to config), tools Read/Glob/Grep/Edit/Write/Bash, cwd = the task's WORKTREE, wrapped by the Policy hook. Role file packages/agent-runtime/roles/coder.md: implement exactly the approved plan, nothing outside it.
- After the agent finishes edits, the RUNTIME (not the agent) runs the check sequence in the worktree: typecheck → lint → test → build (commands from config/target repo package.json). Failures are captured and fed back to the agent as a fix task. Loop: max MAX_RETRIES (config, default 3) attempts, then status blocked with full failure logs preserved. On success: status testing→ready_for_review, diff stored as an artifact file, files_touched updated on the task.
- Track token usage per run from SDK result messages → store on agent_runs (tokens_in, tokens_out, cost_estimate) — add migration. This feeds Phase 5 cost control.

== STEP 4: DIFF API + APPROVAL UI ==
- API (doc 08 Stage 2): GET /api/tasks/:id/diff, POST /api/tasks/:id/approve (→ completed, diff preserved for human merge — the system NEVER merges), POST /api/tasks/:id/reject { feedback } (→ agent can be re-triggered with feedback appended).
- UI: Task Detail gets a Diff tab (unified view, syntax highlighted, per-file), Approve/Reject buttons with confirm, files_touched list, retry counter, and the policy-denial events visible in the timeline.

== STEP 5: TESTS ==
- SECURITY TESTS (doc 20 — critical): in a test environment, run a real agent (or the hook directly with simulated calls — both) attempting to: write to .env, write to ../outside-worktree, run rm -rf, run git push. Assert every single one is DENIED and logged. Any pass-through = phase fails.
- Worktree tests: create/diff/preserve/teardown lifecycle; two tasks get fully isolated worktrees.
- Self-correction test: seed a task whose first implementation will fail typecheck (use a fixture target repo in tests/fixtures/demo-repo with intentional trap); verify the loop retries, fixes, and lands ready_for_review; verify a hopeless task blocks at exactly 3 retries with logs.
- Regression: ALL Phase 1 tests still pass unchanged.
- E2E: submit task → plan → start coding → diff appears → approve → completed.

== STEP 6: END-OF-SESSION PROTOCOL ==
Full suite (Phase 1 + 2), docs/reports/PHASE_2_TEST_REPORT.md with real output, update project.md, commit on stage-2/safe-code-proposal, ✅ GREEN FLAG only if everything passed — including every security test.
```

---
---

# 📋 PROMPT 3 (DAY 3) — Repository Intelligence + Planning Subsystem (PM → Architect → Decomposer)

```
Read CLAUDE.md and project.md. Run the full existing test suite first; fix any red before starting. Today = phase.md PHASE 3, per docs 10 (Repository Intelligence), 11 (short-term memory), 09 (Stage 3 tables), 15 (Stage 3 UI).

== STEP 0: RESEARCH ==
1. /repos/continue — study: embedding pipeline, retrieval/context assembly strategy. Notes → docs/research/continue-notes.md.
2. /repos/aider — re-read its repo-map approach for how it ranks relevant files.
3. /repos/langgraph — study: StateGraph, Postgres checkpointer, interrupt() for human-in-the-loop. Then verify against the INSTALLED @langchain/langgraph TypeScript package types — code against real installed APIs only.
4. `npm view` and pin: @langchain/langgraph, @langchain/langgraph-checkpoint-postgres, tree-sitter (or web-tree-sitter) + tree-sitter-typescript, and the embeddings approach: use pgvector + an embedding model available to us — verify what embedding API we have access to; if only Anthropic API is available, implement embeddings behind an EmbeddingProvider interface (config-driven provider + model name, e.g. VoyageAI or OpenAI embeddings via env) so NOTHING is hardcoded and the provider is swappable. Document the choice in an ADR.

== STEP 1: REPOSITORY INTELLIGENCE SERVICE (packages/repo-tools, exposed as MCP server) ==
Per doc 10, built as a standalone service:
- Scanner: walks TARGET_REPO_PATH, respects .gitignore, identifies files/languages.
- AST parsing with Tree-sitter (TypeScript/TSX/JS at minimum): extract functions, classes, interfaces, types + signatures.
- Import/Dependency Graph (file → files it imports), Symbol Graph (symbol → defined-at, referenced-at), Call Graph (function → callees, cross-file, best-effort via AST — document known limits honestly, no fake precision).
- Storage: graph tables in Postgres (new migration — design them, keep simple: files, symbols, edges tables with type discriminators). Incremental re-index: only changed files (mtime/hash) re-parsed; full re-index command available.
- pgvector: enable extension (migration per doc 09 Stage 3 embeddings table), embed per-file summaries (generated with MODEL_ROUTER — cheap model) + docs; semantic search function.
- Expose as a real MCP server (stdio) with tools: query_dependencies(file), query_symbol(name), query_call_graph(fn), search_semantic(query), get_file_summary(path). Register it in agent-runtime so agents can call it. Verify the MCP server actually starts and responds — integration test it.

== STEP 2: CONTEXT BUILDER + CONTEXT CACHE ==
- buildContext(taskDescription) → { relevantFiles[], dependencies[], summary } by combining graph queries + semantic search, ranked, token-budgeted (budget from config).
- Context Cache: per-task cache table; second request for same task returns cached context (this is a Phase 4 cost-saver, built now).

== STEP 3: PLANNING SUBSYSTEM (LangGraph) ==
- StateGraph with typed shared state (Zod), Postgres checkpointing (crashes resume, not restart — test this).
- Nodes, each a REAL agent run with its own role file + Zod output schema:
  1. PM Agent (roles/pm.md): task → goals, constraints, acceptance criteria.
  2. Architect Agent (roles/architect.md): PM output + buildContext() → impacted files (from the REAL graph), risks, technical approach, risk level low/medium/high.
  3. Task Decomposer (roles/decomposer.md): → typed subtasks [{type: backend|frontend|test|docs, title, description, dependsOn}].
- After Decomposer: LangGraph interrupt() → human-in-the-loop. Pipeline pauses; dashboard shows full plan + subtasks with an Approve Plan / Reject button; approval resumes the graph (Phase 4 will consume subtasks; for now approval marks plan approved and hands off to the existing single Coder flow for the first subtask, keeping the system end-to-end usable).
- New DB: subtasks table (migration) linked to dev_tasks.
- Replace the Phase 1 single-planner path with this pipeline for new tasks (keep old code path behind a config flag PIPELINE_MODE=simple|full for safe rollback — flag, not hardcode).

== STEP 4: DASHBOARD (doc 15 Stage 3) ==
Task Detail → Pipeline view: PM output, Architect output, subtask breakdown — each stage inspectable, approval checkpoint visible and actionable.

== STEP 5: TESTS ==
- Graph correctness tests against tests/fixtures/demo-repo (extend the fixture with known imports/calls): assert query_dependencies and query_symbol return EXACTLY the known-true edges. This is the anti-guessing gate (doc 10 definition of done).
- Incremental index test: touch one file → only it re-parses.
- Context Builder test: for a fixture task ("add endpoint to X"), relevantFiles must include the known-correct files and must not include noise beyond budget.
- LangGraph tests: full pipeline run on a real task; checkpoint/resume test (kill mid-run, resume, completes); interrupt/approve/reject flows.
- Agent evals: 5 real tasks through PM→Architect→Decomposer; assert architect's impacted files all exist and overlap ≥80% with hand-labeled expected files for the fixture tasks.
- Regression: ALL Phase 1+2 tests pass.

== STEP 6: END-OF-SESSION PROTOCOL ==
Full suite, docs/reports/PHASE_3_TEST_REPORT.md, update project.md, commit stage-3/repo-intelligence, ✅ GREEN FLAG only on full pass.
```

---
---

# 📋 PROMPT 4 (DAY 4) — Specialist Agents + QA Loop + Event Bus + Artifact Store

```
Read CLAUDE.md and project.md. Full regression suite first — fix red before building. Today = phase.md PHASE 4, per docs 06 (SDK spec), 07 (tool matrix), 12 (Event Bus), 09 (Stage 4 tables), 15 (Stage 4 UI).

== STEP 0: RESEARCH ==
1. /repos/roo-code — study: how modes separate Architect/Code/Review/Debug responsibilities. Notes → docs/research/roo-notes.md.
2. /repos/autogen — study: agent messaging/delegation patterns (concepts for our Event Bus). Notes → docs/research/autogen-notes.md.
3. Verify Agent SDK subagent/skills features against installed types before using them.

== STEP 1: SHARED AGENT BASE TEMPLATE (packages/agent-runtime) ==
Per doc 06: one base that every role extends — standard safety preamble, standard logging (every tool call → task_logs), standard error handling (unrecoverable → failed with full context), heartbeat writer, token/cost tracking, Zod output validation. Role files:
- roles/backend-dev.md — tools: Read/Glob/Grep/Edit/Write (worktree only) + Bash (allowlisted checks only)
- roles/frontend-dev.md — same scope, frontend focus
- roles/qa.md — Read + Bash (test/build commands ONLY, no Edit/Write — structurally absent from its tool list)
- roles/reviewer.md — Read ONLY. Outputs structured findings [{severity: blocking|non-blocking|suggestion, file, line?, finding, recommendation}] (Zod).
Tool scoping must match doc 07's matrix EXACTLY — enforced by the tools passed to query(), not by prompt text.

== STEP 2: EVENT BUS (packages/event-bus) ==
Per doc 12: Postgres LISTEN/NOTIFY transport + events table persistence (migration per doc 09). Event types exactly as doc 12's table (task.created, task.planned, architecture.ready, subtask.assigned, qa.passed, qa.failed, review.completed, task.blocked...). Typed publish/subscribe API (Zod payload schemas per event type). Consumer failure → retry 3x with backoff → failed_events table (migration). Ordering guaranteed per task_id stream. Replay: on consumer restart, process unhandled events for its subscriptions (query events > last_processed). Agents now communicate ONLY via events — remove any direct agent→agent calls.

== STEP 3: ARTIFACT STORE ==
artifacts table (doc 09 Stage 4 migration) + storage adapter interface (local disk now, S3-compatible via env later — adapter pattern, zero hardcoded paths). Every pipeline step writes versioned artifacts: plan, patch/diff, test_results, review_findings. API: GET /api/tasks/:id/artifacts, GET /api/artifacts/:id (doc 08 Stage 4).

== STEP 4: DISPATCH + FULL PIPELINE ==
- On plan approval (Phase 3 interrupt resume): Decomposer's subtasks emit subtask.assigned events. Dispatcher routes by subtask type → correct specialist agent, each in its own isolated worktree (per-task worktree shared across that task's subtasks; document the isolation model).
- Flow per doc 12: dev agent finishes → QA Agent runs checks in the worktree → qa.passed → Reviewer runs → review.completed with findings artifact → if no blocking findings → task ready_for_review (human diff approval, Phase 2 UI). qa.failed → event back to originating dev agent → fix loop, cap 3 → task.blocked.
- Reviewer blocking findings → back to dev agent with findings as feedback (counts toward the same retry cap).
- Skills: create .claude/skills/ (or SDK-equivalent) with at least one real reusable skill (e.g. "safe-db-migration") loaded by backend agents on demand — verify the mechanism against installed SDK docs first.

== STEP 5: DASHBOARD (doc 15 Stage 4) ==
Full pipeline view per task: PM → Architect → Decomposer → Dev → QA → Review with live status per stage (event-driven refresh via polling), every artifact inspectable + downloadable.

== STEP 6: TESTS ==
- Tool-scoping tests: attempt Edit as QA agent and as Reviewer → structurally impossible/denied; verify per role against doc 07 matrix.
- Event bus tests: publish/subscribe roundtrip, per-task ordering, retry→failed_events, replay after simulated consumer crash.
- Full pipeline integration test on fixture repo: one medium backend task flows subtask→dev→QA→review→ready_for_review with ZERO manual intervention (doc 03 Stage 4 definition of done). Also the failure path: seeded broken change → qa.failed → fix → pass; and hopeless change → blocked at 3.
- Artifact tests: every stage produced its versioned artifact; download works.
- Regression: ALL previous phases' tests pass.

== STEP 7: END-OF-SESSION PROTOCOL ==
Full suite, docs/reports/PHASE_4_TEST_REPORT.md, project.md update, commit stage-4/specialist-agents, ✅ GREEN FLAG only on full pass.
```

---
---

# 📋 PROMPT 5 (DAY 5) — Manager Agent + Epics + Cost Controller + Policy Engine v2 + RBAC

```
Read CLAUDE.md and project.md. Full regression first. Today = phase.md PHASE 5, per docs 13 (Policy v2), 14 (cost-aware scheduling), 08 (Stage 5 API), 15 (Stage 5 UI), 17 (RBAC), 09 (Stage 5 tables).

== STEP 1: EPICS + MANAGER AGENT ==
- Migrations: epics table + epic_id FK on dev_tasks (doc 09 Stage 5).
- Manager Agent = LangGraph supervisor node above the Phase 3–4 pipeline. Role file roles/manager.md (model from config; Manager does routing/tracking — use the cheap tier where reasoning allows). It: creates an epic from a high-level goal → runs PM/Architect/Decomposer → tracks all child subtask statuses in real time via Event Bus subscriptions → auto-retries failed subtasks → if ≥2 subtasks fail repeatedly, halts the epic and emits epic.halted (add event type) → when all subtasks complete, assembles ONE batched approval package (all diffs, QA results, review findings).
- API (doc 08 Stage 5): POST /epics, GET /epics/:id, POST /epics/:id/approve, plus /reject.

== STEP 2: COST CONTROLLER ==
- Before execution: estimate tokens/dollars/runtime from subtask count+complexity, refined by historical averages from agent_runs token data (Phase 2 built this — query it, no magic numbers; initial coefficients in config).
- Epics above COST_APPROVAL_THRESHOLD (config) require explicit human approval BEFORE agents start (blocking gate in the graph, another interrupt()).
- Estimate vs actual tracked on the epic and shown in UI. Model pricing per 1M tokens lives in a config table/env — never hardcoded — so price changes are a config update.

== STEP 3: POLICY ENGINE v2 ==
- Migration: policies table per doc 13. Loader + matcher (glob trigger_pattern → required_approval_role, blocking flag). Manager + Architect check it at pipeline gates; PreToolUse v1 denylist stays as the hard floor (v2 adds approval rules on top, it does not replace v1).
- Seed the doc 13 worked examples as rows: **/migrations/** → human, blocking; api/customer/** → architect, blocking; auth/** → security review (flag-only until a Security role exists). Adding a rule = DB insert. Risk-level rule: architect-tagged high risk → human plan approval always required.
- Approvals recorded in a policy_approvals table (who, when, rule, decision) — auditable.

== STEP 4: RBAC (doc 17) ==
- Roles: viewer (default) and approver. Auth via Supabase Auth session (but role stored in our own table to stay non-locked-in). ALL approve/reject endpoints (task, epic, policy) enforce approver at the API layer — return 403 otherwise. UI hides buttons for viewers but the SERVER is the enforcement point.

== STEP 5: DEVOPS AGENT (read-only) ==
roles/devops.md: Read + Bash limited to read-only health checks (git status, build status, disk usage of worktrees dir — allowlist in config). NO deploy capability, no credentials — assert this in tests.

== STEP 6: EPIC APPROVAL UI (doc 15 Stage 5) ==
Top-level Epics page: list + detail showing all subtasks, all diffs, all QA results, all review findings, cost estimate vs actual, single Approve/Reject for the whole epic. Halted epics clearly flagged with reason.

== STEP 7: TESTS ==
- Manager integration: goal → epic → subtasks → batched approval package (fixture repo). Halt path: force 2 subtasks to fail repeatedly → epic halts, human notified via task.blocked/epic.halted events.
- Cost tests: estimate produced before execution; over-threshold epic blocks until approved; estimate/actual recorded.
- Policy v2 tests: a subtask touching **/migrations/** blocks until human approval row exists; api/customer/** requires architect sign-off before dispatch; rule added via DB insert takes effect with no code change (test proves this).
- RBAC tests: viewer hitting every approval endpoint → 403; approver → 200.
- Regression: ALL previous phases pass.

== STEP 8: END-OF-SESSION PROTOCOL ==
Full suite, docs/reports/PHASE_5_TEST_REPORT.md, project.md, commit stage-5/manager-and-cost, ✅ GREEN FLAG only on full pass.
```

---
---

# 📋 PROMPT 6 (DAY 6) — Research Agent + Documentation Agent + Agent Registry + Engineering Memory

```
Read CLAUDE.md and project.md. Full regression first. Today = phase.md PHASE 6, per docs 06 (Registry), 11 (Engineering Memory), 07 (tool additions), 08 (Stage 6 API), 15 (Stage 6 UI).

== STEP 0: RESEARCH ==
/repos/composio — study: tool/capability registration and integration architecture concepts. Notes → docs/research/composio-notes.md. Verify any GitHub MCP / web-search MCP server we plan to use actually exists and works (test-connect it) before wiring — no imaginary MCP servers.

== STEP 1: AGENT REGISTRY ==
- Migration: agents table per doc 06/09. Seed rows for every existing role (planner, pm, architect, decomposer, backend, frontend, qa, reviewer, devops, manager) with accurate capability tags (git, sql, docker, browser, docs...), tool lists, prompt_ref (path to role file), version.
- Metrics pipeline: success_rate and avg_retries computed from agent_runs + task outcomes (scheduled recompute or on-write update — pick, document). 
- Dispatcher refactor: Manager/dispatch selects agents by CAPABILITY TAG query against the registry, not hardcoded role names (doc 14). Adding a new agent = insert + role file, zero dispatcher code change — prove with a test.
- API: GET /agents, GET /agents/:id/metrics (doc 08 Stage 6). Dashboard: Agent Registry page (doc 15 Stage 6).

== STEP 2: RESEARCH AGENT ==
- roles/research.md — tools: web search + GitHub read via MCP (whichever verified in Step 0), Read. NO Edit/Write/Bash. Zod output: { findings, relevantLibraries, recommendedApproach, risks }.
- Inserted as optional FIRST pipeline step (config flag RESEARCH_ENABLED + per-epic toggle): Research → PM → Architect → Decomposer. Its output artifact feeds PM/Architect context.

== STEP 3: DOCUMENTATION AGENT ==
- roles/docs.md — Edit/Write scoped by a Policy rule to *.md and docs/** ONLY (enforce in PreToolUse: any non-.md write by this role = deny). Triggered by epic approval event: updates README/project docs/changelog entries in the worktree as a final reviewable artifact (still goes through the human diff approval — no direct writes to main, ever).

== STEP 4: ENGINEERING MEMORY v1 (doc 11) ==
- On task completion/blocked: embed { problem, plan, patch summary, outcome, errors, fixes } → pgvector (source_type: past_task).
- Architect Agent + Context Builder now ALSO query Engineering Memory: "similar past tasks" section (top-k with similarity threshold from config) appended to architect context — including what failed before and why.
- Learning Signal: a simple report view/query listing prompt/tool combos correlated with retries/failures — surfaced for HUMAN review only, never auto-applied (doc 11).

== STEP 5: TESTS ==
- Registry tests: metrics math correct against seeded agent_runs; capability-tag dispatch selects the right agent; new fake agent added via insert gets dispatched with zero dispatcher change.
- Research agent eval: real run on a real question; output validates; sources/URLs in findings are real (fetchable).
- Documentation agent security test: attempt to write a .ts file as docs role → denied by policy; .md write in worktree → allowed.
- Memory tests: complete a task → embedding row exists; a similar new task's architect context contains the past-task reference (fixture-controlled similarity).
- Regression: ALL previous phases pass. Full pipeline E2E now: Research → PM → Architect → Decomposer → Dev → QA → Review → Docs → batched approval.

== STEP 6: END-OF-SESSION PROTOCOL ==
Full suite, docs/reports/PHASE_6_TEST_REPORT.md, project.md, commit stage-6/registry-memory, ✅ GREEN FLAG only on full pass.
```

---
---

# 📋 PROMPT 7 (DAY 7) — Parallel Execution at Scale + Executive Agent + Productivity Dashboard

```
Read CLAUDE.md and project.md. Full regression first. Today = phase.md PHASE 7, per docs 14 (concurrency), 12 (bus scaling note), 08 (Stage 7 API), 15 (Stage 7 UI), 18.

== STEP 1: EXECUTIVE AGENT ==
- roles/executive.md — the single top-level entry point. Model: cheap tier for routing + summary language (config). Accepts a plain-language goal from ANY stakeholder → decides whether it maps to one or multiple epics → creates them → hands to Manager Agent → reports progress in plain business language (no engineering jargon in its summaries).
- API: POST /goals, GET /goals/:id (plain-language progress + results). Migration: goals table (goal_id, text, status, epic_ids[], summary, timestamps).
- AGENT ROUTING: the Executive/Manager routing decisions (which epics, which capability tags, which agents) must be REASONED decisions logged with their rationale to task_logs — auditable routing, not a black box.

== STEP 2: CONCURRENCY INFRASTRUCTURE ==
- Per-epic worktree namespacing: WORKTREES_DIR/<epicId>/<taskId> — concurrent epics can never collide on paths. File-conflict guard: before dispatch, Manager checks Architect's impacted-files lists across ACTIVE epics; overlap → the later epic's conflicting subtask queues behind the earlier one (log the decision).
- Concurrency caps (ALL config, not hardcoded): MAX_CONCURRENT_EPICS (default 10), MAX_CONCURRENT_AGENT_RUNS, per-epic MAX_CONCURRENT_SUBTASKS. Enforced by the scheduler before dispatch.
- Queue backend: implement a QueueAdapter interface with two adapters — Inngest (current) and BullMQ+Redis — selected by QUEUE_BACKEND env (docs 18/14: migrate only when throughput demands; the adapter makes it a config flip). BullMQ adapter fully implemented + tested against a real Redis (docker in tests). Same for the Event Bus: keep Postgres LISTEN/NOTIFY as default, add a Redis Streams adapter behind EVENT_BUS_BACKEND — both pass the same test suite (adapter contract tests).
- Global Anthropic API rate limiting + exponential backoff with jitter in one place (agent-runtime), respecting API rate-limit responses — no per-agent ad hoc retry storms.

== STEP 3: TOKEN/COST OPTIMIZATION PASS (multi-agent scale) ==
Apply and verify across the whole system: prompt caching enabled on every system prompt + repeated context blocks; Context Cache hit-rate measured and shown; model tiering audit (every role's model comes from config and matches the tier policy in CLAUDE.md); artifact-reference pattern (agents receive artifact IDs + summaries, and fetch full content only when needed — never paste full prior outputs into every prompt); context budgets enforced by Context Builder. Add a per-epic and per-agent-type cost breakdown to the metrics.

== STEP 4: PRODUCTIVITY DASHBOARD + DAILY BATCH REVIEW (doc 15 Stage 7) ==
Metrics page: tasks completed, avg time per pipeline stage, failure rate by agent type/version, cost per epic/agent-type — pulled from Agent Registry + agent_runs. Daily Batch Review queue: all epics in ready-for-approval, reviewed together; batch approve individually from one screen.

== STEP 5: TESTS ==
- Concurrency test: 5 concurrent epics on fixture repos → zero worktree collisions, caps respected (attempt 12 with cap 10 → 2 queue), file-conflict guard test (two epics touching same file → serialized).
- Adapter contract tests: identical suite passes against Inngest-mode and BullMQ-mode; Postgres bus and Redis Streams bus.
- Executive E2E: plain-language goal → epic(s) → full pipeline → plain-language progress from GET /goals/:id readable by a non-engineer (assert no stack traces/jargon in summary).
- Load smoke: 20 tasks queued rapidly → system remains responsive, no event loss (count events in vs processed).
- Regression: EVERYTHING from Phases 1–6 passes.

== STEP 6: END-OF-SESSION PROTOCOL ==
Full suite, docs/reports/PHASE_7_TEST_REPORT.md, project.md marked "ALL 7 PHASES BUILT — pending final audit (Prompt 8)", commit stage-7/scale-executive, ✅ GREEN FLAG only on full pass.
```

---
---

# 📋 PROMPT 8 (DAY 8) — FULL SYSTEM LIVE AUDIT (no new features — real-time verification of everything)

```
Read CLAUDE.md and project.md. Today you build NOTHING new. You are the auditor. You will verify the ENTIRE system phase by phase, LIVE — by actually running it, not only by running test files. Produce docs/reports/FINAL_AUDIT_REPORT.md as you go, with real command output pasted for every check. Be brutally honest: your job is to FIND problems, not to certify. A false green flag here is the worst possible outcome.

== PART A: STATIC FULL-CODEBASE SWEEP ==
1. Clean install from scratch: rm -rf node_modules everywhere → fresh install → turbo typecheck, lint, build. Zero errors, zero warnings treated as acceptable-by-default (list and justify any remaining warning).
2. Import audit: find unused imports/exports/dead files, circular dependencies (use madge or ts-prune — verify tool exists first), missing dependencies (imported but not in package.json). Fix all.
3. HARDCODING HUNT: grep the entire codebase for hardcoded secrets, API keys, model name strings, URLs, ports, absolute paths, magic numbers for retries/limits/thresholds/prices outside shared-config and DB config. Every hit = fix (move to config) or documented justification. .env.example must cover every env var actually read — cross-check by grepping process.env usage.
4. HALLUCINATION HUNT: for every external API call surface (Agent SDK, LangGraph, Inngest, BullMQ, Supabase, MCP servers, tree-sitter), open the installed package types and verify every call site matches the REAL API. Any invented option/method = fix.
5. INFINITE LOOP / RUNAWAY audit: inspect every loop, retry, recursion, event handler, and agent loop. Verify: every retry has a cap from config; every agent run has maxTurns; every queue consumer is idempotent (event re-delivery can't double-execute); every LISTEN/NOTIFY + poll loop has backoff; a qa.failed↔fix cycle cannot ping-pong past the cap; the Manager can't re-dispatch a blocked subtask. Write down each guard's file+line as proof.
6. Simplicity/durability review: flag over-clever code, god-files >400 lines, duplicated logic → refactor the worst offenders. Error handling audit: no empty catch blocks, no swallowed promise rejections; process-level unhandledRejection/uncaughtException handlers report to Sentry.

== PART B: LIVE PHASE-BY-PHASE VERIFICATION (real runs, real DB, real agents) ==
Start the full stack (fresh DB via migrations from zero — this itself proves migrations are complete). Then, LIVE:
- PHASE 1: create a real task via the API and via the UI → real Planner runs → verify plan in DB references only real files → logs timeline complete → heartbeat rows written.
- PHASE 2: take it to coding → verify worktree created and isolated → LIVE ATTACK: instruct a test agent (in the test env) to write .env, escape the worktree, run rm -rf, run git push → verify all four DENIED and logged → verify self-fix loop on a seeded failure → verify block at exactly 3 retries → approve a diff → verify NOTHING merged automatically.
- PHASE 3: verify MCP repo-intelligence server answers live queries correctly against known fixture truth → kill the LangGraph run mid-pipeline → restart → verify it RESUMES from checkpoint → approve at interrupt.
- PHASE 4: full multi-agent run: watch events flow in the events table in order → verify QA agent structurally cannot edit → verify reviewer findings artifact → verify all artifacts versioned + downloadable.
- PHASE 5: submit an over-threshold epic → verify it BLOCKS for cost approval → verify a migrations/** subtask blocks for human policy approval → verify viewer gets 403 on every approve endpoint → verify epic halt on 2 repeated failures.
- PHASE 6: verify registry metrics match a hand-computed value from agent_runs → add a dummy agent via DB insert and see it dispatched with no code change → verify docs agent denied on .ts write → verify a completed task appears in Engineering Memory and influences a similar next task's context.
- PHASE 7: run 3+ concurrent epics live → no collisions, caps enforced → flip QUEUE_BACKEND and EVENT_BUS_BACKEND to the Redis adapters and re-run a full pipeline → same behavior → submit a plain-language goal as a "non-technical user" and read the plain-language status back.

== PART C: PRODUCT-GRADE QUESTIONS (answer each with evidence, not opinion) ==
1. MULTI-CLIENT READY? Can this handle multiple concurrent human users + concurrent epics without data races? Check: DB transactions on status transitions, idempotent consumers, no shared mutable in-process state that breaks under 2 web instances. If any gap → fix or document as a known limit with the trigger to fix.
2. SELLABLE? What separates this from sellable SaaS: list concretely (multi-tenancy/org_id scoping, billing, onboarding, per-tenant secrets, SLAs). Don't build them — write docs/SELLABILITY_GAP.md honestly.
3. EXTENSIBLE TO ANY DEPARTMENT? Prove ADR-009's claim: write docs/ADD_A_NEW_AGENT.md — the exact minimal steps (role file + registry insert + capability tags + 3 eval tasks) and verify by actually adding a trivial "changelog-writer" agent end-to-end using only those steps.
4. TOKEN EFFICIENCY? Report measured cost per pipeline run, cache hit rates, cost by model tier. Identify the single biggest token waster and fix it.
5. AGENT ROUTING QUALITY? Pull 5 real routing decisions from logs — was each rationale sound? Any misroutes → fix dispatch logic or capability tags.
6. 0 HALLUCINATION IN AGENT OUTPUTS? Re-run the full agent eval suite (all phases' evals). Report plan-accuracy/file-accuracy rates. Any plan referencing a nonexistent file = failure to fix.

== PART D: FINAL DELIVERABLES ==
1. docs/reports/FINAL_AUDIT_REPORT.md — every check above with real output, every issue found, every fix applied, remaining known limitations stated honestly.
2. Updated project.md — final state: all phases, all green, audit date, how to run everything from zero (one section a new engineer can follow), known limits.
3. README.md for the repo — production runbook quality.
4. Final commit + tag v1.0.0.
5. Verdict: "✅ GREEN FLAG — SYSTEM PRODUCTION-READY (with stated known limits)" ONLY if Parts A–C are genuinely clean. Otherwise list exactly what remains, ranked by severity, so the next session fixes them.
```

---
---

# 🔑 QUICK REFERENCE — FINAL TECHNOLOGY DECISIONS (verified current, June 2026)

| Concern | Choice | Why (verified) |
|---|---|---|
| Agent engine | **Claude Agent SDK (TypeScript)** `@anthropic-ai/claude-agent-sdk` | Same production-tested harness as Claude Code: built-in tools, hooks (PreToolUse = your Policy Engine enforcement point), permission scoping, subagents, MCP. Fastest-growing Anthropic-native framework in 2026. |
| Orchestration | **LangGraph.js** | The standard 2026 production pattern: LangGraph as workflow skeleton (checkpoints, interrupt() for human approval, resume-after-crash), Agent SDK doing the work inside nodes. |
| Models (tiering) | Haiku = router/summary · Sonnet = coding/QA/review/architect · Opus behind env flag | Model tiering cuts multi-agent cost 40–60%. All names in config — never hardcoded. |
| Tools/data | **MCP** everywhere; custom MCP server only for Repository Intelligence | Industry-converged standard; hundreds of servers exist. |
| Database | **PostgreSQL (Supabase-hosted, zero lock-in features)** + **pgvector** | Per your ADR-005/006 — still the right call. Qdrant only if measured need (Phase 7+). |
| Repo intelligence | **Tree-sitter** AST → graph tables + pgvector semantic search, exposed over MCP | Aider/Continue-inspired concepts, original implementation. |
| Jobs | **Inngest → BullMQ+Redis** behind a QueueAdapter (config flip) | Your ADR-007, made switchable instead of a rewrite. |
| Event bus | **Postgres LISTEN/NOTIFY → Redis Streams** behind an adapter | Your doc 12, made switchable. |
| Frontend/API | **Next.js App Router + TypeScript + Tailwind + TanStack Query** | Current mainstream production stack. |
| Validation | **Zod on every agent output + every API body + env config** | Your #1 anti-hallucination weapon in code. |
| Testing | **Vitest + Playwright + agent eval suite** | Agent evals are the part normal testing misses — built into every prompt. |
| Observability | **task_logs (audit) + Sentry + heartbeats** | Right-sized per your doc 16. |
| Monorepo | **Turborepo** | Clean package extraction boundaries for future departments. |

## /repos → which reference feeds which phase
| Repo | Used in Prompt | Take (concepts only) |
|---|---|---|
| OpenHands | 1 | Agent lifecycle, run state model |
| SWE-agent | 1, 2 | Plan step, trajectory logging, retry/debug loop |
| Aider | 2, 3 | Repo map, diff/patch strategy, git workflow |
| Cline | 2 | Plan/Act split, approval workflow |
| Continue | 3 | Embedding pipeline, context assembly |
| LangGraph | 3 | Checkpoints, interrupts, durable state |
| Roo Code | 4 | Role/mode separation |
| AutoGen | 4 | Delegation & messaging concepts |
| Composio | 6 | Tool/capability registration |
| OpenCode | any | Terminal/session handling if needed |

**Never copy code from any of them — concepts only. Everything Gridiron ships is original (your Reference Matrix rule, and it also keeps the IP sellable).**

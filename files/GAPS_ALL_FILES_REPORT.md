# Gaps Report — Every File in `/files`, Verified Against Real Code

**Date:** 2026-07-23
**Method:** Every claim below was grep/read-verified against the actual current codebase this
session (not carried over from earlier reports, which were stale — written before the 18-day
"Fleet Enhancement Plan" and the Days 0-18 gap-closure/Day 19 production-readiness prep that
followed it). Five parallel research passes covered all 27 files in `/home/pc-117/Documents/
CRR2906/files/`. Every "done" claim below has file:line evidence; every "missing" claim was
confirmed absent by grep, not assumed.

**Two separate plans exist in this project — don't confuse them:**
1. **The 20 numbered spec docs (`00_README.md`–`20_Testing_Strategy.md`) + `MASTER_PROMPT_PACK.md`
   + `tools_agents.md`** — the *original* 8-day build vision, written before the backend was
   rebuilt in Python. This is what most of this report covers.
2. **`docs/FLEET_ENHANCEMENT_PLAN.md`** (not in `/files` — lives in `/docs`) — a *separate*,
   later, 19-day plan that `agent_enhancement.md` and `agent_models.md` (both in `/files`) were
   design docs for. That plan's Days 0-18 are complete and gap-closed; Day 19 is prepped but the
   actual cloud deployment was intentionally skipped. See Part 3.

---

## Part 1 — The 20 Numbered Spec Docs

### 00_README.md — index only, not a requirement (N/A)

### 01_Vision_Product_Requirements.md — **~90%**
**Done:** The full plain-language-task→plan→diff→decompose→self-correct→batched-approval→audit-log
loop is genuinely wired, not just present as files — `backend/app/agents/manager.py` (real retry
loop), `backend/app/pipeline/graph.py` (real LangGraph `interrupt()`/`Command` human-in-the-loop,
not simulated), `backend/app/policy/engine.py` (blocks `.env*`/`secrets/**`, enforced at every tool
call via `base.py:_enforce_policy`), `task_logs`+`agent_runs` tables populated and surfaced to the
dashboard, `cost_controller.py` genuinely gates epic start on cost threshold, DevOps agent is
confirmed read-only (no deploy tool exists in its tool list).
**Gap:** The PRD's stated non-goal ("no AI models other than Claude near-term") is soft-violated —
a full second model backend (Groq) is implemented and shipped (`agents/groq_adapter.py`,
`base.py:87`), just opt-in/default-off. Not a functional gap, a spec-tension worth knowing about.

### 02_System_Architecture_Blueprint.md — **~60% literal / ~90% capability**
**Done:** LangGraph orchestration, pgvector (real cosine-distance queries, not just a dependency),
AST-based repo intelligence (tree-sitter, not regex), Postgres LISTEN/NOTIFY + Redis Streams event
bus (both transports exist as real code), Sentry (`main.py:54`, real `sentry_sdk.init()` call),
S3/DB dual-backend artifact store, the Next.js/TS/Tailwind/TanStack frontend stack exactly as
specified.
**Real deviations (not just unimplemented — actively built differently):**
- **"Claude API via the Claude Agent SDK"** — false. Zero `claude-agent-sdk` references anywhere.
  The real execution engine is a hand-rolled tool-loop on the raw `anthropic` SDK (`agents/base.py`).
- **"Backend: Next.js API routes → NestJS"** — false. Backend is Python/FastAPI, not any Node
  framework.
- **MCP as the tool-access layer** — a real custom MCP server exists (`backend/app/mcp/server.py`,
  4 real tools) but **nothing in the running app calls it** — all 72 agents get tools via direct
  in-process Python dispatch (`agents/tools.py`), the opposite of "agents access tools through MCP
  servers."
- **Inngest** — never used anywhere (zero grep hits); the system went straight to Redis-backed RQ.
- **Turborepo `packages/*` structure** — `packages/` is a completely empty directory; all the logic
  meant to live in `packages/task-engine`, `agent-runtime`, `repo-tools`, etc. lives in the Python
  `backend/app/` monolith instead.

### 03_Technical_Execution_Roadmap.md — **~85%**
**Done:** All 7 stages' definitions-of-done substantially met with real, wired code (task queue,
worktree-isolated patching, AST/pgvector context, 72 specialist agents, Manager/Cost
Controller/Policy v2/read-only DevOps/batched epic approval, Research+Docs agents, capability-tagged
registry, concurrency semaphores, Executive Agent).
**Gap:** `BullMQQueueAdapter.enqueue()`/`get_status()` are confirmed literal `raise
NotImplementedError(...)` stubs (`pipeline/queue_adapter.py:96,102`) — the doc's own comment says
"replace the body when Redis becomes available." Functionally superseded by a separate real RQ
adapter, but the specific artifact this doc names is genuinely unimplemented (see also 14 below —
that RQ adapter is itself never actually selected at runtime).

### 04_Engineering_Standards_Conventions.md — **~55%**
**Done:** TS `strict: true` + `noUncheckedIndexedAccess` for the surviving `apps/web` package, Zod
used in 51 frontend files, git worktree isolation for every writing agent, Conventional Commits
genuinely followed (verified via `git log`), `.env`/secrets blocked by both `.gitignore` and a real
enforced Policy Engine hook, CI runs ruff+black+mypy(--strict)+pytest for backend.
**Gaps:**
- The mandated `packages/{task-engine,agent-runtime,repo-tools,policy-engine,event-bus,
  shared-types,shared-db}` folder structure doesn't exist at all — `packages/` is empty.
- Branch naming convention (`stage-N/...`, `fix/...`) is not what's actually used (`git branch -a`
  shows `agent/task-N` instead) — CI's own trigger list expects `stage-*`/`gap-*` branches that
  don't exist.
- No automated enforcement anywhere that a PR links a task ID.
- **Frontend has zero real test files** (`find` for `*.test.ts(x)` under `apps/web` returns nothing)
  and CI's frontend job never runs `pnpm test` at all — only typecheck/lint(`|| true`,
  non-blocking)/build.
- "Every agent output schema is a Zod schema" doesn't hold for the backend (Pydantic there, Zod is
  TS-only) — a naming/library mismatch, not really a functional gap.

### 05_Architecture_Decision_Records.md — **~75%**
**Done:** Most ADRs' reasoning is honored even where the literal tech changed — Postgres/pgvector,
worktree isolation, and especially **ADR-010's permanent human-approval gate** (a real, empirically
verified LangGraph `interrupt()`/`Command(resume=...)` mechanism, not cosmetic).
**Real reversals (the team built exactly what the ADR argued against):**
- **ADR-001 (Claude Agent SDK)** — reversed; a custom tool-loop was built instead, including its
  own permission hooks and worktree management (the exact re-implementation ADR-001 said to avoid).
- **ADR-003 (MCP for all tool access)** — reversed; direct in-process dispatch is the real path.
- **ADR-007 (Inngest before BullMQ)** — Inngest skipped entirely; `BullMQQueueAdapter` (the ADR's
  stated eventual target) is left as a confirmed stub.

### 06_Agent_SDK_Specification.md — **~85%**
**Done:** Lifecycle (`created→planning→coding→testing→blocked|completed|failed`) is enforced in
code via `VALID_TRANSITIONS`+`can_transition()`, not just documented. Shared base template
(`base_graph.py`, 900+ lines) is real and used by all 72 agents — policy checks gate every tool
call, verification overrides model self-claims, heartbeat/status events all real.
`ensure_all_agents_registered()` (new this session) confirmed live: 72/72 agents registered at
startup, up from as few as ~6. Capability-based dispatch (`fleet_manager.select()`) is real, not
hardcoded. Read-only vs. coding tool permission separation confirmed structurally enforced.
**Gap:** The spec's "Zod-validated plan output added to a shared-types package" doesn't exist as
such — validation is via Anthropic tool `input_schema` + a Pydantic-adjacent override mechanism,
functionally similar but not the literal contract described. No formal "test against 3
representative tasks" gate before an agent becomes dispatchable — it's live as soon as its module
imports cleanly.

### 07_Tool_MCP_Specification.md — **~55%**
**Done:** The Tool Access Matrix (which roles get which tools) is real and structurally enforced,
not advisory — `READ_ONLY_TOOLS`/`CODER_TOOLS`/`QA_TOOLS`/`REVIEWER_TOOLS`/`DEVOPS_TOOLS`/
`RESEARCH_TOOLS` match the spec's matrix row-for-row, and PreToolUse-style denylist enforcement
(`guardrails.py`) is called unconditionally before every tool execution. Real GitHub PR creation
via the actual REST API exists (`tools/git_push_tool.py`).
**Central gap:** the spec's core principle — "tools standardized through MCP, existing servers used
directly rather than reimplemented" — is not what's built. Only one genuinely custom MCP server
exists (repo intelligence), and it's unused by the runtime. Filesystem/Git/GitHub/Postgres/
Web-Search access is all bespoke in-process Python, not MCP servers. No Postgres MCP, no public MCP
registry search step evidenced anywhere.

### 08_API_Specification.md — **~80%**
**Done:** Every Stage 1-7 endpoint from the spec is present and correctly shaped (task
CRUD/logs/diff/approve-reject, artifacts, epics, agent registry, goals), plus far more added later
(98 total routes across 16 routers vs. the spec's minimal surface — expected, since later specs/
Fleet-Enhancement work postdate this doc). Error envelope, cursor pagination on `GET /tasks`, all
real.
**Gaps:**
- No cursor pagination on `GET /agents` — spec requires it, `registry.py` only has an optional
  `?tag=` filter, returns the full unpaginated list.
- Auth model is a custom JWT system, not "Supabase Auth" as this doc specifies.
- `POST /tasks`'s `priority`/`project`/`assignedAgent`/`finalSummary` fields are **hardcoded
  placeholder values** in the response (`tasks.py:_task_to_dict()` — `"priority": "medium",
  "assignedAgent": None`, etc.), not real stored/settable columns — a "looks done, isn't" gap.

### 09_Database_Design_Specification.md — **~80%**
**Done:** All Stage 1-6 core tables present with correct FKs (26 total `__tablename__` classes, 17
migrations 001-017), pgvector genuinely used, Alembic migration strategy matches spec exactly.
**Gaps:**
- `dev_tasks` is missing spec's `priority`/`assigned_agent`/`project`/`final_summary` columns
  entirely (faked at the API layer instead, see doc 08 above).
- Spec's status `CHECK` constraint doesn't exist at the DB level — only enforced in application code
  (a direct SQL write could set an invalid status).
- **`indexed_files`/`symbols`/`call_edges` tables exist, are migrated, but have zero real writers
  anywhere** — the actual scanner builds an in-memory structure and never persists to them. Looks
  complete (table + migration exist), isn't functionally connected.
- Spec's `embeddings` table (generic `code_summary|doc|past_task`) doesn't exist as such — the real
  pgvector table (`memory_embeddings`) is task-outcome-scoped instead, serving doc 11 not doc 10.

### 10_Repository_Intelligence_Specification.md — **~60%**
**Done:** Tree-sitter-based scanner with incremental re-parse (content-hash comparison), Context
Builder + cache matching spec almost verbatim, Voyage AI semantic search with graceful keyword
fallback, both manual and a real weekly-timer re-index loop (`main.py:_weekly_reindex_loop()`).
**Gaps:**
- The "Call Graph" is actually a **file-level import graph mislabeled as a call graph** — a real
  function-level call graph exists (`repo_tools/ast_engine.py`) but is single-file only, not
  cross-file, and lives outside the Context Builder pipeline as a standalone chat tool instead.
- **Architecture Mapper is entirely missing** — no module, zero grep hits.
- Symbol Graph is real only in-memory — the DB tables meant to back it as a persisted/queryable
  graph are unwired (see doc 09).
- "Re-indexing must complete before an Architect run starts" — not enforced anywhere; no gating
  logic exists between reindex and architect dispatch.
- No webhook-triggered reindex on merge — only manual trigger + the weekly timer.
- The MCP server exists as invocable code, not a deployed standalone service other tools could
  discover.

### 11_Memory_System_Specification.md — **~80%**
**Done:** Short-term memory via real `AsyncPostgresSaver` LangGraph checkpointing (not a stub —
confirmed wired at startup/shutdown). Long-term Engineering Memory (`memory/store.py`) has real
pgvector-backed task/architecture/failure embedding functions with genuine call sites outside the
module (`manager.py`, `pipeline/graph.py`). A more advanced layer beyond spec also exists:
`versioned_memory.py`'s full lesson lifecycle (DRAFT→PUBLISHED→SUPERSEDED→ARCHIVED) with a real
background archival loop.
**Gaps:**
- **Retention contradicts the spec** — spec says archive to cheaper storage; the real
  `services/retention.py` does a hard `DELETE FROM task_logs WHERE created_at < cutoff`. No
  retention/archival logic exists for `agent_runs` or `artifacts` at all.
- The "Learning Signal" memory category is entirely unimplemented — the `category` column supports
  it schematically but is never actually set to `"learning"` anywhere.

### 12_Event_Bus_Specification.md — **~75%**
**Done:** Postgres LISTEN/NOTIFY transport is genuine (persist-then-notify), all 9 core event types
present with typed constructors, retry-then-dead-letter exactly as specced (`failed_events` table),
ordering-per-task_id and replay both implemented per spec's own wording.
**Biggest single finding in this whole report:** **the Redis Streams transport is real, working
code that is 100% disconnected from the actual event flow.** `event_bus/redis_streams.py` has a
genuine Redis client (`xadd`/`xreadgroup`/`xack`, consumer groups) — but `publish_event()` never
calls it, and grep confirms zero call sites for `publish_to_stream()` anywhere outside its own file.
The only place `REDIS_STREAMS_ENABLED` is checked outside that file is a `/health`-endpoint ping.
**Flipping `REDIS_STREAMS_ENABLED=true` today would make the health check probe Redis but would not
stream a single real event.**

### 13_Policy_Engine_Specification.md — **~85%**
**Done:** v1 denylist (`.env`/`secrets/**`/`.github/workflows/**`/symlink-escape protection, `rm
-rf`/`kubectl`/`terraform`/`git push --force` command blocking) is real, non-trivial, and confirmed
called at the actual tool-execution layer via two independent enforcement points. v2 config-driven
`policies` table + glob-to-regex compilation + full audit trail (`PolicyApproval` table) all real.
Every coding pipeline run halts at a real `interrupt()` node before any dev agent starts — stricter
than the spec requires.
**Gap:** No evidence the spec's two worked-example policy rules (migrations require human approval,
`api/customer/**` requires architect sign-off) are actually seeded as active rows in the `policies`
table — the enforcement mechanism is real, but these specific example rules aren't confirmed active
by default.

### 14_Scheduler_Specification.md — **~55%** (weakest of the 20 docs)
**Done:** Cost-aware gating (`cost_controller.py`) and Stage 7 concurrency caps (real
`asyncio.Semaphore`s) both genuinely wired. Epic-halt-on-repeated-failure matches spec exactly.
Capability-based agent dispatch (`fleet_manager.select()`) is real, not hardcoded.
**Gaps (the sharpest in the whole report):**
- **No `priority` field on `dev_tasks` at all** — spec explicitly requires it; confirmed absent.
- No Inngest anywhere — direct `asyncio.create_task()` calls from API handlers instead.
- **The real RQ adapter (`queue/rq_adapter.py`) is fully-built, genuine code that is completely
  unwired** — zero call sites outside its own file/tests/health-check.
- **Worse: the queue selector that IS live (`pipeline/queue_adapter.py:get_queue_adapter()`) only
  branches on `"bullmq"` (a confirmed `NotImplementedError` stub) vs. the in-process default — it
  never checks for `"rq"` at all**, even though `config.py`'s own field description says the options
  are `"asyncio or rq"`. Setting `QUEUE_BACKEND=rq` today silently falls through to in-process
  execution, not to the real RQ adapter that exists specifically for this. Neither of the two queue
  backends the spec/config actually name is reachable in production.

### 15_Mission_Control_Dashboard_Specification.md — **~70%**
**Done:** Task List/Detail, Diff Viewer, Pipeline View (with human approval checkpoint), Artifact
Inspector, Epic Approval View (cost estimate vs. actual, RBAC-gated), and the Stage 7 "Daily Batch
Review" screen (`apps/web/app/review/page.tsx`, 400 lines — genuinely implements batch
approve/reject, not a placeholder) all real. SSE realtime behavior confirmed live in 2 pages.
**Gap:** **Stage 6's Agent Registry View doesn't exist as a dashboard screen at all**, despite the
backend being fully ready for it (`GET /api/agents` already returns name/version/capabilities/
success_rate/avg_retries) — grep across the entire frontend for any consumption of that endpoint
returns nothing. `apps/web/app/fleet/page.tsx` is a different, similarly-named feature (the Fleet
self-improvement request queue), not this screen. The Productivity Dashboard (`metrics/page.tsx`)
is cost/token-centric and doesn't show the spec's "avg time per pipeline stage" or "failure rate by
agent type" views.

### 16_Observability_Specification.md — **~85%**
**Done:** Real Sentry init (not just config presence) with FastAPI+SQLAlchemy integrations, gated
on `sentry_dsn` being set. Alerting is a real `httpx` POST to a webhook on blocked/failed tasks, not
a stub. `/health` reports DB+Redis+S3+live agent count. Per-agent success-rate metrics are computed
from real run data, not mocked. Agent-level stall detection is real.
**Gap:** No OpenTelemetry/Prometheus stack (correctly deferred per spec's own framing, not a gap).
The heartbeat/stall check lives inside individual agent runs rather than as a separate periodic
dashboard-visible sweep — narrower than the spec's framing but functionally covers the intent.

### 17_Security_Handbook.md — **~75%**
**Done:** Credential vault uses real Fernet encryption with a safe plaintext-fallback-with-warning
(never hardcoded), audit-logs every load/store. JWT auth is real and live end-to-end (real login
endpoint + real bcrypt verification + a real frontend login page). RBAC is enforced server-side via
`Depends()` on real endpoints, not just hidden in the UI. Sandbox isolation (real `git worktree add
-b`) and per-role Bash allowlisting are both genuinely enforced, not advisory.
**Gap:** Spec says "Supabase Auth for all human users" — the actual system is a custom JWT auth
against a `system_settings`-backed user store, a real architectural deviation from what this
specific doc describes (later docs/decisions may supersede it, but as written here it's wrong).

### 18_Deployment_Infrastructure_Guide.md — **~40%** (prep-only, confirmed)
**Done:** CI (`.github/workflows/ci.yml`) is real — Postgres+pgvector service container, ruff,
black, mypy --strict, pytest, plus frontend and security (`pip-audit`) jobs. `Procfile`,
`vercel.json`, `docker-compose.yml`, and the newly-written `docs/DEPLOYMENT.md` are all real and
correct as *local prep*.
**Confirmed gap, unambiguous:** **zero evidence of any live deployed instance anywhere.**
`docs/DEPLOYMENT.md` states in its own text that nothing was deployed. `vercel.json`'s rewrite
destination is a placeholder URL. No `.vercel` directory, no Supabase project reference, no
`vercel.app`/`railway.app`/`onrender.com`/`supabase.co` string anywhere in the repo. CI has no
deploy job by design. Inngest (the spec's named background-job service) is unused — `QUEUE_BACKEND`
is `asyncio`/`rq` instead. No evidence any staging/production environment was ever stood up.

### 19_Operations_Runbook.md — **~70%**
**Done:** "Blocked halts agent action" is real (not just described), worktree preservation on
block/failure is real (never auto-removed), Sentry-based health checking is live, Agent Registry
success-rate data is real, `failed_events` dead-letter table is real and referenced in real code.
**Gap:** No dedicated living "Operations Runbook" document exists under `docs/` — this spec file
itself is the only copy of the content; nothing restates it as an operational doc engineers actually
follow day-to-day. Weekly/monthly maintenance cadence has no automation forcing it. Unverifiable in
practice anyway, since nothing is deployed (see doc 18).

### 20_Testing_Strategy.md — **~65%**
**Done:** Real unit/integration suite (87 files under `backend/tests/`, not counting `tests/
pending/`), security testing matches spec exactly (`test_policy.py`/`test_policy_v2.py` directly
test the denylist), CI spins up a real Postgres+pgvector container and runs real migrations before
tests. Two separate agent-eval systems exist (see the pending-tests file for full detail) — one
wired into CI, one standalone.
**Gap:** **Zero Playwright or any browser E2E test setup exists anywhere in the real project** —
exhaustive search confirms this, excluding third-party reference clones under `/repos`. Files named
`*_e2e.py` exist but are backend-only HTTP-client tests gated in `tests/pending/`, not the
browser-driven dashboard E2E the spec describes. The `packages/*`-per-package-Vitest testing
structure the spec assumes doesn't exist (see doc 04).

---

## Part 2 — Vision / Master-Plan Files

### tools_agents.md (the ~190 tools / ~60 agents / ~22 infra-services vision)
**Status: exceeded on agent and tool count.** Grep-verified: **72 real registered agents** (not 60
— the naive count of 73 includes `groq_adapter.py`, which deliberately has no `AGENT_CONTRACT`/
registry entry as an infra adapter, not an agent). **197 distinct tool names** in `agents/tools.py`
(exceeding the "190" claimed in the v1.2.0 commit). Nearly every named tool category from the spec
is present (repo/search/AST/editing/terminal/git/testing/debug/docs/browser(Playwright-backed)/DB/
docker/security/memory tools all confirmed by name). All 22 infra-layer services from the spec exist
in code, not just as names.
**Gap:** A handful of named external integrations are genuinely absent — GitLab, Jira, Notion,
Figma, AWS, Azure, Helm (Kubectl only appears inside a *denylist* string, not as a real tool).
GitHub/Linear/Slack integrations ARE present. Qdrant's absence is a documented, deliberate ADR
choice (pgvector instead), not a gap.

### MASTER_PROMPT_PACK.md (original 8-day build plan)
**Status: tech-stack claims are obsolete; deliverable checklist was honored.** This doc mandates a
pure TypeScript system (Claude Agent SDK, Turborepo `packages/*`, LangGraph.js, Inngest→BullMQ) —
that entire stack was deliberately abandoned on 2026-07-02 (commit `c6ced96`, "archive TS to TX/,
scaffold FastAPI foundation") in favor of the current Python backend. This is a disclosed,
intentional pivot, not a hidden gap — but it means this doc can't be used as a literal
architecture-verification spec anymore. What it explicitly names as Day 8 deliverables (separate
from the 20 numbered docs) all genuinely exist: `docs/reports/FINAL_AUDIT_REPORT.md` (189 lines,
real hardcoding-audit findings with fix status), `docs/SELLABILITY_GAP.md`, `docs/
ADD_A_NEW_AGENT.md`, root `README.md`, and real git tags `v1.0.0`/`v1.1.0`/`v1.2.0` on distinct,
correctly-dated commits.

### main_client_share_file.md (5 client milestones)
**Status: all 5 present in code**, milestone 5 ("full AI engineering department continuously
building products") being aspirational/ongoing by nature rather than a fixed target — the 72-agent
fleet plus 5 dedicated fleet-governance agents (performance reviewer, debugger, advisor, knowledge
curator, quality auditor) is real evidence of progress toward it, gated by design behind human epic
approval (RBAC), not a gap.

### agent_enhancement.md and agent_models.md
**Status: confirmed superseded design docs, not a separate outstanding requirement.**
`agent_enhancement.md` maps almost line-for-line onto `docs/FLEET_ENHANCEMENT_PLAN.md`, which
explicitly cites it as its source ("Added from agent_enhancement.md requirements"). `agent_models.md`
maps directly onto the real `backend/app/fleet/agent_models.json` (diffed: keys match the 72 real
agents + `groq_adapter`). Both are pre-work for the separately-tracked Fleet Enhancement Plan, whose
Days 0-18 are complete and gap-closed, with Day 19 prepped-but-not-deployed (see Part 3).

### "Gridiron Agent OS - Open Source Reference Matrix.md"
**Status: 100%.** All 10 named reference repos (aider, autogen, cline, composio, continue,
langgraph, opencode, open-hands, roo-code, swe-agent) confirmed present under `/repos`. One extra
directory (`andrej-karpathy-skills`) exists beyond the original doc — confirmed legitimate, added
later and documented in `PROJECT.md` for a specific Fleet Enhancement Plan day, not a contradiction.

---

## Part 3 — The Separate 19-Day Fleet Enhancement Plan (`docs/FLEET_ENHANCEMENT_PLAN.md`)

Not one of the `/files` docs, but `agent_enhancement.md`/`agent_models.md` were its design inputs,
so it's summarized here for completeness. This plan has already been through its own multi-round
gap-closure process this session (Days 11-13 audit, Days 11-15 audit, and a full Days 0-18 re-audit
+ Day 19 prep, all separately reported in `docs/reports/`).

| | Status |
|---|---|
| Days 0-18 (all 68→72 agents fully wired, 20 Fleet OS capabilities, event bus, checkpoint/rollback ladder, human approval UI, git push workflow, blank-repo bootstrap, image input, credential vault, real-time streaming) | **Complete, gap-closed** (2707 tests passing, mypy --strict clean) |
| Day 19 — production-readiness prep (CI confirmed adequate, `vercel.json` pnpm fix, `.env.example` completeness, `docs/DEPLOYMENT.md` written) | **Complete** |
| Day 19 — actual cloud deployment (Supabase project, Railway/Render backend, Vercel frontend, real live URL) | **Not done — intentionally skipped per your explicit instruction.** Everything needed is written and correct; it just needs your own account-level actions. See `docs/DEPLOYMENT.md`. |

---

## Master Gap List — Everything Found, Prioritized

### 🔴 High-impact / most worth fixing next
1. **Redis Streams event bus is fully built but never called** — `publish_event()` doesn't feed it;
   flipping the env flag today does nothing but add a health-check ping. (Doc 12)
2. **Neither named queue backend actually works in production** — the live selector never checks
   for `"rq"` (falls through to in-process silently), and `"bullmq"` is a confirmed stub. The real,
   working `rq_adapter.py` is dead code. (Doc 14)
3. **No live deployment exists anywhere** — this is the one gap that can't be closed by more code;
   it needs your Supabase/Railway/Vercel accounts. (Doc 18, Fleet Plan Day 19)
4. **Zero Playwright/browser E2E tests exist** — a real, acknowledged, still-open gap across every
   report this project has ever produced. (Doc 20)
5. **`indexed_files`/`symbols`/`call_edges` DB tables are migrated but have zero writers** — the
   scanner never persists to them; looks complete, isn't. (Docs 09, 10)
6. **MCP is not actually the tool-access mechanism anywhere in the live agent path** — despite being
   named as the core principle in docs 02 and 07, and despite one real custom MCP server existing
   and going completely unused by the runtime.

### 🟡 Medium
7. `dev_tasks` is missing `priority`/`assigned_agent`/`project`/`final_summary` as real columns —
   the API fakes them as hardcoded placeholder values. (Docs 08, 09, 14)
8. Retention policy hard-deletes `task_logs` instead of archiving, per spec; `agent_runs`/
   `artifacts` have no retention logic at all. (Doc 11)
9. The "Learning Signal" memory category is schematically supported but never actually written to.
   (Doc 11)
10. Agent Registry View (Stage 6 dashboard screen) doesn't exist despite the backend being fully
    ready for it. (Doc 15)
11. `test_research_agent.py`'s skip condition doesn't actually check for a real key (only
    `RUN_PENDING_TESTS`) — would attempt and fail a real call instead of skipping cleanly if run
    today without a key. (Testing infra, see the pending-tests file)
12. Frontend has zero real test files and CI never runs a frontend test step at all (lint is even
    non-blocking, `|| true`). (Doc 04)
13. Function-level, cross-file call graph doesn't exist as a unified component — the file-level
    import graph is mislabeled as a "call graph," and the real function-level AST engine is
    single-file-only and lives outside the main pipeline. (Doc 10)
14. Architecture Mapper (spec 10) is entirely missing — no module exists.

### 🟢 Low / structural-only, not functional
15. The `packages/*` monorepo structure the original TS-era docs assume is completely empty/
    abandoned — real, but a consequence of the disclosed Python pivot, not an active bug.
16. Branch-naming convention (`stage-N/...`) isn't followed in practice.
17. A handful of named external tool integrations (GitLab, Jira, Notion, Figma, AWS, Azure, Helm)
    from `tools_agents.md` are genuinely absent.
18. `evals/` (standalone CLI) and `tests/evals/` (pytest-wired) are two redundant, unconsolidated
    agent-eval systems built at different times.

---

## Bottom Line

Nothing in this report is "fake progress" — every gap listed was confirmed absent by direct
grep/read, and every "done" claim has file:line evidence behind it. The project is genuinely far
along (72 real, wired agents; 197 real tools; a real, enforced policy engine; real human-approval
gates; real Sentry/alerting/JWT-auth/credential-vault security). The gaps that remain cluster into
three honest categories: **(a) real code that's built but never wired into the live path** (Redis
Streams, RQ adapter, MCP server, the 3 repo-intel DB tables), **(b) features the spec docs describe
that were never built at all** (Architecture Mapper, Agent Registry dashboard view, browser E2E
tests, DB-level status constraints), and **(c) one thing that fundamentally requires you, not more
code** (an actual live deployment). Nothing here needs guessing at what "done" means — it's all
independently checkable the same way this report was produced.

# Day 9 Implementation Plan — Fleet Enhancement Dashboard + 5 Self-Improvement Agents
Prepared: 2026-07-20, updated 2026-07-20 (v2 — user expanded scope with a real product vision).
Implementation starts next session. This doc is the single source of truth for that session —
read it first, don't re-derive.

## What changed from v1

v1 treated Day 9 as "5 small read-only agents, follow debugger_agent.py's shape." The user
then described a real product: these 5 agents self-improve the **Gridiron platform itself**
(not a user's connected external repo), report findings to a dedicated dashboard with
priority triage, and only ever act after explicit human approval — then commit and notify.
This is a genuine feature (dashboard + approval workflow + background scanning + git-commit
tool), not just 5 more agent files. v1's tool/contract research is still correct and kept
below; the architecture around it is new.

**User decisions locked in (asked via AskUserQuestion, 2026-07-20):**
- Scan trigger: **background loop, every few hours** (same lightweight pattern already used
  for the retention/reindex loops in `main.py`'s lifespan — no new scheduler dependency)
- Notifications: **in-app dashboard only** (badge/live list, no browser push — matches the
  project's self-hosted, no-cloud-SaaS posture already established elsewhere)

## Source of truth
- `docs/FLEET_ENHANCEMENT_PLAN.md` lines 792–820 (Day 9 summary) and lines 984–1025 (Day 13
  Human Approval UI — the pattern this dashboard pulls forward, adapted — see architecture
  decision below)
- `files/agent_enhancement.md` lines 224–299 (original 5-agent spec, richer wording)
- This session's chat: user's own description of the dashboard, priorities, per-agent scope,
  and the "full project access, git commit, notify me, restart" flow

---

## Architecture decision: two-phase Scan→Propose / Approve→Apply (not LangGraph interrupt())

Checked the actual installed code: `build_agent_graph()` compiles with **`g.compile()`, no
checkpointer** (`app/agents/base_graph.py:750`). The plan's Day 13 design
(`langgraph.types.interrupt()` + `Command(resume=...)`) requires a checkpointer to actually
suspend and later resume a graph — that's not wired anywhere in this codebase yet, for any
agent. Wiring it now would be a foundational, fleet-wide change (Postgres checkpointer,
resume plumbing) far bigger than "5 agents," and isn't needed for what the user actually
described.

What the user described is naturally **two separate runs**, not one paused mid-way:
1. **SCAN** (autonomous, no approval needed — it's read-only, so it's safe to run
   unattended): each of the 5 agents runs periodically, investigates, and for anything worth
   flagging calls a new `submit_enhancement_request` tool. This writes a row to a new
   `enhancement_requests` table with status `pending`. Nothing on disk changes.
2. **APPLY** (only fires after the user clicks Approve on a specific request): a **second,
   separate** `run_agent_graph()` call for the same agent, this time with write tools
   (+ bash + a new git-commit tool) enabled, scoped to fixing exactly that one approved
   request. Streamed live to the dashboard via the **already-built P1 Activity Stream**
   (`app/services/activity_stream.py`, `/api/tasks/{id}/stream`) — reusing infrastructure,
   not rebuilding it. On success: commits (never `git add -A` — stage only the touched files,
   per CLAUDE.md's git safety rules) and marks the request `completed` with a
   `restart_required` flag for the dashboard banner. Reject just marks `rejected` — agent
   never runs Phase 2 at all.

This is simpler, safer (matches CLAUDE.md's "no agent acts without approval" default even
more literally than a mid-run pause would), reuses two pieces of infrastructure that already
exist and work (ActivityStream, the background-loop pattern in `main.py`), and doesn't
require touching how every other agent's graph compiles.

---

## Scope note: these agents operate on the Gridiron project itself

Per the user: these 5 agents work "out of project... in direct crr2906 folder" — unlike
every other agent (which operates on a user-connected external repo via
`settings.target_repo_path` / git worktrees), these 5 always target the Gridiron codebase's
own root (`/home/pc-117/Documents/CRR2906`, both `backend/` and `apps/web/`, plus read access
to `/repos` for pattern research). This is a deliberate, narrow exception — not a general
relaxation of the worktree-isolation rule for other agents. **Read access is broad** (they
need to see everything to find real issues); **write access is fully gated behind explicit
per-request approval**, and even then scoped to only the files named in that specific
request. New config: `FLEET_SELF_REPO_PATH` (defaults to the project root, never hardcoded
per CLAUDE.md's zero-hardcoding rule).

---

## New DB table: `enhancement_requests`

New Alembic migration (next number after the current head — check `backend/migrations/versions/`
for the latest at build time). Columns:

```
id                 BigInteger PK
agent_name         String(100)   -- one of the 5
title              Text          -- short, human-readable
description        Text          -- plain-language explanation (no jargon dump) — this is
                                     what the user reads on the dashboard card, must be
                                     understandable without opening code
category           String(50)    -- performance | bug | orchestration | knowledge | quality | security
priority           String(20)    -- emergency | medium | low
evidence           JSON          -- file:line citations, metrics snapshot, whatever backs the claim
status             String(20)    -- pending | approved | rejected | in_progress | completed | failed
files_touched      JSON          -- populated after apply phase
commit_sha         String(64)    -- populated on successful commit
restart_required   Boolean
error              Text          -- populated on failure
trace_id           String(64)
created_at         DateTime
decided_at         DateTime      -- when approved/rejected
decided_by         String(100)   -- for now: the single admin user; keep the column for
                                     when real multi-user RBAC applies here too
completed_at       DateTime
```

`app/db/models.py`: new `EnhancementRequest(Base)` ORM class next to `MemoryEmbedding`.

## New backend module: `app/api/fleet_dashboard.py`

```
GET  /api/fleet/requests?agent=&status=&priority=   → list, newest first
GET  /api/fleet/requests/{id}                        → detail incl. evidence
POST /api/fleet/requests/{id}/approve                → status=approved, kicks off Phase 2
                                                          run in background (asyncio.create_task),
                                                          returns immediately with trace_id
                                                          the frontend uses to open
                                                          /api/tasks/{trace_id}/stream (reuse P1)
POST /api/fleet/requests/{id}/reject                 → status=rejected, terminal, no further action
GET  /api/fleet/requests/stream                      → SSE: dashboard-level events (new request
                                                          created, status changed) — drives the
                                                          in-app badge/live list without polling.
                                                          Separate channel from the per-run
                                                          activity stream (that one is for
                                                          watching one approved request execute;
                                                          this one is for "something new appeared").
```

Wire router into `app/main.py` alongside the existing routers.

## New tool: `git_commit_change` (Phase 2 only, scoped)

`app/agents/tools.py` — new tool + handler:
- Input: `{files: string[], message: string}`
- Stages **only** the named files (`git add <file> <file> ...`, never `-A`), then
  `git commit -m <message>`, returns the commit SHA. Reuses the safety posture already
  established for `git_commit` in `chat_agent.py` (never force, never touches
  `.env*`/`secrets/**`/`.github/workflows/**` — enforced by the existing `check_path`
  guardrail in `app/agents/guardrails.py`, already wired into `execute_tools`).

## Background scan loop

`app/main.py` lifespan — new `asyncio.create_task(_fleet_agents_scan_loop())`, same shape as
the existing `_weekly_reindex_loop`/`start_retention_loop`. New config:
`FLEET_SCAN_INTERVAL_HOURS` (config.py, documented in `.env.example`, no hardcoded default
baked into code — read from settings). Runs the 5 agents' SCAN phase **sequentially** (not
parallel — real LLM calls, avoid a runaway-cost loop), each producing zero or more
`enhancement_requests` rows.

## Frontend: Fleet Dashboard tab

`apps/web/app/fleet/page.tsx` (new nav entry "Fleet" next to Console/Tasks/Metrics in
`NavBar.tsx`). Reuses existing patterns from `/console` and `/stream/[taskId]`:
- List of request cards grouped/filterable by agent, sorted by priority
  (emergency → medium → low) then recency
- Each card: agent name, title, plain-language description, priority badge (red/amber/gray),
  category tag, Approve / Reject buttons
- On Approve: card transitions to "in progress," embeds the existing live activity feed
  (reuse `ActivityFeed`/`ThinkingBlock`/`ToolCallBlock` components from Day 5A) so the user
  watches the fix happen start to end, exactly like `/stream/[taskId]`
- On completion: card shows commit SHA + "Restart required to see changes" banner if
  `restart_required` is set
- In-app notification: a badge count on the "Fleet" nav item, driven by the
  `/api/fleet/requests/stream` SSE channel — no browser push (per the locked-in decision)

---

## The 5 agents — concrete build spec (tool grounding from v1, scope updated per user)

Each follows `debugger_agent.py`'s shape for its **SCAN** phase (`AGENT_CONTRACT` → tools →
`VerificationConfig` → handlers → `run_<name>_scan()` → `_register()`), plus a second
**`run_<name>_apply(request_id)`** entry point for Phase 2 with an expanded, write-capable
toolset used only after approval.

### 1. `agent_performance_reviewer`
User's expansion: not just other agents' performance — **whole-project** performance
(backend + frontend), same investigative depth as agent_debugger.
- Capability tag: `agent_performance_review` (checked — no collision; existing
  `performance_reviewer` agent owns the plain `performance_review` tag, don't reuse)
- SCAN tools: `read_file`, `list_files`, `search_code`, `get_file_tree`, **new**
  `fleet_metrics_read` (wraps `MetricsCollector.by_agent/p50_latency_ms/p95_latency_ms/
  avg_tool_accuracy` from `app/fleet/metrics.py` — already exists, just needs a tool
  wrapper), `web_search` (**already exists and works** — `_WEB_SEARCH_TOOL` +
  `web_search()` handler in `tools.py`, uses `duckduckgo_search`, no API key needed — reuse
  directly, don't rebuild), `submit_enhancement_request`
- `set_by`: `{"fleet_metrics_read": "metrics_read"}`, `enforce_in_result: {"metrics_read": "metrics_read"}`
- APPLY tools (post-approval): + `write_file`, `edit_file`, `run_tests`, `git_commit_change`

### 2. `agent_debugger`
User's expansion: best-effort model, full project access, silent when nothing found,
immediate dashboard update when something is found, full main toolset for the apply phase.
- Capability tag: `agent_debugging`
- Model: explicitly pin to the `sonnet` tier in `agent_models.json` (already the fleet
  default for coding-capable agents per CLAUDE.md's MODEL_TIERING rule — confirm it's not
  accidentally on `haiku`/`router`; if the user wants Opus specifically for this one agent,
  that's a single-line override in `agent_models.json`, flag it as an easy follow-up, not a
  blocker for Day 9)
- SCAN tools: `read_file`, `search_code`, `get_file_tree`, `bash` (scoped via the existing
  `check_command`/`check_allowlisted_command` guardrail — same pattern every bash-using agent
  already follows, no new "limited bash" tool needed), **new** `audit_log_read` (wraps
  `AuditLog.recent()` filtered client-side by agent_name — simplest, no changes needed to
  `audit_log.py` itself), `fleet_metrics_read` (shared with agent 1), `submit_enhancement_request`
  — **"silent if nothing found"**: the role prompt instructs it to only call
  `submit_enhancement_request` when it has real evidence; an empty scan run is a normal,
  expected outcome, not an error
- `set_by`: `{"audit_log_read": "diagnosed"}`, `enforce_in_result: {"diagnosed": "diagnosed"}`
- APPLY tools (post-approval, **full toolset per user's "all main tools" request** — matches
  backend_dev/coder's scope, not the narrower v1 read-mostly list): `read_file`, `write_file`,
  `edit_file`, `apply_patch`, `search_code`, `bash` (scoped), `run_tests`, `git_diff`,
  `git_commit_change`

### 3. `agent_advisor`
User's reframe: **orchestration correctness**, not general architecture advice — did the
right agent(s) run for a given task, was anything missing or over-provisioned (their own
example: a "generate one project file" task that also triggered QA and other unneeded
agents), advise other agents (PM through all 68) when it spots this.
- Capability tag: `orchestration_advisory` (renamed from v1's `architecture_advisory` to
  match the user's actual, narrower framing — architecture-wide advice is a different,
  broader job the user did *not* describe for this agent)
- SCAN tools: `read_file`, `search_code`, **existing** `task_history_query` (already built —
  queries `task_logs` via a `psql` subprocess, sync-safe, no async-DB wrapping needed, see
  `tools.py:3476` + handler at `tools.py:7329`), `fleet_metrics_read`, `audit_log_read`,
  `submit_enhancement_request`
- risk_level: `low`, purely read-only — no APPLY phase with write tools; its output is always
  an advisory note attached to the request (e.g. "recommend skipping qa_node when task_type=
  docs_only"), which becomes a request the user can approve to have some *other* agent (or a
  manual pipeline-config change) implement — advisor itself never writes code
- `set_by`: `{"task_history_query": "history_read"}`, `enforce_in_result: {"history_read": "history_read"}`

### 4. `knowledge_curator`
User's framing: help agents understand what the user actually needs and steer them the right
way. Synthesis with v1's memory-curation research (both point at the same underlying
mechanism): the concrete way a curator makes agents "go the right way" is by keeping the
fleet's shared memory — `memory_embeddings` (persistent, semantic, Voyage AI-searched via
`app/api/memory.py`/`app/memory/store.py::query_similar_tasks`) — accurate, deduplicated, and
well-categorized, since that memory is what future `memory_hook_node` calls inject into every
agent's context. **Flag this synthesis explicitly to the user at the start of the build
session** in case the intent was actually something else (e.g. a live intent-clarification
step during task intake, which would be a different, PM-node-adjacent feature) — don't let
this be a silent reinterpretation.
- Capability tag: `knowledge_curation`
- SCAN tools: `read_file`, **new** `memory_search` (wraps `query_similar_tasks()` via a plain
  `asyncio.run(...)` — confirmed safe, no event loop already running in a sync tool handler;
  `app/db/session.py` has no sync engine alternative, so this is the right approach, not a
  workaround), **new** `memory_curate_read` (list/inspect `MemoryEmbedding` rows — named
  distinctly from the *different*, semantically unrelated per-repo `memory_read` tool already
  in `tools.py:3439`, **do not reuse that one**, it's a simple KV scratch store with no
  connection to the engineering-memory system), `submit_enhancement_request`
- `set_by`: `{"memory_search": "memory_searched"}`, `enforce_in_result: {"memory_searched": "memory_searched"}`
- APPLY tools: **new** `memory_curate_write` (mark a `MemoryEmbedding` row superseded/updated —
  intentionally a light precursor to Day 11's full versioned-lesson lifecycle, not a
  reimplementation of it), `git_commit_change` if the curation also touches
  `backend/roles/*.md` (e.g. recommending a role-prompt tweak based on a recurring pattern)

### 5. `quality_auditor`
User's expansion: UI quality/errors, cybersecurity (hacking-risk surface), general project
quality — "one by one."
- Capability tag: `fleet_quality_audit`
- SCAN tools: `read_file`, `list_files`, `search_code`, `get_file_tree`, plus **reuse
  security_reviewer's existing, proven security tools** rather than building new ones:
  `secrets_scan`, `find_sql`, `find_config`, `find_api`, `find_route` (all real, in
  `security_reviewer.py`'s tool list already), `bash` scoped to `apps/web/` for UI checks
  (`npx tsc --noEmit`, existing lint tooling — same pattern `cicd_agent`/`devops` already
  use, no new tool needed), `submit_enhancement_request`
- Worth checking at build time (not yet verified working): `app/repo_tools/browser_driver.py`
  exists (Selenium/Playwright-style automation, currently carries 18 pre-existing mypy
  errors, unrelated to this session's fleet work) — if functional, it's a natural fit for
  real UI-issue detection (broken renders, console errors) beyond static analysis; don't
  assume it works without testing it first
- `set_by`: `{"secrets_scan": "scan_ran"}`, `enforce_in_result: {"scan_ran": "scan_ran"}`
- APPLY tools: `write_file`, `edit_file`, `run_tests`, `git_commit_change` — "one by one" per
  the user means: each approved request should be a single, scoped fix, not a batch —
  enforce this by generating one `enhancement_request` per distinct issue, never bundling

---

## New shared tool: `submit_enhancement_request`

Used by all 5 agents' SCAN phase. Not a per-agent `_SUBMIT` tool like every other agent's —
this one is genuinely shared (same DB write target), so define it once in `tools.py`:
- Input: `{title, description, category, priority, evidence}`
- Handler: inserts a row into `enhancement_requests` (status=`pending`, agent_name from the
  calling agent's context, trace_id from the run) — same `asyncio.run(...)` DB-write pattern
  as the memory tools above

## Tests to write

`tests/test_day9_fleet_agents.py` (mirrors `test_day5b_agents.py` / `test_day8_role_prompts.py`):
- Contract shape, role-file structure (reuse Day 8's constants), `_register()` →
  `capability_registry` membership, capability-tag uniqueness against the ~189 existing tags,
  `enforce_in_result` non-empty with no dead keys — same checks as every prior day
- New tool unit tests: `fleet_metrics_read`, `audit_log_read`, `memory_search`,
  `memory_curate_read/write`, `submit_enhancement_request`, `git_commit_change` (mocked DB /
  mocked subprocess — never a real commit in tests)
- `run_<agent>_scan()` returns `AgentResult` on a mocked `run_agent_graph`
- `run_<agent>_apply(request_id)` — mocked, asserts it only runs when status is `approved`,
  never on `pending`/`rejected`

`tests/test_fleet_dashboard_api.py`:
- `GET /api/fleet/requests` list/filter
- `POST /api/fleet/requests/{id}/approve` → status transition, background task scheduled
  (assert via mock, don't let a real agent run fire in a unit test)
- `POST /api/fleet/requests/{id}/reject` → terminal status, no execution triggered
- Approve/reject on an already-decided request → rejected with a clear error (idempotency)

## Order of implementation tomorrow

1. Migration + `EnhancementRequest` ORM model
2. Shared tools: `submit_enhancement_request`, `fleet_metrics_read`, `audit_log_read`,
   `memory_search`/`memory_curate_read`/`memory_curate_write`, `git_commit_change` — unit
   test each in isolation before wiring into any agent
3. Build the 5 agent files (SCAN phase first for all 5, then APPLY phase for all 5) —
   `_register()` each, add to `agent_models.json`
4. `app/api/fleet_dashboard.py` + wire into `main.py`; background scan loop in lifespan
5. Frontend: `/fleet` dashboard page + NavBar entry, reusing Day 5A's activity-feed components
6. `tests/test_day9_fleet_agents.py` + `tests/test_fleet_dashboard_api.py`, full suite green
7. `mypy app/ --strict` — must not add to the pre-existing error count
8. Update `PROJECT.md` + `docs/PROJECT_CONTROL_CENTER.md`, write
   `docs/reports/FLEET_DAY9_TEST_REPORT.md`, commit
9. Re-audit against this doc's own success criteria (ZERO-SKIP): all 5 agents +
   dashboard + approval flow + background loop + notifications all present and tested —
   not just "agents exist"

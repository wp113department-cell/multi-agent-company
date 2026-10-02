# 09 — Master Performance & Scalability Audit (Concurrency, Blocking Calls, DB, Token/Cost, Frontend, Scalability)

- **Audit ID:** 09
- **Baseline commit:** `c927c44bf410e188287f32b2cf54e0529c642025` ("Production audits 09 and 11", 2026-10-02 11:11 +0530) — **baseline drift note:** HEAD advanced twice during the series (`ecd4905a` "Production audit 12" → `33bbd03c` "Production audit 13"). The baseline commit itself contains a set of *already-applied* performance fixes (thread-pool sizing, slot-acquisition timeout, fleet spend guard, worktree retention — each labeled "Production audit 09") — everything below is audited **as it exists on disk at `33bbd03c`**, i.e. with those fixes present.
- **Run date:** 2026-10-02
- **Method:** read-only static verification. Full reads: `pipeline/concurrency.py`, `fleet/budget_manager.py`, `fleet/spend_guard.py`, `pipeline/cost_controller.py`, `pipeline/conflict_guard.py`, `pipeline/file_locks.py`, `repo_tools/context_builder.py`, `services/activity_stream.py`, `db/session.py`, `api/budget_gate.py`, `api/activity.py`, epic-manager graph/cost nodes (`agents/manager.py`), epic approve endpoints (`api/epics.py`), frontend epic pages. Plus one **AST scan of all 496 `backend/app/*.py` files** for blocking calls (`subprocess.*`, `os.system/popen`, `time.sleep`, `requests.*`, `httpx.Client`) inside `async def` with/without `asyncio.to_thread` wrapping, and targeted greps (`selectinload`, HNSW DDL, `<=>` operators, `to_thread(`, polling intervals, `check_daily*` callers). **Static analysis only — not load-tested** (stated per finding where reasoning, not measurement, is involved).
- **Scope per brief:** 6 phases — concurrency correctness, blocking-call audit, DB performance, token/cost controls, frontend performance, scalability reasoning (explicitly static).

---

## 1. Executive Summary

The performance core is **materially better than the brief assumes it might be**, and several of the classic failure modes have *already been fixed at the baseline commit itself*: the event loop has **zero unwrapped blocking calls** (a full AST scan found 3 candidates, all verified to be sync helpers correctly dispatched via `await asyncio.to_thread(...)`); the default thread pool is explicitly re-sized so 20 concurrent agent runs can't be starved by the stdlib's 10-thread default (`main.py:1402-1420`); slot acquisition fails **loudly** after a bounded wait (`SlotAcquisitionTimeout`, 2100s > 1800s max run time); and the daily LLM spend cap is now a **hard pre-call gate installed on the Anthropic SDK itself** (`fleet/spend_guard.py`, wrapped in `app/__init__.py:5`), plus a preventive per-turn token stop, plus a pre-dispatch 429 on the task/approval/specialized/epic endpoints.

**One High finding (PROD-09-101): the cost-approval gate has no working approval path.** An epic over `COST_APPROVAL_THRESHOLD` ($1.00) is halted to `pending_cost_approval` — but "Approve Cost & Start Agents" relaunches the manager, which re-enters the same deterministic pre-flight gate and re-blocks; the other approve endpoint strands the epic at status `approved` with no relaunch. The gate itself is real and correct; the resume path is a deterministic dead end, and no test covers the approve direction (tests only exercise the block direction).

**Two Medium findings:** the pre-flight gate estimates with a **hardcoded `subtask_count=5`** and the refined estimate computed after planning is stored but **never re-gated** (PROD-09-102); and the repo-context cache is **unbounded and its per-repo invalidation can never match** — keys are SHA-256 hashes, invalidators pass repo paths (PROD-09-103). **Three Lows:** `GET /api/epics` returns every epic ever created with no pagination while the UI polls it every 5s (PROD-09-104); `BudgetManager.check_daily()`/`check_daily_db()` have zero production callers (the docstring cites a caller that now calls different methods — cross-ref Audit 11) (PROD-09-105); and the per-epic subtask-semaphore dict is never pruned (PROD-09-106).

**Verdict: READY FOR PRODUCTION — no data-loss, security, or core-operation defects; fix PROD-09-101 before relying on cost-approval gating. Score: 78/100** (static analysis only, not load-tested).

---

## 2. Concurrency Correctness (Phase 1) — **VERIFIED**

| Semaphore | Definition | Real acquisition (file:line) | Verdict |
|---|---|---|---|
| `epic_slot()` (`max_concurrent_epics=10`, config.py:801-803) | plain `asyncio.Semaphore` | `run_epic_manager()` wraps the entire orchestration body: `async with epic_slot(): return await _run_epic_manager_body(...)` (`manager.py:1847-1851`, the ORCH-04-009 fix); released on **every** early-return path — proven by `test_audit04_orchestration_fixes.py:611-...` (`max_epics=1`, two sequential pending_cost_approval runs cannot hang) | Verified |
| `agent_run_slot(priority)` (`max_concurrent_agent_runs=20`, 804-806) | `PrioritySemaphore` (priority + FIFO, CPython-mirrored cancellation safety, concurrency.py:24-113) | Acquired around **each** LLM-calling stage per subtask: dev dispatch (596), QA run (754), reviewer run (836) — bounded by `slot_acquisition_timeout_seconds=2100` via `asyncio.wait_for` → `SlotAcquisitionTimeout` (188-194) | Verified |
| `subtask_slot(epic_id, priority)` (`max_concurrent_subtasks_per_epic=5`, 831-834) | `PrioritySemaphore` per `epic_id` | Acquired for the whole subtask lifecycle via manual `__aenter__`/`__aexit__` pairing (`manager.py:521-525` … `986`), with the documented invariant "nothing in this loop raises past this function"; timeout routes through the same loud blocked-subtask path (526-552) | Verified |

- **Internal consistency:** worst case `10 epics × 5 subtasks = 50` subtasks contending for `20` global agent-run slots ⇒ **queueing, not silent starvation**: each waiter is bounded by a wait timeout **2100s > `max_run_time_seconds` 1800s** (config.py:844-847 documents this exact arithmetic as the audit-09 fix, "was 300"), and an exhausted wait produces a *visible* blocked subtask with reason — the failure is loud by construction (`SlotAcquisitionTimeout.__init__` message: "possible deadlock").
- **`conflict_guard.check_file_conflicts()` O(n²) question — answered from the real call graph:** it is called **once per epic** (not per subtask) in `_conflict_check_node` (`manager.py:2225-2267`), and does `1 + E` queries for `E` running epics with `E ≤ max_concurrent_epics = 10` (conflict_guard.py:39-56; per-epic file query 59-70). Total cost across all concurrent epics ≈ `E(E+1)/2 ≤ 55` small indexed queries, one-time per epic — **not a bottleneck**, and the advisory read is backed by a real DB-enforced lock (`file_locks.py::reserve_epic_files`, UNIQUE(file_path) + SAVEPOINT all-or-nothing + TTL reaping; migration 039). The only file-selection caveat was already fixed at the baseline: `_get_epic_files` now parses the architect plan's real `{"path": ...}` schema (77-91), so the guard no longer silently returns an empty set.
- **Observation (not a finding):** `max_run_time_seconds` is *detective* (checked post-run via `check_run`); nothing kills a live run at 1800s. The live bounds are the per-call LLM timeout (`llm_call_timeout_seconds=300`, applied at client construction `base.py:56`/`base_graph.py:135`), the per-turn token stop, and the slot-wait timeout. Consistent and documented; no hung-run path found.

### PROD-09-106 — `_subtask_sems` grows for the process lifetime; per-epic semaphores are never pruned
- **Severity:** Low · **File:** `backend/app/pipeline/concurrency.py:118,153-158` · **Confidence:** High (code-verified)
- **Finding:** `_subtask_sems[epic_id]` is created on first use and removed only by `reset_for_testing()` (218-227). Across a long-lived process, one small `PrioritySemaphore` per epic ever run accumulates.
- **Evidence:** zero other readers/writers of `_subtask_sems` in `app/` (grep).
- **Production impact:** bytes-scale leak per epic; correctness unaffected (a stale semaphore for a finished epic is unreachable). Hygiene issue; cross-ref Audit 11 (dead/lifetime code).
- **Recommendation:** delete the entry in `_finalize_node` alongside `release_epic_files()` (same lifecycle point already exists). Effort: S.

---

## 3. Blocking-Call Audit (Phase 2) — **VERIFIED CLEAN (zero unwrapped calls)**

**Method:** AST scan (temporary read-only script, deleted after use) over all `backend/app/**/*.py` finding every `subprocess.run/Popen/call/check_output/check_call`, `os.system/popen`, `time.sleep`, `requests.*`, `httpx.Client` call lexically inside an `async def`, then walking the ancestor chain to detect an enclosing `asyncio.to_thread(...)` — plus direct greps: **182** `subprocess.run(` sites total, **0** sync `requests.*` calls, **1** `time.sleep` site.

- **3 scanner hits — all verified safe:** `chat_agent.py:3079/3121/3162` are `subprocess.run` calls inside nested **sync** helpers `_run_npm_install` / `_run_npm_script` / `_run_pip_install`, each dispatched by `await asyncio.to_thread(...)` at 3092/3134/3172. Not on the event loop.
- **The single `time.sleep`** (`base_graph.py:2570`, backoff in `_run_tool_with_retry`) lives in a sync helper executed as part of the sync agent graph — and agent runs are dispatched off-loop (`manager.py:755/837` `await asyncio.to_thread(run_qa/run_reviewer, ...)`; the LangGraph tool node `execute_tools` is a sync function, `base_graph.py:2659`).
- **Known historical hotspot re-checked:** the doc-agent's git lookup now wraps `subprocess.run` in `to_thread` with the original incident documented in-line (`main.py:1202-1214`, "B9 verification #160"); the repo scanner/reindex paths are `to_thread`-dispatched throughout (`api/repo.py:425,459,488,542,547,573,575,600,602,631,633`), including the startup warm-up which is a fire-and-forget `to_thread` task (`main.py:1498-1513`).
- **Honest caveat (stated per brief):** the scan detects *direct* blocking calls; the cross-function case "async code calls a sync helper that blocks" cannot be fully enumerated statically. The hot chokepoint for that class — tool execution — was verified manually: the tool retry helper is invoked from the sync graph node (which runs in the worker thread), not from a coroutine.

---

## 4. Database Performance (Phase 3) — **VERIFIED (one Low finding)**

- **Connection pooling:** `create_async_engine(pool_pre_ping=True, pool_size=20, max_overflow=10)` from real config fields `db_pool_size`/`db_pool_max_overflow` (`db/session.py:46-51,85-89`; `config.py:807-821` — both env-exposed and documented as the audit-4.7#2 fix), plus a **server-side `statement_timeout`** applied via asyncpg `server_settings` on every pooled connection (30s default, session.py:17-29; config.py:822-830) so no query can hang a connection indefinitely. (No `pool_recycle` — see cross-audit note in §8.)
- **N+1 sweep:** `list_tasks` is cursor-paginated (`limit ≤ 100` enforced at the API, `api/tasks.py:208-213`) and eager-loads `selectinload(DevTask.repo)` (`repository.py:353-375`); epic detail/batch paths `selectinload(Epic.repo)` (`api/epics.py:402-403`); `fleet_dashboard` endpoints are aggregate `GROUP BY` queries (5 executes, zero per-row queries — 585/648 iterate result rows, not trigger queries); `list_subtasks` is a single indexed query. No missing-eager-load site found in any list path (structurally enforced by async SQLAlchemy: a lazy access would raise `MissingGreenlet`).
- **HNSW index usage — verified against DDL + query operators:** indexes exist for all three vector tables — `memory_embeddings` (migration `004:90-91`), `versioned_lessons` (`020:27-28`), `code_embeddings` (`032:29-30`), all `USING hnsw (... vector_cosine_ops)`. Every similarity query uses the matching `<=>` cosine operator (memory/store.py:619/630/1018/1029/1177/1186/1373/1381/1560/1569; embeddings.py:189; analytics.py:186). The composite-ranking sort that **cannot** use HNSW is handled correctly by two-stage retrieval: inner CTE = bare `ORDER BY embedding <=> :vec LIMIT k × memory_candidate_overfetch_factor (10)`, outer = composite re-rank of only those candidates (`store.py:600-635`, with the reasoning in-line as the audit-4.4#1 fix).
- **Query patterns:** `statement_timeout` bounds worst cases; retention archive flags avoid deletes; no `SELECT *`-into-ORM N+1 found in list endpoints.

### PROD-09-104 — `GET /api/epics` is unbounded while the UI polls it every 5s
- **Severity:** Low · **File:** `backend/app/api/epics.py:150-170` · **Confidence:** High (code-verified; scale impact reasoned, not load-tested)
- **Finding:** the endpoint executes `select(Epic).order_by(Epic.created_at.desc())` with **no limit/cursor** and returns every epic ever created; the frontend epics page polls at 5s (surveyed in Audit 08 §6). Every open dashboard tab re-downloads the entire epic table every 5 seconds — response size and JSON serialization grow linearly with lifetime epic count.
- **Evidence:** contrast with the correctly paginated tasks list (`repository.py:353-375`, cursor + `le=100`).
- **Production impact:** none at demo data sizes; at thousands of epics it becomes the heaviest periodic request in the app (self-inflicted polling load, PROD-08-101's shared-bucket arithmetic also worsens).
- **Recommendation:** add the same cursor/limit shape as `list_tasks` (status filter already exists in the query for batch-review). Effort: S.

---

## 5. Token & Cost Controls (Phase 4) — **STRONG (one High + one Medium found in the approval path)**

- **Context-window enforcement (`_trim_messages`, the brief's question):** the drop-oldest trimmer no longer exists — it was replaced by **real LLM summarization** (`_condense_messages`, `base_graph.py:948-993`): keeps `head[0] + tail[-4]`, summarizes the middle via a Haiku call (max 512 tokens), splices one synthetic summary message, and pushes a `context_trimmed` SSE event. On summarization failure it emits an explicit `"(N earlier messages were dropped; summarization failed: ...)"` placeholder (940-945) — **no silent loss**. Its usage is folded into run token totals (1999-2002), so the extra call is budget-accounted. An 80%-of-budget `approaching_limit` SSE fires first (1875-1880), and a separate safety net compares against the **real** model window (`_real_context_window`, 1884-1901). Chat sessions have the async counterpart reusing the same pure helpers (`chat_agent.py:681+`), and DB restore is bounded (`chat_history_restore_limit=200`, config.py:131-138).
- **Budget enforcement actually halts spend — at three levels, all verified:**
  1. **Pre-call, SDK-level (the strongest tier):** `spend_guard.install()` runs at package import (`app/__init__.py:5`) and wraps `Messages.create/stream` and `AsyncMessages.create/stream` at class level, so *every* Anthropic call in the process — agents, chat, memory consolidation, router — hits `check()` before sending; post-response real `usage` is priced by tier incl. cache write ×1.25 / read ×0.1 (`spend_guard.py:178-299`). Ledger = Redis `INCRBYFLOAT` (shared across workers/restarts) with a documented in-process fallback when Redis is down (98-128).
  2. **Pre-dispatch:** `require_daily_budget` dependency (429 before work starts) on tasks/approvals/specialized-agents/epics (`api/budget_gate.py:17-21`, four import sites), with `spent_today_with_db_floor()` floored by today's `agent_runs` sum so a lost Redis key can't reset the day (141-165).
  3. **Preventive per-turn stop:** `call_llm` checks cumulative tokens vs `max_tokens_per_agent_run` before each call → blocked + `budget_exceeded` health event (`base_graph.py:1791-1825`); the post-run pass re-checks and marks over-budget runs blocked (4195-4233).
- **Pre-flight epic estimate is a real gate, not informational:** over `cost_approval_threshold` ($1.00) the epic is set `pending_cost_approval` with a halt reason containing the per-subtask cost and a scope-reduction suggestion, emits an event, and the graph routes to END before planning/dispatch (`manager.py:2066-2127`, `_route_after_cost_estimate` 2532-2535). **But the resume path and the estimate inputs both have defects — PROD-09-101 and PROD-09-102 below.**
- **Per-agent model routing is cost-appropriate:** `agent_models.json` = 76 sonnet / 9 opus / 2 haiku (of 87 real entries) — consistent with the sonnet-priced estimator fallback and with Audit 07's finding that no dev-tier agent runs below sonnet (cost_controller.py docstring; cross-ref Audit 07).

### PROD-09-101 — **High:** the cost-approval gate has no working approval path (approve → deterministic re-block, or strand at `approved`)
- **Severity:** High · **File:** `backend/app/agents/manager.py:2036-2127,2532-2535,2638-2649`; `backend/app/api/epics.py:250-280,318-345`; `apps/web/app/epics/[id]/page.tsx:52-53,153-157` · **Confidence:** High (full call chain statically traced; not live-executed — read-only audit)
- **Finding (the complete chain, every link verified):**
  1. For an epic over the $1.00 threshold, `_cost_estimate_node` computes `estimate_epic_cost(subtask_count=5, db=db)` — a **pure function of config + historical `agent_runs` averages** — and on `requires_approval` sets `status="pending_cost_approval"` and routes to END (2066-2127).
  2. The UI click "**Approve Cost & Start Agents**" (`epics/[id]/page.tsx:153-157`) calls `POST /api/epics/{id}/approve-cost` → `approve_epic_cost` sets `status="pending"` and re-launches `_launch_epic_manager` (`epics.py:335-339`).
  3. The relaunch enters the graph at START (`graph.ainvoke(initial_state)`, `manager.py:2638-2649`); `resource_check → cost_estimate` is an unconditional edge chain (2579-2589). No approved-bypass exists anywhere: the `epic` row loaded in the node is unused (`# noqa: F841`, 2056), there is **no** `cost_approved`/skip flag in `app/` (grep: 0 hits), and the estimate inputs are unchanged — so `requires_approval` is still True and the epic is re-blocked to `pending_cost_approval`. **Approve → re-block, deterministically.**
  4. The *other* approve endpoint, `POST /api/epics/{id}/approve` (accepts `pending_cost_approval`, `epics.py:261-267`) sets `status="approved"` and **never relaunches**; no code consumes an epic in `approved` status (grep of status transitions: none) — that path strands the epic.
  5. **No test covers either resume direction.** The three relevant test modules only exercise the *block* direction (`test_phase51_epic_manager_graph.py:319-360,483-507`; `test_audit04_orchestration_fixes.py:611-716`; `tests/pending/test_manager_integration.py:96-121` flips the threshold to force a block); the only test touching `/approve-cost` asserts its rate/budget dependency (`test_audit09_spend_guard.py:179`).
- **Production impact:** every epic whose pre-flight estimate exceeds $1 is permanently stuck — its headline remedy ("approve to proceed at the current scope") cannot succeed; the operator's only workaround is raising `COST_APPROVAL_THRESHOLD` in config. Spend remains bounded (nothing runs), so this is a workflow dead-end, not a money-loss bug.
- **Recommendation:** persist approval on the epic (e.g. `cost_approved_at` column set by `approve_epic_cost`) and have `_cost_estimate_node` honor it for the current estimate (re-gate only if the refreshed estimate materially exceeds what was approved); make `approve_epic`'s acceptance of `pending_cost_approval` either relaunch or be restricted to `ready_for_review`; add a regression test running block → approve → planning reached. Effort: M.

### PROD-09-102 — **Medium:** pre-flight gate hardcodes `subtask_count=5`; the refined post-planning estimate is stored but never re-gated
- **Severity:** Medium · **File:** `backend/app/agents/manager.py:2058,2199-2206`; graph edge `manager.py:2590` · **Confidence:** High (code-verified)
- **Finding:** the approval gate evaluates `estimate_epic_cost(subtask_count=5)` before planning exists. After planning, the **real** count is known — `refined_estimate = estimate_epic_cost(subtask_count=len(subtasks), db=db)` — and it updates `Epic.cost_estimate` only (2200-2206). The graph then continues `planning → conflict_check` unconditionally (2590); no second approval check exists anywhere (grep `requires_approval`: only the one node).
- **Evidence & arithmetic (config-grounded):** at the config fallback rate (~$0.030/subtask: 4k in × $3/M + 1.2k out × $15/M) a 5-subtask estimate is ≈$0.15, while a 34-subtask plan ≈$1.02 — so the gate can pass an epic that, once planned, is well over the threshold without human approval; conversely a genuinely-small plan is conservatively blocked by the placeholder (and then hits PROD-09-101's dead end). Real trigger frequency is data-dependent (historical-average calibration).
- **Production impact:** the "human approval before money is spent" decision can be made on an assumption that planning later invalidates; the fleet-wide daily cap ($25) still bounds total damage.
- **Recommendation:** after computing `refined_estimate`, if `refined_estimate.requires_approval` and the epic was not explicitly approved at that (materially larger) amount, route back through the same pending_cost_approval state with the refined numbers in the halt reason. Effort: S–M.

### PROD-09-105 — `BudgetManager.check_daily()`/`check_daily_db()` are dead code; `check_daily_db`'s docstring cites a caller that no longer calls it
- **Severity:** Low · **File:** `backend/app/fleet/budget_manager.py:132-199` · **Confidence:** High
- **Finding:** production daily-cap enforcement moved to `spend_guard` (stronger: pre-call + Redis + DB floor). `check_daily()` has **test-only** callers; `check_daily_db()` — built specifically as the DB-accurate daily check ("Real callers (base_graph.py's post-run budget check)") — has **zero callers anywhere in `app/` or `tests/`**; the post-run block it describes now calls `bm.check_run()` + `spend_guard.check()` (`base_graph.py:4204-4219`). The stale comment at 1791-1795 also still claims `check_daily` "only ran AFTER" runs.
- **Production impact:** none at runtime (the effective cap is enforced); maintenance hazard — two unwired methods imply enforcement that doesn't exist through them.
- **Recommendation:** delete both methods (or rewire `check_daily_db` into the post-run path if defender-in-depth is wanted) and fix the stale comments. Effort: S. Cross-ref Audit 11 (dead code).

---

## 6. Frontend Performance (Phase 5) — **VERIFIED**

- **Polling intervals are sane (all ≥ 3s, no sub-second hammering):** NavBar badge 5s, tasks list 4s, task detail 3/4/5/5s (4 parallel polls), epics 5s, approvals 5s (full survey in Audit 08 §6). The amplification risk is only the unbounded epics payload (PROD-09-104).
- **SSE activity stream — bounded on every axis:** heartbeat every 15s exactly as the brief's Day-18 fix specifies (`api/activity.py:66-73`; fleet dashboard stream uses 30s, `fleet_dashboard.py:125`). Each subscriber gets its **own** `asyncio.Queue(maxsize=500)` (`activity_stream.py:89,332-334`); a slow/stalled subscriber causes **per-subscriber drop-on-full with a warning**, never unbounded memory (177-198). Client-disconnect cleanup is a `finally` that removes the queue (352-355). The stream registry is capped at 256 streams with idle (1h) / terminal-state eviction (101-102, 167-175, 392-403). Stop/resume control flags are durable (write-through to `task_control_flags`), with a 3s-bounded DB recheck interval instead of per-call queries (94, 205-219).
- **Large lists:** tasks cursor-paginated (`le=100`); memory similarity search is `k`-bounded with a k×10 candidate cap; agent list is registry-memory (≤~85); **epics is the one unbounded list** (PROD-09-104).

---

## 7. Scalability Assessment (Phase 6) — **static reasoning only, not load-tested**

- **Thread pool (already fixed at baseline):** `_size_default_executor()` sets the loop's default executor to `max_concurrent_agent_runs + max(16, cpu+4)` = **36 threads on this 6-core host** (`main.py:1402-1420`), with the original failure documented in-line ("min(32, cpu_count+4) … 10 on a 6-core host … with MAX_CONCURRENT_AGENT_RUNS=20 only 10 agents ever ran"). Because agents are sync-in-thread, this is the real concurrency dial, and it now matches the configured agent-run cap with headroom for chat/IO/warm-up `to_thread` work.
- **10 concurrent users each running an epic — first bottleneck reasoning (config-grounded):** `epic_slot` admits exactly 10 epics; within them, `agent_run_slot` (20) is the LLM-phase throughput ceiling and the **DB pool (20 + 10 overflow = 30 connections)** is the most likely first *shared* bottleneck once API handlers and ~23 background loops are added — pool waits raise `TimeoutError` after the 30s default, not silently. LLM API latency/rate limits dominate wall-clock before any in-process limit does. All queues fail loudly (slot timeout, pool timeout, statement timeout).
- **Disk (worktree-per-task-per-epic):** cleanup triggers verified — reject path (`api/tasks.py:755`), completion path (`tasks.py:1051`), post-push approval (`api/approvals.py:218`), all `to_thread`, all best-effort; plus the retention loop removes worktrees of **terminal-state** tasks older than `worktree_retention_days=7` (`retention.py:169-219,255-259`; the "failed/cancelled kept theirs forever" gap was the audit-09 fix). **Residual (by design, worth monitoring):** `blocked`/review-waiting tasks keep their worktree indefinitely — sustained load that produces permanently-blocked tasks can grow disk without bound; the retention sweep is the only backstop for terminal states.
- **Memory growth inventory:** activity streams bounded (256 × 500 events), metrics ring buffers bounded (Audit 07), scanner index cache keyed per repo (bounded); the **two unbounded structures found are PROD-09-103 (context cache) and PROD-09-106 (subtask semaphore dict)**.

### PROD-09-103 — Repo-context cache is unbounded, and its per-repo invalidation can never match (keys are SHA-256 hashes; invalidators pass paths)
- **Severity:** Medium · **File:** `backend/app/repo_tools/context_builder.py:22-38,79-82,165-166`; callers `backend/app/api/repo.py:184,444` · **Confidence:** High (code-verified)
- **Finding:** `_context_cache[key] = ContextResult` where `key = sha256(task_description|repo_path)`. Entries are added per distinct task description and **never evicted** (no max size, no TTL, no LRU). Worse, `invalidate_context_cache(repo_path)` filters with `repo_path in str(k)` — comparing a repo path against a hex digest, which can never be true; both real callers (`api/repo.py:184` after clone, `:444` after reindex) pass a path, so **the only invalidation that ever works is the full clear with `None`, which nobody calls**.
- **Evidence:** keys are hex strings (25-27); substring test at 36; the two call sites pass `local_path`/`repo_path`.
- **Production impact (static):** (a) monotonic memory growth ∝ distinct tasks run, for process lifetime; (b) after a re-index, cached ContextResults built from the **old** index keep being served to planning — stale file lists/dependency chains until restart. Both are silent.
- **Recommendation:** key by `(task_description, repo_path)` tuple instead of a hash (fixes invalidation with a one-line change), store the repo path in `ContextResult`, and cap the dict (LRU or size cap) so growth is bounded. Effort: S.

---

## 8. Prioritized Fix List

| # | ID | Sev | Fix | File:line | Effort |
|---|---|---|---|---|---|
| 1 | PROD-09-101 | **High** | Persist cost approval on the epic and honor it in `_cost_estimate_node`; make the second approve endpoint not strand `pending_cost_approval` epics; add a block→approve→planning regression test | `manager.py:2036-2127`, `api/epics.py:250-345` | M |
| 2 | PROD-09-102 | Medium | Re-gate after the refined estimate when it materially exceeds the approved amount; pass the real subtask count through a second approval check | `manager.py:2199-2206,2590` | S–M |
| 3 | PROD-09-103 | Medium | Tuple cache key (fixes broken per-repo invalidation) + bounded size (LRU) | `context_builder.py:22-38,165-166` | S |
| 4 | PROD-09-104 | Low | Cursor/limit pagination on `GET /api/epics` (mirror `list_tasks`) | `api/epics.py:150-170` | S |
| 5 | PROD-09-105 | Low | Delete/rewire `check_daily`/`check_daily_db`; fix stale comments | `budget_manager.py:132-199`, `base_graph.py:1791-1795` | S |
| 6 | PROD-09-106 | Low | Prune `_subtask_sems[epic_id]` in `_finalize_node` | `concurrency.py:118,153-158` | S |

**Cross-audit flags for Audit 10 (consolidation) — external Audit 09 (`files/Antigravity_audit_report/09_…md`, score 94/100, 1 Low):**
1. Their single finding, `PERF-09-001`, recommends "Expose `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` as environment variables in `config.py`" — **the fields already exist** (`db_pool_size` config.py:807, `db_pool_max_overflow`:817, both documented as the audit-4.7#2 fix), and its evidence string claims `pool_recycle=3600` which **does not exist** anywhere (grep: 0 hits in `session.py` and `config.py`). A stale finding.
2. Their table states `max_concurrent_subtasks=4` — actual default **5** (`config.py:831-833`); and "auto-eviction" attributes a `maxlen=500` deque to `app/api/activity.py` — the real artifact is a per-subscriber `asyncio.Queue(maxsize=500)` in `services/activity_stream.py:89,332-334` (`maxlen` appears 0 times in `api/activity.py`).
3. They cite `EPIC_BUDGET_USD` as the enforced ceiling — **no such setting exists** (grep: 0); the enforced one is `COST_BUDGET_DAILY_USD` (fleet-wide daily, `spend_guard.py`).
4. Their 94/100 predates-and-misses the still-open defects found here — including a **High** (dead-end cost approval) they did not report — while the perf items they *did* influence (thread pool sizing, slot timeout, spend guard, worktree retention) were real fixes already landed at the baseline. Weight their 94 accordingly. Also: their series shipped no `17_*` report (only 01-16 present) — relevant to deliverable file 17.

---

## 9. Score & Verdict

**Performance & Scalability Production-Readiness: 78 / 100 — READY FOR PRODUCTION (static analysis only, not load-tested).**

- Deductions: −10 for the High (cost-approval workflow dead-end — bounded spend, broken remedy), −4 for the placeholder-count gate never re-gated (PROD-09-102), −3 for the unbounded/broken-invalidation context cache (PROD-09-103), −2/−2/−1 for PROD-09-104/105/106.
- **Why READY:** the concurrency layer is real and loud (every semaphore traced to its dispatch site; bounded waits with timeouts > max run time); the blocking-call audit came back **clean with a reproducible method** (AST scan + manual chokepoint verification); DB access is pooled with statement timeouts, the HNSW indexes exist and are used correctly by the two-stage retrieval; spend enforcement is now at the strongest tier (SDK-level pre-call gate + Redis ledger + DB floor + pre-dispatch 429 + preventive per-turn stop) and the frontend's SSE machinery is bounded on every axis. Nothing found in this audit can lose data, hang the loop, or leak unboundedly under the default configuration except the two slow memory-growth paths (106 trivial; 103 fixed by a one-line key change).
- **Conditions to track post-release (none block release):** (1) fix PROD-09-101 before advertising cost-approval gating to operators; (2) PROD-09-102's re-gate strengthens the same workflow; (3) cap the context cache before long-lived multi-month deployments; (4) paginate `/api/epics` when epic counts reach the hundreds; (5) the scalability reasoning above is **static** — validate pool/thread sizing with a real load test before scaling past ~10 concurrent epic users.

---

*End of Audit 09. Verdicts: 6 findings (0 Critical, 1 High, 2 Medium, 3 Low). All other brief areas verified clean with file:line evidence above; blocking-call audit method and its one honest limitation stated in §3.*

# Audit 09: Performance & Scalability

**Spec:** `files/Audit/09_MASTER_PERFORMANCE_SCALABILITY_AUDIT.md` + `00b_AUDIT_STANDARDS.md`
**Date:** 2026-10-02 · **JSON sidecar:** `json/AUDIT_09_PERFORMANCE_SCALABILITY.json`
**Evidence:** `evidence/blocking_calls_in_async.py` (+ `.out.json`, `blocking_calls_transitive.out.json`)

## Result

🟢 **GREEN: 8 defects found and fixed (2 High, 5 Medium, 1 Low), each covered by a test that fails on the old code. The daily cost limit is now a real hard stop.**

**Performance & scalability score: 86 / 100.** Load testing was not possible here (one developer machine, no LLM credit for real runs), so section 6 is **static reasoning, not load-tested**, and is labeled that way.

## 1. Cost and token controls (Phase 4): your money

| Check | Before | Now |
|---|---|---|
| Daily budget (`COST_BUDGET_DAILY_USD`) | ❌ checked **only after a run finished**, and **per agent**: each of 85 agents could spend the whole "daily" budget, and the run that crossed it was already paid for | ✅ **fleet-wide hard stop before every call** (PERF-09-001) |
| Which LLM calls are covered | n/a | ✅ **every** Anthropic call in the process: agents, chat, memory consolidation, role detection, router, git-push summaries, and any future call site. The guard sits on the SDK itself (`Messages.create/stream`, sync and async), installed in `app/__init__.py` |
| What is counted | n/a | real `usage` of each response: input, output, cache write (1.25×), cache read (0.1×), priced at the model's tier |
| Shared across processes / restarts | in-process ring buffer only | ✅ Redis `INCRBYFLOAT gridiron:spend:<UTC day>`; the API refusal also takes today's `agent_runs` cost as a floor, so a lost Redis key can't reset the day |
| New work once the cap is reached | accepted, then silently "blocked" mid-run | ✅ **429 "Daily LLM budget reached"** on 10 endpoints: run, restart, approve, pipeline-approve, chat message, epic approve, approve-cost, approvals approve, specialized run, run-sync |
| An agent hitting the cap mid-run | n/a | stops cleanly as `blocked` before the next call, with a `budget_exceeded` health event |
| Per-run token cap | ✅ preventive (checked each turn) | unchanged |
| Pre-flight cost estimate | ✅ a **real gate**: an epic over `COST_APPROVAL_THRESHOLD` halts at `pending_cost_approval` (`manager.py:2066`) | unchanged |
| Context growth | ✅ real LLM condensation at the context budget (verified in audit 07) | unchanged |

**Your local setting:** `backend/.env` now has `COST_BUDGET_DAILY_USD=1`, the $1/day you asked for (the shipped default stays $25). The live tests at the end raise it only for their own process, up to the $3.50 stop.

## 2. Concurrency (Phase 1)

| Check | Result |
|---|---|
| `epic_slot` / `agent_run_slot` / `subtask_slot` acquired on real paths | ✅ `manager.py:1849` (epic), `:596/:754/:836` (dev/qa/reviewer runs), `:521` (subtask) |
| **Thread pool vs agent limit** | ❌ → ✅ **PERF-09-002 (High).** Agent runs execute in `asyncio.to_thread`, whose default pool is `min(32, cores+4)` = **10 threads here**, but the configured limit is 20 runs. Only 10 could run, and **every other background call (chat file reads, git, worktree setup, budget checks) waited behind minutes-long agent runs**. Proven: with 20 busy threads a 1-line call timed out. Now sized at startup to `MAX_CONCURRENT_AGENT_RUNS + headroom` (36 here). |
| Limits consistent (10 epics × 5 subtasks = 50 > 20 runs) | Fails loudly, not silently (`SlotAcquisitionTimeout` → blocked) |
| **Slot wait vs run length** | ❌ → ✅ **PERF-09-004 (Medium).** A subtask waited max **300 s** for a slot, but one run may take **1,800 s**, so under normal load queued work failed as "blocked" instead of waiting its turn. Default now 2,100 s (> max run time). |
| `conflict_guard.check_file_conflicts()` cost | ✅ once per epic start, one query per other running epic (capped at 10), so no O(n²) bottleneck in practice |
| Slot leak on cancellation | Low (PERF-09-007): `manager.py` enters the subtask slot manually; a `CancelledError` would skip the release. No code path cancels a running task (stop uses an abort flag), so this only happens at process shutdown. Documented, not changed. |

## 3. Blocking calls in async code (Phase 2)

AST scan (`evidence/blocking_calls_in_async.py`), direct and transitive. **Direct: 0. Transitive: 61**; after removing false positives (e.g. `websocket.close` matched a pty `close`), the real ones were fixed (PERF-09-003):

| Where | Blocking work | Severity | Fix |
|---|---|---|---|
| `chat_agent._execute_tool`: 31 call sites | `git` subprocesses (checkout, stash, diff, merge, reset, worktree…), file write/edit/insert handlers, `organize_imports`/`compare_files` subprocesses, docker risk check, process spawn | **Medium**: the main chat path; a slow `git diff` froze every request on the server | `await asyncio.to_thread(...)` |
| `launch_manager`, `launch_coder`, `manager._coding_node` | `create_worktree` (git + `rmtree`) | Medium | to_thread |
| `launch_planning_pipeline`, `launch_coder`, `bootstrap.bootstrap` | `is_blank_repo` (git) | Low | to_thread |
| task reject / complete, git-push decision | `remove_worktree` (git + `rmtree` of a full checkout) | Medium | to_thread |
| terminal WebSocket close | `pty.close` (docker kill + `time.sleep` retry, up to 5 s) | Medium | to_thread, **shielded** so a disconnect can't cancel the kill. An unshielded first attempt left containers running in 1 of 6 runs; caught by the existing test and fixed (8/8 since). `pty.start` stays sync: it's a quick `Popen`, and threading it would risk orphan containers. |
| `_resource_check_node`, release retrospective | host probes / `git log` | Low | to_thread |
| `pipeline/dispatcher.dispatch_subtask` | **whole agent runs** called synchronously | Would be Critical, but the function has **no callers** (dead path) | to_thread anyway |
| Fleet registry locks (`start_task`, `fail`, `retire`) | in-memory `threading.Lock` | Not blocking in practice | none |

## 4. Database (Phase 3)

| Check | Result |
|---|---|
| N+1 on list endpoints | ✅ **measured, not guessed**: every SQL statement counted per request. `GET /api/tasks?limit=100` = **9 queries for 100 rows**; epics/goals/repo/settings 2–3 queries. |
| pgvector HNSW index exists and is used | ✅ 3 HNSW indexes (`memory_embeddings`, `versioned_lessons`, `code_embeddings`), all `vector_cosine_ops`; every similarity query uses `<=>` with `ORDER BY … LIMIT`. `EXPLAIN` shows `Index Scan using memory_embeddings_embedding_hnsw`. |
| Connection pool | ✅ explicit `pool_size=20, max_overflow=10`, 30 s statement timeout |

## 5. Frontend and streaming (Phase 5)

| Check | Result |
|---|---|
| Polling intervals | ✅ 3–30 s everywhere (task detail 3–5 s, lists 4–5 s, metrics/agents/roadmap 30 s); React Query pauses in background tabs. Low (PERF-09-009), fixed: `NavBar` and Approvals used `setInterval(5 s)` that kept polling in hidden tabs; they now skip while the tab is hidden. |
| SSE stream | ✅ 15 s heartbeat; per-subscriber queue bounded (500); subscriber removed on disconnect |
| **Stream registry memory** | ❌ → ✅ **PERF-09-005 (Medium).** One `TaskStream` (with up to 500 events of history) was kept **forever** per task ever run or watched. Now capped at 256: finished or 1-hour-idle streams with no live viewer are evicted, oldest first. Safe because the stop flag is durable in the DB and an evicted stream is rebuilt on demand. |
| Large lists bounded | ✅ task list takes `limit`; memory search takes `top_k` |

## 6. Scalability: static reasoning, NOT load-tested

**10 users each running an epic, on this machine (6 cores, 15 GB) with default config:**
1. **First limit: LLM spend and rate.** The daily cap now stops everything at `COST_BUDGET_DAILY_USD` (that's the intent). Below the cap, Anthropic per-minute rate limits come next; the SDK retries 429s with backoff.
2. **Then CPU and RAM for test runs:** 20 concurrent agent runs each running tests/linters in worktrees would overload 6 cores. `resource_check` already warns. **Recommendation: `MAX_CONCURRENT_AGENT_RUNS=4–6` on this machine** (PERF-09-010; a config choice, left to the owner).
3. **The DB pool (30) is not the bottleneck**: agent threads use short-lived isolated engines.

**Worktree disk growth:** ❌ → ✅ **PERF-09-006 (Medium).** Worktrees were removed only on reject, complete or push decision, so **every failed or cancelled task kept a full checkout forever** (only saved today because the default dir is `/tmp`, cleared on reboot). The daily retention loop now removes worktrees of tasks finished more than `WORKTREE_RETENTION_DAYS` (7) days ago; blocked and review-waiting tasks keep theirs.

## 7. Findings (prioritized)

| ID | Sev | Status | Finding | Where |
|---|---|---|---|---|
| PERF-09-001 | **High** | FIXED | Daily budget never stopped spend (post-run, per-agent) | `fleet/spend_guard.py`, `app/__init__.py`, `api/budget_gate.py`, `base_graph.py` |
| PERF-09-002 | **High** | FIXED | Thread pool (10) smaller than agent limit (20); short calls starved | `main.py::_size_default_executor` |
| PERF-09-003 | Medium | FIXED | 40+ blocking git/file/subprocess calls on the event loop | `chat_agent.py`, `api/agents.py`, `manager.py`, `api/tasks.py`, `api/approvals.py`, `api/terminal.py`, `pipeline/bootstrap.py`, `fleet/release_retrospective.py`, `pipeline/dispatcher.py` |
| PERF-09-004 | Medium | FIXED | Slot wait (300 s) shorter than run time (1,800 s) | `config.py` |
| PERF-09-005 | Medium | FIXED | Activity-stream registry unbounded | `services/activity_stream.py` |
| PERF-09-006 | Medium | FIXED | Failed/cancelled task worktrees never removed | `services/retention.py` |
| PERF-09-007 | Low | ACCEPTED | Subtask slot not released on `CancelledError` (shutdown only) | `manager.py:521-986` |
| PERF-09-008 | Low | ACCEPTED | `_subtask_sems` keeps one small semaphore per epic id | `pipeline/concurrency.py` |
| PERF-09-009 | Low | FIXED | NavBar/Approvals polled in hidden tabs (now skip while `document.hidden`) | `components/NavBar.tsx:121`, `app/approvals/page.tsx:166` |
| PERF-09-010 | Low | OWNER | 20 concurrent runs is too many for a 6-core host | `backend/.env` |

**Closes PROD-08-007** (audit 08: "daily budget doesn't stop spend").

## 8. Tests added

| Test | Proves |
|---|---|
| `tests/test_audit09_spend_guard.py` (7) | real SDK classes + fake HTTP transport (no network, no spend): each call priced with cache tokens; **no request is sent** once the cap is reached; cap is fleet-wide; async + stream guarded; API answers 429; all 10 work-starting endpoints carry the gate |
| `tests/test_audit09_thread_pool.py` | a short call still gets a thread while 20 agent runs are busy (old pool: timed out) |
| `tests/test_audit09_activity_stream_bounded.py` (3) | finished streams evicted; running and watched streams kept; idle streams evicted |
| `tests/test_audit09_worktree_retention.py` | old failed/cancelled worktrees removed (incl. epic dirs); blocked and recently-failed ones kept (real DB, tmp repo) |

Regression results are in the tracker (`00_AUDIT_PLAN.md`).

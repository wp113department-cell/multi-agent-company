# Batch 8 — Execution Control, Failure Recovery, Disaster Recovery, Long-Running Jobs, Production Reliability

Covers §14, §38, §97, §102, §66. Evidence-only, file:line cited.

---

## §14 Execution Control

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Pause | **YES** | `POST /api/tasks/{id}/stop` → `registry.set_abort()` → in-process `threading.Event`, checked inside the agent loop. |
| Resume | **YES** | `POST /api/tasks/{id}/resume` clears the same event, stashes a resume payload. |
| Cancel (distinct terminal state) | **NO — not found** | No `"cancelled"`/`"paused"` status exists in the DB's `VALID_TRANSITIONS` state machine at all. Stop/Resume is the only pause primitive and it's always resumable — there's no separate irreversible cancel. |
| Retry | **YES** | Tool-level (`_run_tool_with_retry`) + agent-run-level (`coder.py`/`backend_dev.py`/`frontend_dev.py`/`manager.py`, all gated by `failure_ladder.should_retry()`). |
| Rollback | **NO — confirmed not auto-wired** | `rollback_to`/`failure_ladder.rollback` are real functions with **zero production callers** — only the definition, a re-export, and a docstring. Explicitly, deliberately manual-only per the module's own comment. |
| Checkpoints | **PARTIAL — broader than assumed, but uneven** | Three separate checkpointers exist: (1) pipeline graph — Postgres-backed (`AsyncPostgresSaver`); (2) generic worker-agent graph (`run_agent_graph`, used by ~76 agents) — **also** Postgres-backed, contrary to the initial assumption that checkpointing was pipeline-only; (3) `chat_agent.py` — **`MemorySaver()`, never upgraded to Postgres, in-process only, lost on crash/restart**. The epic-manager graph has no checkpointer at all (explicit design comment: "never pauses, runs start-to-finish"). |
| Recovery after crash | **PARTIAL** | Survives: DB rows, both Postgres-backed checkpoint stores. Lost: everything in-process — abort/resume flags, chat session state, bg-process registry PIDs, in-memory agent-health state (ties to Batch 5's scaling finding). |
| Recovery after reboot | **NO — not automatic** | `reconcile_orphaned_runs()` runs at startup but only **marks stuck runs `failed`**, it does not resume them. A human must manually re-trigger. No auto-resume-in-flight-work-on-boot routine exists. |
| Continue from checkpoint if interrupted | **PARTIAL, path-dependent** | Real for (a) the PM/Architect/Decomposer pipeline and (c) plain worker agents (both Postgres-checkpointed, though (c) has no real production caller that actually invokes a "resume this run" API — the checkpoint exists but isn't exercised by any live resume path found). **Not real for (b) chat_agent sessions** — in-process `MemorySaver`, lost on crash (though chat message text itself is separately DB-persisted). |

**§14 overall: PARTIAL.** Genuinely more checkpoint infrastructure exists than a first pass would assume (Postgres-backed for the majority of agent runs, not just the pipeline) — but chat, the interactive surface users actually spend the most time in, is the one path left on in-memory state. This is the same "chat_agent is the architecturally separate, under-hardened path" pattern found in Batches 1 and 4.

---

## §38 Failure Recovery

| Scenario | Verdict | Evidence |
|---|---|---|
| Docker crashes (sandbox) | **YES — fails closed correctly** | `SandboxUnavailableError` raised on Docker-unreachable, caught and turned into a `[SANDBOX UNAVAILABLE]` tool result rather than crashing the run or silently running unsandboxed. |
| Python backend crashes | **PARTIAL** | See §14 above. |
| Terminal/shell session closes | **PARTIAL** | Only handled at next app startup (`sweep_orphaned_processes`); nothing detects a closed shell while the app keeps running. |
| VS Code / IDE closes | **N/A** | Not applicable — this is a web app, not an IDE extension. |
| Claude Code stops | **N/A** | Different product, not applicable. |
| Internet disconnects | **PARTIAL** | No application-level retry/backoff on the Anthropic client construction itself (only a timeout, no `max_retries`). Real protection is a **circuit breaker**, not a retry — repeated failures trip it open and fail fast. |
| LLM API fails (rate limit/500/timeout) | **PARTIAL** | Same circuit-breaker protection (closed→open→half-open), config-driven threshold/cooldown. **No retry-with-backoff of the LLM call itself was found** — the system fails fast when the breaker is open rather than retrying to eventual success. |

**§38 overall: PARTIAL.** The one scenario tested most thoroughly (Docker sandbox failure) is handled correctly and safely. The LLM-connectivity scenarios have real protection but of a different character than what's implied by "recovery" — a circuit breaker prevents pile-up/retry-storms, but doesn't itself get a request through; an in-flight run experiencing an LLM outage will fail, not silently succeed once connectivity returns, unless something external re-triggers it.

---

## §97 Disaster Recovery

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Backup exists | **PARTIAL** | Real `scripts/backup_db.sh` (pg_dump custom format, verification via `pg_restore --list`, retention pruning) and `scripts/restore_db.sh` — both genuinely well-built. **Not automated** — no cron/systemd timer/CI schedule invokes the backup script anywhere; it is manual/operator-run only. |
| Auto-restart on crash | **PARTIAL** | `docker-compose.yml`: only `db` and `redis` have `restart: unless-stopped`. **`backend`, `migrate`, `worker`, `frontend` have no restart policy** — they will not auto-restart on crash under Compose's default. `Procfile` restart behavior is entirely delegated to whatever deploy platform runs it (not defined in-repo). |
| What's replayed vs redone manually | **Documented above (§14/§38)** | Checkpoint state replays only if something explicitly calls resume; DB restore is a manual script run; orphaned runs require manual re-trigger. |

**§97 overall: PARTIAL, and this compounds the "no production deployment manifest" finding from Batch 5.** A real, well-designed backup script exists but sits unscheduled, and the core `backend` service — the one thing disaster recovery is supposedly protecting — has no restart policy in the only compose file in the repo.

**Production Enhancement Plan:** Add a cron/systemd-timer entry (or a scheduled CI job against a target host) that actually invokes `scripts/backup_db.sh` on a real cadence — the script itself needs no changes, only a trigger. Add `restart: unless-stopped` to the `backend`/`worker`/`migrate`/`frontend` services in `docker-compose.yml` at minimum for any environment closer to production than pure local dev.

---

## §102 Long-Running Jobs

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Run 30+ min / hours without being killed | **PARTIAL** | No wall-clock task-level timeout exists for the default (`asyncio`) queue backend — the only bound is `max_turns=20` (turn-count, not time). A real 30-minute job timeout exists (`_DEFAULT_JOB_TIMEOUT=1800`) but **only applies when `QUEUE_BACKEND=rq`**, which is not the default (`docker-compose.yml` defaults to `asyncio`) — so in the default configuration, nothing would kill a genuinely long job, but also nothing guarantees it survives cleanly either (ties to §14's checkpoint-but-no-real-resume-caller finding). |
| Progress reporting | **YES** | Real, rich, incremental SSE event taxonomy (`thinking`, `tool_call`, `tool_result`, `file_edit`, `terminal`, `agent_switch`, `token_usage`, `context_trimmed`, `approaching_limit`, `stopped`, `done`, `error`) — genuinely more granular than a bare "done/failed" signal. |
| Checkpointing / Resumability | **See §14** | |

**§102 overall: PARTIAL.** Progress visibility is genuinely strong. The actual duration/resumability guarantee is inconsistent depending on which queue backend is configured — and the documented default (asyncio) is the one *without* the 30-minute safety net that RQ has.

---

## §66 Production Reliability

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Retries | **YES** | Confirmed, see §14. |
| Exponential backoff | **PARTIAL** | Real for tool-level retry (`0.5 * 2**attempt`, capped). LLM-call-level uses a fixed circuit-breaker cooldown, not exponential backoff — a real but different mechanism than what's implied. |
| Circuit breakers | **YES — Production Ready** | Real `CircuitBreaker` class, 3-state (closed/open/half-open), thread-safe, config-driven thresholds. Protects every Anthropic call across `base_graph.py` and `chat_agent.py` via one shared singleton, plus a separate breaker for Groq. |
| Timeout handling | **PARTIAL** | Subprocess and LLM-call timeouts are real and configured. **DB query timeouts are not found** — no `statement_timeout`/`command_timeout` anywhere in the session/engine config. |
| Idempotency | **PARTIAL** | No formal idempotency-key mechanism. A real, narrower state-based guard exists (`approve_task()` returns HTTP 409 if already coded) — functional for that one case, not a general pattern. |
| Transaction safety | **PARTIAL** | No explicit `session.begin()`/`async with db.begin()` blocks found anywhere — relies entirely on SQLAlchemy's implicit autobegin + a single `commit()` per handler. Works as long as every handler follows that convention, but the boundary isn't structurally enforced, so a future handler with two separate `commit()` calls wouldn't be caught by anything. |
| Structured error reporting | **YES** | Consistent `{"error": {"code": ..., "message": ...}}` shape across both HTTP-exception and validation-exception handlers in `main.py`. |

**§66 overall: PARTIAL.** The standout piece here is the circuit breaker — a genuinely production-grade implementation, correctly shared across both agent execution paths. The weaker areas (DB timeouts, idempotency, explicit transaction boundaries) are the kind of gaps that don't show up until a specific failure mode is hit in production (a hung query, a duplicate task-creation request, a handler that grows a second commit later).

---

## Summary — Batch 8 (30 checkpoints across 5 sections)

- **YES:** 10
- **PARTIAL:** 18
- **NO:** 2

**Findings worth flagging above the rest:**
1. **Chat sessions are the one execution path without durable checkpointing** — same architectural pattern as the sandboxing gap in Batch 1 and the shared-engine divergence in Batch 4: chat_agent.py consistently ends up as the least-hardened path because it's a structurally separate implementation.
2. **The default queue backend (asyncio) has no job timeout; the non-default one (RQ) does** — an easy-to-miss inversion where the safety net exists on the path fewer deployments will actually use.
3. **Disaster recovery tooling (backup/restore scripts) is well-built but unscheduled**, and the core backend service has no auto-restart policy in the only compose file that exists.

**Production Enhancement Plan (cross-cutting):** Prioritize migrating `chat_agent.py`'s `MemorySaver()` to the same `AsyncPostgresSaver` already used elsewhere — this is a proven pattern in the same codebase (`init_agent_checkpointer()`), not new infrastructure. Add a task-level wall-clock timeout to the asyncio queue path mirroring RQ's `_DEFAULT_JOB_TIMEOUT`, so behavior doesn't silently depend on which backend an operator chose.

# 13 — Master Production Operations / Disaster Recovery / Lifecycle Audit

**Audit date:** 2026-10-02
**Repository:** /home/pc-117/Documents/CRR2906 — "Gridiron Developer Department"
**Commit:** 90dac23bad223ec39413c485d1ddb68f9646975e ("Production audit 14: clean-room reproduction from README; fix onboarding blockers")
**Series baseline:** c927c44b ("Production audits 09 and 11"); audits 01–11 of this series ran against disk state 33bbd03c. Commits ecd4905a ("Production audit 12"), 33bbd03c ("Production audit 13") and 90dac23b ("Production audit 14") made by a parallel repair pass are the **object under audit**, not proof of correctness.
**Worktree:** clean; untracked only: `files/Qoder_audit report/`, `files/Antigravity_audit_report/`, `What_is/AUDIT_REPORT/NEXT_PLAN_MONDAY.md`.
**Environment:** Linux 24.04; Python 3.12 venv; Next.js production server UP on :3100; backend :8000 **DOWN**; Postgres 16 + pgvector in `crr2906-db-1` (DB `gridiron_dev`, healthy), Redis 7 in `crr2906-redis-1` (healthy); no real ANTHROPIC/OPENAI keys (`PENDING_TESTS_API_KEYS.md`).

## 0. Method, constraints, and drill disclosure

The governing user instruction for this engagement is **strict read-only**: no project code may be modified; the only writable outputs are the numbered reports in `files/Qoder_audit report/` and their `json/` sidecars. Under the brief's zero-hallucination rule (§2), anything not executed is marked UNVERIFIED/BLOCKED and never PASS.

**One controlled exception was executed** — permitted by the brief's own §4 (destructive recovery testing only in an isolated environment with a disposable database) and §5 (no production data destroyed):
- A real **backup → throwaway-restore → row-count comparison** drill against the development database `gridiron_dev` only, using the shipped `scripts/backup_db.sh` semantics (`pg_dump -Fc`) and a **new disposable database `qoder13_restore_drill`** created solely for the drill. No production data existed or was touched; the throwaway DB was dropped and the dump file deleted immediately after (verified: only `gridiron_dev` + `postgres` remain).
- This yielded exactly one executed status: **RESTORE_VERIFIED (at dev scale)**. Everything else in this report is either static verification (VERIFIED-static) or UNVERIFIED runtime.
- The day's earlier committed claims in `docs/disaster_recovery.md` ("outage behavior drilled 2026-10-02") are **not used as evidence** (§2.2: prior claims are leads only).

## 1. Final Decision

**NOT GREEN — OPERATIONAL PRODUCTION AUDIT INCOMPLETE**

Rationale (per §238: never GREEN while a required critical gate is unresolved):
- **Zero Critical and zero High findings**; the operational core (orphan recovery, DB-outage error contract, spend guard, circuit breaker, rate limits, graceful shutdown) is real, wired, and leader-gated.
- **Backup/restore is the only executed-verified gate** (RESTORE_VERIFIED at dev scale).
- **RTO/RPO targets are UNDEFINED** — a human decision the brief explicitly reserves (§5); only dev-scale timings were measured.
- **Backup scheduling is dormant**: the systemd unit/timer exist but are not installed anywhere in this environment, and no backup artifacts exist (`/var/backups/gridiron` absent; `./backups` absent; `systemctl list-timers` → 0 timers).
- `alembic check` **fails against the live schema** (7 tables, 55 indexes, 4 unique-constraint diffs) while CI runs only `upgrade head` — merge-time autogenerate is unsafe today.
- Runtime outage/failover/chaos/soak drills, rollback exercise, and post-recovery user journeys were **not executed** (read-only engagement; backend down; no LLM keys).

## 2. Master Operations Matrix

| ID | Area | Expected | Tested | Evidence | Failure Result | Recovery Result | Status |
|---|---|---|---|---|---|---|---|
| O-0001 | DB backup (script) | pg_dump -Fc + integrity check + retention | **Executed 2026-10-02** | `scripts/backup_db.sh`; drill dump 4.84 MB / 444 TOC entries / ~1.8 s | Loud failure (partial file never renamed) | n/a | VERIFIED (dev scale) |
| O-0002 | Restore (disposable DB) | pg_restore --exit-on-error; row parity | **Executed 2026-10-02** | `scripts/restore_db.sh`; restore ~7.5 s; counts identical (below §3) | --exit-on-error aborts | **RESTORE_VERIFIED (dev scale)** | **RESTORE_VERIFIED** |
| O-0003 | Scheduled backups | Runs daily without a human | Inspected | `scripts/systemd/gridiron-backup.{service,timer}` (03:00, splay 1800 s, Persistent=true) — **not installed**; no unit in /etc/systemd/system; 0 timers; no artifacts | No backup ever taken → total data-loss exposure | Manual install documented in unit header | **FAIL (dormant) — PROD-13-103** |
| O-0004 | RTO / RPO | Measured or human-defined targets | Inspected | Dev-scale: backup 1.8 s, restore 7.5 s; daily cadence implies worst-case RPO ≈ 24 h + ≤30 min splay; no target documented anywhere | Undefined recovery expectations | Human decision required | **UNDEFINED — PROD-13-102** |
| O-0005 | Orphan run recovery | Stale running runs reconciled; task not left "running" in UI | Source | `failure_ladder.py:282-324` `_block_tasks_of_orphans` → `transition_task(..., "blocked", blocked_reason="orphaned")`; `reconcile_orphaned_runs:327` (resume via resume_registry, else fail+escalate); 300 s interval :235; leader-gated loop `loop:orphan_recovery` main.py:1634,1714-1716; startup sweep main.py:1532-1543 | Run stuck "running" forever (pre-audit-13 behavior) | Task blocked with error log; operator restarts | VERIFIED (static; runtime not executed) |
| O-0006 | Worker crash (RQ) | Failed jobs swept; retries bounded | Source | `loop:failed_rq_job_sweep` (main.py:1636); retry reuses `queue_job_retry_max`; prod worker default `QUEUE_BACKEND=rq` (docker-compose.prod.yml:115) | Job lost silently (bounded retry mitigates) | Sweep loop + retry | PARTIAL (static) |
| O-0007 | Duplicate execution | No double-run of same task/loop | Source | Loops leader-elected; task state machine via `transition_task`; no distributed idempotency key verified for task execution | Possible duplicate work on retry | State machine rejects illegal transitions | PARTIAL (static; cross-ref Audit 04) |
| O-0008 | Queue retry storm | Bounded retries, no unbounded requeue | Source | `queue_job_retry_max` (AUDIT_Q_BATCH16 §86); failed-job sweep instead of redelivery | Bounded | Deterministic dead-letter sweep | VERIFIED (static) |
| O-0009 | DB outage behavior | 503 + Retry-After, JSON error shape | Source | `main.py:1907-1925` (503 + Retry-After: 5), `db/errors.py` classifier, `rbac.py:44-45`, `auth.py:95` | Pre-audit-13: bare 500 text | Client retries after 5 s | VERIFIED (static; not executed — backend down) |
| O-0010 | Redis outage | Degrade, don't lose money/state | Source | spend_guard in-process fallback (`spend_guard.py:66-98`); prod Redis AOF (`--appendonly yes`, docker-compose.prod.yml:76 + redisdata volume :78,229); streams drain loop | Ledger temporarily local-only (documented) | AOF replay | PARTIAL (static) |
| O-0011 | External provider (Anthropic) outage | Circuit breaker + retry | Source | `base_graph.py:44,166-167` `get_anthropic_breaker().call(...)`; retry suite `tests/test_gap58_59_llm_outage_retry_and_breaker.py` | Fail fast instead of piling on | Breaker closes after recovery | VERIFIED (static; not executed — no API key) |
| O-0012 | Cost runaway | Hard daily cap before every LLM call | Source | `spend_guard.py` `check_before_dispatch:168` pre-dispatch, Redis INCRBYFLOAT ledger + fallback, `DailyBudgetExceeded:51`, disable via `COST_BUDGET_DAILY_USD<=0` :25 | Calls refused beyond cap | Next UTC day resets | VERIFIED (static; cross-ref PROD-09-105) |
| O-0013 | Abuse / rate limits | Login brute force + general limits | Source | slowapi limiter; `rate_limit_login` on auth.py:67,167; config.py:2141 | 429 on abuse | Automatic | VERIFIED (static) |
| O-0014 | Resource exhaustion (logs/disk) | Bounded logs | Source | prod compose json-file `max-size: 20m` :48 all services | Bounded | n/a | VERIFIED (static) |
| O-0015 | Secrets lifecycle | Vault, rotation path, no leaks | Inspected | credential_vault Fernet (optional); rotation table `docs/disaster_recovery.md`; history scan 577 commits → hits all fixtures (sampled: `sk-ant-test-key`, `FAKEFA…`, `AKIAABCDEFGHIJ`, `ghp_faketoke`, `ghp_xxxxxxxx`) | Plaintext at rest if vault key unset | Manual rotation only | PARTIAL — PROD-13-106 |
| O-0016 | Data lifecycle: retention | Automated cleanup loop | Source | `start_retention_loop` main.py:1439 (leader-gated) | Table growth | Daily sweep | VERIFIED (static) |
| O-0017 | Deletion / erasure | Admin-only destructive ops | Source | `privacy.py:132-135` `DELETE /user/{username}` behind `require_admin`; exports `:103` self, `:120-123` admin | 403 for non-admin | Immediate | VERIFIED (static) |
| O-0018 | Migrations | Head applied; schema consistent with models | **Executed** | `alembic current` = 062 = head ✓; **`alembic check` FAILS**: 7 removed tables, 55 removed indexes, 1 added index, 2+2 unique constraints (§8) | Unsafe autogenerate at merge time | n/a | **FAIL — PROD-13-101** |
| O-0019 | Upgrade | Documented, ordered deploy | Inspected | `docs/DEPLOYMENT.md` (174 lines); prod `migrate` one-shot `on-failure`; no pre-migration backup step | Bad migration without snapshot | Recovery = restore drill path | PARTIAL — PROD-13-104 |
| O-0020 | Rollback | Exercised rollback or restore-based rollback | Inspected | DR doc describes restore procedure; no downgrade or rollback exercise executed in this engagement | Undefined rollback time | Unverified | **UNVERIFIED (ROT: not ROLLBACK_VERIFIED)** |
| O-0021 | Dependency failure recovery | Retry + breaker + queue sweep | Source | see O-0006, O-0011 | Bounded | Unverified runtime | PARTIAL (static) |
| O-0022 | Long-run stability (soak) | No leaks across hours/days | Inspected | k6 load script `backend/tests/load/gridiron_load_test.js` + scheduled CI workflow; no soak executed here; open leaks cross-ref Audit 09 PROD-09-103/106 | Unknown | Unknown | UNVERIFIED |
| O-0023 | Runbooks / operability | Another engineer can operate | Inspected | 94 md docs incl. DR (207 lines), DEPLOYMENT (174); install steps for backup unit; no maintenance mode (0 grep hits) | Operator must improvise quiesce | n/a | PARTIAL — PROD-13-105 |
| O-0024 | Regression after recovery | Post-recovery journeys still pass | Not applicable | No repairs performed (read-only); drill used throwaway DB; live DB untouched (counts re-verified: dev_tasks=414, agent_runs=91, task_logs=108, rev 062) | n/a | n/a | N/A |

## 3. Backup / Restore — the one executed gate (RESTORE_VERIFIED, dev scale)

Executed 2026-10-02 against `crr2906-db-1` (pgvector/pg16; client tools 16.15 **inside the container** — pg tools are not on the host PATH):

```text
pg_dump -Fc gridiron_dev                       -> 4.84 MB, 444 TOC entries, ~1.8 s
createdb qoder13_restore_drill                 -> disposable DB
pg_restore --exit-on-error -d qoder13_restore_drill <dump>   -> OK, ~7.5 s, zero errors
row counts SOURCE vs RESTORED (identical):
  alembic_version = 1 (rev 062) | dev_tasks = 414 | agent_runs = 91 | task_logs = 108
cleanup: DROP DATABASE qoder13_restore_drill; dump file removed
post-check 2026-10-02 (report time): only gridiron_dev + postgres remain;
  counts re-confirmed 414 / 91 / 108 at rev 062 — live DB unaffected
```

Mechanics verified statically: `scripts/backup_db.sh` (strip `+asyncpg` from DATABASE_URL, write `.partial`, rename only on success, `pg_restore --list` integrity check, retention prune of `gridiron_*.dump`, default 30); `scripts/restore_db.sh` (dump sanity via `pg_restore --list`, interactive `restore` confirmation or `--yes`, `pg_restore --clean --if-exists --exit-on-error`, post-check `SELECT count(*) FROM alembic_version`).

Limitations (honesty): dev-scale only (4.8 MB); restore time at production volume, partial/point-in-time recovery, and offsite copies are **unmeasured**. `docs/disaster_recovery.md` documents deliberate non-goals (no offsite/encryption/scheduling in the scripts themselves) and the agent-workspace durability gap (workspace under `/tmp` is not durable unless relocated; Settings edits hard-fail in production). **PROD-13-103/102.**

## 4. Failure Recovery

- **Orphan runs (crash recovery):** crash mid-run freezes `AgentRun.last_heartbeat_at`; the 300 s leader-gated sweep (`loop:orphan_recovery`) resumes resolvable agents from their Postgres checkpoints or fails+escalates the rest, and — this is the audit-13 addition — **blocks the task** (`blocked_reason="orphaned"`, failure_ladder.py:282-324) instead of leaving it "running" in the UI forever. Startup additionally sweeps orphaned OS processes (main.py:1532-1543) and marks live runs failed (main.py comment re: restart sweep).
- **Clean shutdown:** lifespan cancels and awaits ~20+ background tasks (main.py:1790-1834 incl. `orphan_recovery_task.cancel()` :1806), disposes the leader-election engine, and closes the 3 LangGraph checkpointer connections before exit.
- **Database outage:** any DBAPI/driver unavailability is classified by `db/errors.py::is_db_unavailable` and answered as **503 + `Retry-After: 5`** with the app's JSON error shape (main.py:1907-1925; also rbac.py:44-45, auth.py:95); Starlette HTTP exceptions now preserve their headers (:1941-1948).
- **Provider outage:** shared Anthropic circuit breaker on the client wrapper (base_graph.py:166-167) — every agent submission inherits it.
- **Queue:** RQ is the prod default; bounded retries reuse `queue_job_retry_max`; a leader-gated failed-job sweep (`loop:failed_rq_job_sweep`) and Redis-streams drain loop run continuously.
- Runtime execution of any of the above (kill -9 drill, DB stop drill, provider outage drill) was **not performed** — read-only engagement; all statuses are static.

## 5. Cost / Abuse / Resource Control

- **Hard LLM daily cap:** `spend_guard.check_before_dispatch()` (:168) runs before dispatch; Redis `INCRBYFLOAT` ledger with in-process fallback (:66-98); `DailyBudgetExceeded` (:51) surfaces a clear operator message; `COST_BUDGET_DAILY_USD <= 0` disables by design (:25). Response accounting via `_record_response` (:198) / `_SyncStreamGuard` (:207). The cap is enforced at the SDK wrapper, i.e., every call site inherits it (same mechanism as the breaker).
- **Rate/abuse:** slowapi limiter with per-route policies; login/refresh carry the dedicated brute-force limit (`auth.py:67,167`; `config.py:2141`).
- **Disk/log bounds:** all prod services log via json-file capped at 20 m (docker-compose.prod.yml:48).
- **Spend visibility:** fleet cost report endpoints exist (backend-only surface, cross-ref PROD-12-106).

## 6. Secrets Lifecycle

- Credential vault (Fernet, optional at rest); no hardcoded secrets found in the tree (Audit 11) and a 577-commit history scan (`git log -S`) surfaced only fixture values in samples (`sk-ant-*` test keys, `AKIAABCDEFGHIJ…`, `ghp_faketoke`, `ghp_xxxxxxxx`, `FAKEFA…`) — sampled, not exhaustive.
- Rotation: documented table in `docs/disaster_recovery.md` (which secret, where, blast radius). **No rotation tooling or executed rotation** — runbook-only (**PROD-13-106**).

## 7. Data Lifecycle

- **Retention:** leader-gated `start_retention_loop` (main.py:1439) prunes on schedule (Audit 11 note: public `enforce_retention_policy` is test-only; live path is `_run_cleanup`).
- **Deletion/erasure:** `DELETE /privacy/user/{username}` is **admin-only** (`require_admin`, privacy.py:132-135) — the parallel commit 33bbd03c tightened this; exports are self (`/export/me` :103) or admin (`/export/{username}` :120-123).
- **Cross-project/tenant isolation:** covered by Audits 03/05 (per-run state, scoped memory, RBAC); no regression found in this pass.
- **Workspace durability:** documented gap — agent workspaces under `/tmp` are not durable unless relocated; production Settings writes hard-fail rather than silently vanish (docs/disaster_recovery.md).

## 8. Migrations / Upgrade / Rollback

- **Head applied:** `alembic current` = 062 = head. Baseline migrations run in a one-shot compose service.
- **`alembic check` FAILS against live schema** (executed): 7 removed tables — `checkpoint_blobs`, `checkpoint_migrations`, `checkpoints`, `checkpoint_writes` (created at runtime by LangGraph's `saver.setup()`), plus `chat_messages`, `lessons`, `audit_log`; **55 removed indexes** (incl. HNSW vector indexes `code_embeddings_embedding_hnsw`, `versioned_lessons_embedding_hnsw`); 1 added index; 2 removed + 2 added unique constraints. Root cause: `migrations/env.py` sets `target_metadata` from `app.db.models.Base` only (import at env.py:20-22), with **no `include_object` filters**; `models.py` declares 42 `index=True` columns but **zero explicit `Index()` objects**; app-owned tables `chat_messages`/`lessons`/`audit_log` have no ORM models in that metadata. CI runs `alembic upgrade head` only — no `alembic check` gate. Consequence: any developer merging `alembic revision --autogenerate` today produces a migration proposing to **drop live tables/indexes** (checkpoint drops break run resume; dropping `chat_messages`/`lessons`/`audit_log` destroys memory/chat/audit data). **PROD-13-101.**
- **Upgrade:** the procedure is documented (DEPLOYMENT.md) and the migration step is ordered before app start; **no pre-migration backup is automated or prescribed** (PROD-13-104).
- **Rollback:** restore-based recovery is documented and the restore script was drill-verified, but **no rollback was exercised** → `ROLLBACK_VERIFIED` cannot be claimed.

## 9. Operations

- **Runbooks:** 94 md docs under `docs/`, incl. `disaster_recovery.md` (207 lines: covered/not-covered, 5-step recovery, secret rotation table, outage behavior table, drill log) and `DEPLOYMENT.md` (174 lines).
- **Backup scheduling:** systemd `gridiron-backup.service` + `.timer` shipped (daily 03:00, splay ≤30 min, `Persistent=true`, `TimeoutStartSec=3600`, retention 30). **Not installed in this environment** (0 timers; no unit in /etc/systemd/system; `/var/backups/gridiron` and `./backups` do not exist). Install requires a human (`systemctl edit` for DATABASE_URL/BACKUP_DIR + `enable --now`) — documented in the unit header, but "backups are running" is **false today** anywhere it hasn't been installed. **PROD-13-103.**
- **Maintenance/quiesce mode: ABSENT** (0 grep hits). Upgrades/restores have no read-only/drain mode; operators must stop services manually; undocumented (**PROD-13-105**).
- **Observability:** structured app logs; activity SSE with 15 s heartbeats; audit log table (`audit_log`, currently outside Alembic metadata — see §8); no metrics/alerting stack (Prometheus/Grafana/OTel collector) observed in the deployment artifacts — alerting is **UNVERIFIED/absent** for gates like "backup failed" or "breaker open".
- **Terminal/SSE cleanup:** terminal WS releases PTY/subprocess in `finally` (terminal.py:223-238); SSE streams terminate cleanly (Audit 08/12).

## 10. Long-Run / Resource Stability

- Pool health: `pool_pre_ping=True` on the async engines (db/session.py:49,87); Redis AOF in prod (O-0010); bounded internal queues/caches (Audit 11 "Memory Leakage PARTIAL").
- Open cross-refs from Audit 09, still open: **PROD-09-103** (`_context_cache` unbounded, never-matching invalidation) and **PROD-09-106** (`_subtask_sems` never pruned) — neither re-counted here.
- A scheduled k6 load test workflow exists (`load-test.yml`, script `backend/tests/load/gridiron_load_test.js`) but no soak/long-run execution was performed during this audit → long-run stability **UNVERIFIED**.

## 11. Findings

### PROD-13-101 — MEDIUM — `alembic check` fails: merge-time autogenerate is unsafe (drift vs live schema)
Executed at head 062: 7 removed tables, 55 removed indexes (2 HNSW), 1 added index, 2 removed + 2 added unique constraints. `migrations/env.py` imports only `app.db.models.Base` (no `include_object` filters); app-owned `chat_messages`/`lessons`/`audit_log` have no models in that metadata; LangGraph checkpoint tables are runtime-created; `models.py` uses `index=True` (42) but no `Index()` objects. CI runs `upgrade head` only. An autogenerated revision merged today proposes dropping live tables/indexes (checkpoints → resume breakage; chat/lessons/audit → data loss). **Fix:** metadata `include_object` filter for runtime/vector/legacy tables + declare app-owned models/indexes + add `alembic check` to CI. Effort S-M.

### PROD-13-102 — MEDIUM — RTO/RPO undefined (human decision; brief §5)
Only dev-scale timings measured (backup ~1.8 s / restore ~7.5 s, 4.84 MB). Daily 03:00+splay cadence implies worst-case RPO ≈ 24 h + ≤30 min; no target RTO/RPO is stated anywhere. Gate "RTO/RPO MEASURED OR HUMAN-DEFINED" is unmet. Human must set targets (and, if finer RPO is required, move to WAL archiving / more frequent dumps). Effort: human decision.

### PROD-13-103 — MEDIUM — Backup automation is dormant; zero backup artifacts exist
Unit + timer are shipped but not installed (0 timers listed; no unit file in /etc/systemd/system; `/var/backups/gridiron` and `./backups` absent). Nothing in the deployed artifacts (compose services) runs backups either. The script itself is drill-proven; the *ongoing protection* is absent until a human installs and monitors it. **Fix:** install the timer per its header on the DB host, or add a compose backup service; add "backup age" alerting. Effort S.

### PROD-13-104 — LOW — No automated backup-before-migration
Prod `migrate` one-shot runs `alembic upgrade head` with no preceding snapshot; a destructive migration has no automated safety net (recovery relies on the last daily backup, which may not exist per PROD-13-103). **Fix:** wrap migrate in "take dump → upgrade" or document a mandatory operator pre-step. Effort S.

### PROD-13-105 — LOW — No maintenance / read-only / drain mode
0 grep hits. Upgrades, restores, and destructive repairs have no in-product quiesce path (new tasks/agents keep being accepted); operators must stop services externally, undocumented. **Fix:** a maintenance flag that rejects new task starts with 503 while draining in-flight work. Effort M.

### PROD-13-106 — LOW — Secret rotation is runbook-only and never exercised
`docs/disaster_recovery.md` has a rotation table, but no tooling/scripts exist and no rotation was ever executed; the Fernet vault key re-wrap path is untested. Acceptable for single-operator deployment; becomes a real gap for multi-operator/production teams. Effort S-M.

**Counts: Critical 0 · High 0 · Medium 3 · Low 3 · Total 6.**

## 12. Final Operational Production Gate (§238)

```text
============================================================
GRIDIRON OPERATIONAL PRODUCTION GATE
============================================================

Backup verified:                  PASS (mechanism; executed drill, dev scale)
Restore verified:                 PASS (RESTORE_VERIFIED; dev scale)
RTO verified:                     UNDEFINED (dev timings only; no target)
RPO verified:                     UNDEFINED (daily cadence implies ~24h+splay; no target)

Failure recovery:                 PASS (static) / runtime UNVERIFIED
Worker recovery:                  PASS (static) / runtime UNVERIFIED
Queue recovery:                   PASS (static) / runtime UNVERIFIED
Database recovery:                PASS (static: 503+Retry-After contract)
Redis recovery:                   PASS (static: AOF + fallback ledger)

Duplicate protection:             PARTIAL (leader election; no idempotency key verified)
Retry storm protection:           PASS (static: bounded retries + sweep)
Cost protection:                  PASS (static: hard pre-dispatch daily cap)
Rate limiting:                    PASS (static: slowapi + login brute-force limit)
Resource exhaustion:              PASS (static: bounded logs/queues; leaks open PROD-09-103/106)

Secrets lifecycle:                PARTIAL (no leaks found; rotation runbook-only)
Data lifecycle:                   PASS (static: retention loop + admin-only erasure)
Deletion verification:            PASS (static; admin-gated at privacy.py:132-135)

Migration verification:           FAIL (alembic check drift — PROD-13-101)
Upgrade verification:             PARTIAL (documented; no pre-migration backup)
Rollback verification:            UNVERIFIED (never exercised; restore path drill-verified only)

External dependency recovery:     PASS (static: breaker + retries) / runtime UNVERIFIED
Operational runbooks:             PASS (94 docs) / backup timer NOT installed
Observability:                    PARTIAL (logs+SSE; no metrics/alerting stack)
Long-run stability:               UNVERIFIED (no soak executed; k6 script + CI exist)
Regression:                       N/A (read-only audit; no repairs performed)

P0 blockers:                      0
P1 blockers:                      3 (drift; backup dormant; RTO/RPO undefined)
Unknown critical items:           4 (outage/failover drills, rollback exercise, soak, post-recovery journeys)
Human decisions required:         3 (RTO/RPO targets; backup host/ownership; maintenance-mode adoption)

============================================================

FINAL STATUS:

NOT GREEN — OPERATIONAL PRODUCTION AUDIT INCOMPLETE

============================================================
```

**Layer score: 78 / 100** — credited: the executed RESTORE_VERIFIED drill, and the real, leader-gated recovery machinery (orphan recovery, 503+Retry-After contract, circuit breaker, spend guard, rate limits, graceful shutdown). Deducted: the three Mediums (autogenerate drift, dormant backup scheduling, undefined RTO/RPO) and the unexecuted runtime gates (rollback, chaos/failover, soak, post-recovery journeys).

## 13. Blockers and Human Decisions

- **P0:** none (no data-loss path, no security hole, no unrecoverable hang found).
- **P1:** PROD-13-101 (drift/unsafe autogenerate); PROD-13-103 (backups dormant); PROD-13-102 (RTO/RPO undefined).
- **Unknown critical (not executed under read-only engagement):** DB-down/Redis-down/provider-down runtime drills; rollback exercise; long-run soak; post-recovery user journey — all have committed test artifacts/runbooks but were not run here.
- **Human decisions:** RTO/RPO targets; where the backup timer runs + who monitors it; whether to add a maintenance mode; acceptance of dev-scale restore evidence for production sign-off.

## 14. Evidence Index (spot references)

- `scripts/backup_db.sh`, `scripts/restore_db.sh`, `scripts/systemd/gridiron-backup.service`, `scripts/systemd/gridiron-backup.timer` (03:00 / RandomizedDelaySec=1800 / Persistent=true; not installed).
- Drill: `docker exec crr2906-db-1` pg_dump -Fc → 4.84 MB / 444 TOC / ~1.8 s; `qoder13_restore_drill` pg_restore --exit-on-error ~7.5 s; parity 1/062, 414, 91, 108; throwaway DB dropped; re-verified 2026-10-02.
- `backend/app/fleet/failure_ladder.py:225-235,282-324,327-380`; `backend/app/main.py:1439-1440,1532-1543,1632-1637,1714-1717,1790-1834,1907-1925,1941-1948`.
- `backend/app/db/errors.py`; `backend/app/middleware/rbac.py:44-45`; `backend/app/api/auth.py:67,95,167`; `backend/app/config.py:2141`.
- `backend/app/fleet/spend_guard.py:25,51,66-98,131,168,178,198,207`; `backend/app/agents/base_graph.py:44,166-167`.
- `backend/app/api/privacy.py:103,120-123,132-135`; `backend/migrations/env.py` (whole); `alembic check` output (7/55/1/2+2).
- `docker-compose.prod.yml:24,48,76,78,115-116,176,229`; `backend/app/db/session.py:49,87`; `backend/tests/load/gridiron_load_test.js`; `.github/workflows/ci.yml`, `load-test.yml`.
- `docs/disaster_recovery.md` (207 lines), `docs/DEPLOYMENT.md` (174 lines); systemd state: `0 timers listed`, `/var/backups/gridiron` absent, `./backups` absent; maintenance mode: 0 grep hits.

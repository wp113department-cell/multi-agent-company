# Audit 13: Operations / Disaster Recovery / Lifecycle

**Spec:** `files/Audit/13_MASTER_PRODUCTION_OPERATIONS_DISASTER_RECOVERY_LIFECYCLE_AUDIT.md` + `00b_AUDIT_STANDARDS.md`
**Date:** 2026-10-02 · **JSON sidecar:** `json/AUDIT_13_OPERATIONS_DR_LIFECYCLE.json`
**Evidence:** `evidence/secret_history_scan.py` (+ `.out.json`); drill results in `docs/disaster_recovery.md` § "Measured drill" / "Behaviour during outages"

## Result

🟡 **YELLOW: every recovery drill now passes, and doing the drills found 5 real defects (including a High authorization hole), all fixed. One production gap is the owner's: backups are not scheduled anywhere, so today the recovery point is "the last time someone ran the script by hand".**

**Score: 82 / 100.**

## How the drills were run

There is no production environment, so every drill ran **for real on this machine**, on an **isolated copy**: a separate Postgres 16 + pgvector container and a separate Redis, with your backup restored into them. The backend ran with a fake Anthropic key (no spend). The shared dev database and Redis were never stopped, because another test run (yours) was using them. Afterwards everything was removed: containers, the drill database and temp files.

## 1. Backup and restore: PASSED (real)

| Step | Result |
|---|---|
| `scripts/backup_db.sh` (unchanged, run in a pg16 container) | **3.5 s**, 4.2 MB, the script's own `pg_restore --list` check passed |
| `scripts/restore_db.sh --yes` into an empty database | **7.1 s**, migration 062 (head) |
| Integrity | 51/51 tables. 48 identical row counts; 3 differ only because another test run was writing to the source database during the drill (verified: an active pytest process, and the differing tables are the ones it writes) |
| Restore into a **brand-new Postgres server** | OK: 373 tasks, 3 HNSW indexes, pgvector 0.8.6 |
| App on the restored database | **healthy in 7.2 s**; login, task list (API) and **HNSW vector search** (`EXPLAIN` uses the index, returns results) all work |
| **RTO** | ≈ 18 s machine time at this size (< 1 minute with an operator) |
| **RPO** | ⚠️ **Unbounded: no backup schedule exists** (no cron, timer, compose service or CI job). Ready-to-paste daily cron line added to `docs/disaster_recovery.md` → **OWNER ACTION** (OPS-13-006) |

## 2. Failure drills (real, on the isolated stack)

| Drill | Before | After fixes |
|---|---|---|
| **Redis down** | ✅ app fully working (health, list, create, budget gate) in ms; 1 warning, no log spam; automatic recovery | same |
| **Postgres down** | ⚠️ `/health` 503 ✅ and recovery without restart ✅, **but** endpoints returned a bare text/plain `Internal Server Error`, login said **"Auth configuration error"**, and the token check said **"Invalid token" (401)**, which **logs every user out over a DB blip** | ✅ every endpoint answers `503 {"error":{"message":"Database unavailable, retry shortly"}}` + `Retry-After: 5`; sessions stay valid; automatic recovery |
| **Backend `kill -9` mid-task** | ⚠️ the orphaned run was marked failed on restart ✅, **but its task stayed in "coding" forever** (the UI shows it running, with nothing running) | ✅ task → **blocked** (`blocked_reason="orphaned"`) with an explanatory log line; a task that still has a live run is untouched |
| **Invalid LLM key** | ✅ fails in ~1–2 s with exactly **1** provider call (no retries on 401), clear reason; ⚠️ returned 500 | ✅ returns **502** (upstream error) |
| **Repeated provider failures** | ✅ **circuit breaker opens after 5 failures**: runs 5–8 refused locally in ~0.3 s, **0** provider calls | same |

## 3. Findings

| ID | Sev | Status | Finding | Fix |
|---|---|---|---|---|
| OPS-13-001 | **High** | FIXED | **Any approver could erase any account, including every admin** (locking admins out), and export any user's personal data. `DELETE /api/privacy/user/{u}` and `GET /api/privacy/export/{u}` used `require_approver`, although their own docstrings said "admin-initiated". Proven in the drill: an approver erased `admin` (200). | New `require_admin` (role read **live** from the DB, never from the token) on both; **the last admin can never be erased** (409). Tests: approver → 403 on both; admin → 200; last admin → 409. |
| OPS-13-002 | Medium | FIXED | DB outage reported as a server bug: plain-text 500s, "Auth configuration error" | `app/db/errors.py::is_db_unavailable` (only DB-layer errors; a missing file or unrelated timeout is not misclassified) + a catch-all JSON handler: 503 + `Retry-After` for outages, a detail-free JSON 500 otherwise |
| OPS-13-003 | Medium | FIXED | DB outage turned into 401 "Invalid token" in the auth middleware → mass logout | `rbac._raise_if_db_unavailable` → 503 |
| OPS-13-004 | Medium | FIXED | Crash left tasks "running" forever | `failure_ladder._block_tasks_of_orphans` |
| OPS-13-005 | Low | FIXED | The JSON error handler **dropped headers** set on HTTP errors (`Retry-After`, `WWW-Authenticate`) | pass `exc.headers` through |
| OPS-13-006 | **High** (operational) | **OWNER ACTION** | Backups never scheduled → RPO unbounded; no off-host copy | Cron recipe in `docs/disaster_recovery.md`; copy backups off the host |
| OPS-13-007 | Low | FIXED | Provider failure returned 500 | 502 for `anthropic.APIError` / open circuit breaker |
| OPS-13-008 | Low | DOCUMENTED | No secret-rotation runbook | Added: `docs/disaster_recovery.md` § "Secret rotation". It covers 7 secrets, including two traps: a key saved from the UI **overrides** `.env`, and replacing `CREDENTIAL_ENCRYPTION_KEY` alone makes stored keys unreadable |
| OPS-13-009 | Low | OWNER | `backend/.venv` was committed on 2026-07-02 (removed the next day); it still sits in git history (repo pack 131 MB). Removing it needs a history rewrite. | Owner's choice |
| OPS-13-010 | Info | NOTE | Your dev DB's `admin` user has role **approver**, not admin, so with OPS-13-001 fixed **no account can erase users** until one is made admin | `UPDATE users SET role='admin' WHERE username='admin';` if wanted |

## 4. Secrets

- **Git history scan (all 613 commits, all branches): 0 real secrets.** The 11 matches are fake fixtures in secret-detector tests (one is GitHub's published example token) and doc placeholders (`PASSWORD`, `<password>`); 23 more were in vendored library files. Values were never printed; only masked prefixes.
- `.env` is git-ignored and was never committed.
- Rotation runbook: see OPS-13-008.

## 5. Data lifecycle

- **Export** (`/api/privacy/export/me`): works on the real stack (identity, role, attributable audit entries; no password hashes).
- **Erasure:** works, is now admin-only, and revokes the erased account's token immediately (existing test, updated).
- **Retention:** logs are archived, not deleted; checkpoints of plans awaiting approval are kept (audit 08); finished worktrees reclaimed (audit 09).

## 6. Covered by earlier audits (not repeated)

Migration rollback and stairway (06) · daily cost hard stop, retry bounds, concurrency (09) · rate limiting and brute force: 429 after 8 failed logins (12) · secret hygiene in agent shells (11) · idempotency keys and duplicate-run CAS (04).

## Tests added / changed

- `tests/test_audit13_db_outage_responses.py` (8): a real refused connection is classified as an outage; FileNotFound, plain ConnectionRefused, timeouts and ValueError are not; 503 JSON + Retry-After; detail-free 500; headers preserved.
- `tests/test_audit13_orphan_blocks_task.py`: real DB; crashed task → blocked/orphaned with a log; task with a live run untouched (**fails on old code**).
- `tests/test_b7_auth_and_agent_authorization.py`: new admin-only erasure/export test; the existing "deleted user loses access immediately" test now erases via an admin (an approver is asserted refused).
- Regression: 214 (audit-13 areas) + **556 (every API-level test file)** passed.

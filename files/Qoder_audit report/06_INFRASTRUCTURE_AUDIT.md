# 06 — Master Infrastructure Audit (DB, Migrations, Queues, CI/CD, Deployment)

- **Audit ID:** 06
- **Baseline commit:** `c927c44bf410e188287f32b2cf54e0529c642025` ("Production audits 09 and 11", 2026-10-02 11:11 +0530) — **baseline drift, see §9 note + §11**: HEAD advanced twice while this audit ran (`ecd4905a` "Production audit 12" → `33bbd03c` "Production audit 13", 12:07:59 +0530). All citations were re-verified against on-disk content after the last commit; among cited files only `backend/app/main.py` was touched by audit 13 (+36-line insert at the ~1900 region), and every main.py line number cited below was re-confirmed stable afterwards.
- **Run date:** 2026-10-02
- **Method:** read-only static verification — AST scripts (migration chain walk, ORM↔DDL column diff, Settings↔.env.example diff), targeted greps/file reads, git history, and one non-mutating Starlette routing experiment for artifact-path handling. No code touched, no deployment commands run.
- **Scope per brief:** migration integrity + ORM/DB drift + timezone consistency + pgvector ordering, config completeness, queue & event bus, artifact storage, CI/CD, deployment readiness, `/health`; 0–100 score.

---

## 1. Executive Summary

The infrastructure layer is **real and internally consistent**: a 62-file Alembic chain is strictly linear with a single head and zero ORM↔DDL drift (the historical crash class is absent, verified column-by-column); the only naive timestamp columns in the entire schema are four deliberately-naive `archived_at` columns whose designed writer strips tzinfo; config is fully synchronized (304/304 fields present in `backend/.env.example`) with fail-fast validators for security-sensitive selections; the queue abstraction actually switches backends at runtime through a single dispatch chokepoint with wall-clock bounds, real RQ retries, and a scheduled dead-letter sweep; both artifact backends (local-disk and S3) are real implementations with checksum verification; CI runs the same suite as local with a matching `pgvector/pgvector:pg16` service and does **not** contain a deploy job (manual-by-design, confirmed by absence); and `vercel.json` / `Procfile` / `docker-compose.yml` all match the real entrypoints and build tooling (pnpm).

**No Critical, High, or Medium findings.** Three Low findings are recorded: one stale module docstring in the queue module that contradicts live wiring (INFRA-06-101), one mixed-writer timezone inconsistency on `memory_embeddings.archived_at` (INFRA-06-102), and stale variable counts / incomplete optional-service coverage in deployment docs (INFRA-06-103).

**Infrastructure Layer Production-Readiness: 92 / 100 — Verdict: READY.**

---

## 2. Migration Chain Integrity

| Check | Result | Evidence |
|---|---|---|
| Migration files | 62 (`001…062`) | `backend/migrations/versions/*.py` count |
| Revision chain | **Single linear chain, 62/62 links walked head→base** | AST walk of `revision`/`down_revision` from head `062` to `None`; chain length 62 == unique revisions 62 |
| Duplicate revisions | 0 | id→file map, no collisions |
| Missing `down_revision` references | 0 | every reference resolves within the directory |
| Merge points / branch labels | 0 | single head (`062_documentation_score.py`) |
| pgvector extension ordering | **Correct** — `CREATE EXTENSION IF NOT EXISTS vector` at `001_initial_schema.py:22` runs before the raw `CREATE TABLE code_embeddings (embedding vector(1536))` at `001:193-203`; idempotent re-create at `004_phase6_tables.py:22` precedes the `memory_embeddings.embedding` conversion at `004:85-86`; `pgcrypto` added at `036:50` | grep of all `CREATE EXTENSION`/`vector` sites |
| HNSW coverage | **All three `Vector(1536)` tables indexed**: `memory_embeddings` (004:90-91), `versioned_lessons` (020:28), `code_embeddings` (032:29-30) | grep `hnsw` across migrations |
| Migration drill (up/down/up on empty DB) | Previously executed and documented by the ops audit; not re-run here (read-only; would mutate a DB) — chain-level integrity fully verified statically | `docs/DEPLOYMENT.md:40-43` + `What_is/AUDIT_REPORT/evidence/migration_drills.sh` (external artifact) |

## 3. ORM / DB Drift — **CLEAN (zero drift)**

Method: AST parse of `backend/app/db/models.py` (43 tables) vs. a full upgrades-only reconstruction of the migration-final schema (46 tables, incl. raw-SQL DDL). Initial candidate mismatches were each reconciled manually and all turned out to be parser blind spots, not drift:

- **Loop-variable `add_column` migrations** (the parser only saw literal table names): `019` adds `archived`/`archived_at` to `task_logs`/`agent_runs`/`artifacts` via `_TABLES` loop; `043` adds `repo_id` to `indexed_files`/`call_edges`/`code_embeddings`; `053` adds `repo_id` to `events`/`artifacts`/`pending_approvals`/`epic_scratchpad`. Verified by reading each file.
- **Raw-SQL table**: `code_embeddings` is created by raw DDL in `001:193-203` — all 8 DDL columns (`id, repo_path, file_path, chunk_index, content, embedding, content_hash, updated_at`) + `repo_id` (043) match the `CodeEmbedding` model field-for-field.
- **Drop+add type conversion**: `memory_embeddings.embedding` is dropped and re-added as `vector(1536)` inside `004:85-86` (net: present) — matches `MemoryEmbedding.embedding` (`models.py:767` region).
- **Reverse direction (DB columns without ORM fields): empty.**
- Tables intentionally accessed via raw SQL without ORM classes (no finding): `audit_log`, `chat_messages`, `lessons` — consistent with their raw-SQL write sites (e.g. `fleet/audit_log.py` INSERTs).

No column in any modelled table is missing from the DDL, and no modelled field lacks a real DB column — the exact class of bug that previously crashed endpoints is absent.

## 4. Timezone Consistency

- **Schema census:** exactly **4 naive `DateTime` columns** exist in `models.py` — `task_logs.archived_at` (241), `agent_runs.archived_at` (340), `artifacts.archived_at` (507), `memory_embeddings.archived_at` (767). All four are `archived_at`, created by migrations `019`/`022` with an explicit "naive by design" rationale; **every other timestamp column in the schema is `DateTime(timezone=True)`**.
- **Designated writer:** `retention.py:44-70` — `now_naive = datetime.now(timezone.utc).replace(tzinfo=None)` (53) bound into the raw `UPDATE … SET archived = true, archived_at = :now` (58), for all four tables (memory via `_archive_table("memory_embeddings", …)` at 242). Correct tz-stripped UTC.
- **Call-site sweep** of all 83 `datetime.now(` sites: 79 use `timezone.utc`; 1 is a comment (`fleet_checkpoint.py:151`); 1 is `datetime.now().astimezone()` (`approval_gate.py:219`) writing into `decided_at` which is `DateTime(timezone=True)` — correct; 2 use `datetime.utcnow()` (`known_issues_write.py:125`, `decision_log_append.py:124`) and write **files only** (`.md`/`.jsonl`), never a DB column.
- **Raw-SQL aware bindings all target aware columns:** `bus.py` `events.created_at` and `failed_events.failed_at`, and `store.py` `artifacts.created_at` — DDL for all three is `sa.DateTime(timezone=True)` (`002_phase4_tables.py:30-32, 53-55, 73-75`). No aware→naive binding exists anywhere.
- **Observation (not a finding):** `retention.py` binds the naive cutoff against `timestamptz` age columns (`created_at`/`started_at`) in raw SQL — no crash possible (server-side comparison), but the interpretation of the naive cutoff depends on the session `TimeZone`; benign under the UTC-default Postgres used by compose/CI.

### INFRA-06-102 — `memory_embeddings.archived_at` has two writers with different timezone semantics
- **Severity:** Low · **File:** `backend/app/memory/consolidation.py` · **Confidence:** High
- **Finding:** beyond retention's tz-stripped UTC writer, memory consolidation also archives rows: `UPDATE memory_embeddings SET archived = true, archived_at = now() WHERE id = ANY(:ids)` (`consolidation.py:240`). Server-side `now()` is `timestamptz`; assigning it to the naive `archived_at` column makes Postgres silently cast it through the **session TimeZone**, while `retention.py` writes UTC-stripped values. The same column therefore carries values with two different implicit timezones depending on which writer archived the row.
- **Evidence:** `consolidation.py:238-243`; `retention.py:53,58`; naive column `models.py:767` (migration `022`).
- **Production impact:** interpretation ambiguity for retention/monitoring reports that read `archived_at` (memory consolidated into a survivor vs. aged-out by retention); no crash (the cast is server-side) and no data loss. Low.
- **Recommendation:** switch `consolidation.py:240` to `archived_at = :now` bound from `datetime.now(timezone.utc).replace(tzinfo=None)`, matching `retention.py`. Effort: S.

## 5. Config Completeness

- **`Settings` ↔ `backend/.env.example`: 304 fields ↔ 304 names, zero differences in either direction** (scripted AST diff + regex parse). `.env.example` consists of 130 active assignments + 174 commented placeholders; every field is documented in one of the two forms. No regression of the historically-found "18 missing vars".
- **Fail-fast validation present for security/cost-sensitive selections:** `_validate_credential_encryption_key` (config.py:1964), "`artifact_backend=s3` requires `s3_bucket`" (2055-2060), enum validation rejecting unknown `ARTIFACT_BACKEND`/`QUEUE_BACKEND` values (2061-2084), plus the production block (1947-2023, cross-ref audit 05). `queue_backend` validator accepts only `asyncio|rq` (2082-2084) — see INFRA-06-101(b) for the doc conflict this creates with the BullMQ stub.
- **Stale counts in docs** (not a functional issue): root `.env.example:15` says "~85 backend variables"; `docs/DEPLOYMENT.md:57` says "96 documented variables as of Audit 06, 2026-07-27" (explicitly hedged as drifting). Actual: 304. Folded into INFRA-06-103.

## 6. Queue & Event Bus

- **Runtime switching is real:** `get_queue_adapter()` (`queue_adapter.py:267-276`) returns `RQAdapterBridge` for `rq`, `BullMQQueueAdapter` for `bullmq`, `AsyncioQueueAdapter` (default) otherwise; the RQ bridge (`181-245`) wraps the real `RQQueueAdapter` (`rq_adapter.py:36-145` — two named queues, `Retry(queue_job_retry_max)`, 30-min job timeout, singleton connection). `BullMQQueueAdapter` correctly raises `NotImplementedError` from `enqueue`/`get_status` (254-261) rather than silently no-op-ing.
- **Single real dispatch chokepoint:** `dispatch_job()` (`queue_adapter.py:322-364`) routes `QUEUE_BACKEND=rq` → `queue().enqueue()` (real RQ job) and the default backend → FastAPI `BackgroundTasks` **wrapped in the same wall-clock bound** (`_with_wall_clock_timeout`, 290-319; `job_wall_clock_timeout_seconds=1800`, config.py:868-878). It is called from 10 sites in `api/tasks.py` (409, 420, 431, 526, 589, 599, 714, 815, 850, 1113) and from the dependency auto-dispatch loop (`main.py:1047`) — 11 call sites app-wide.
- **Dead-letter handling persists, not just logs:** `_write_failed_event` INSERTs a real `failed_events` row (`bus.py:144-178`); for RQ, `sweep_failed_rq_jobs()` (`queue_adapter.py:367-445`) drains `FailedJobRegistry` into the same table and is scheduled every `queue_failed_job_sweep_interval_seconds` (default 300s) by a lifespan loop that no-ops unless `QUEUE_BACKEND=rq` (`main.py:330-362`, task registered at `main.py:1723`).
- **No double-processing:** `publish_event` (`bus.py:181-212`) persists + `pg_notify` + fan-outs to Redis Streams unconditionally, but `publish_to_stream` no-ops when disabled (`redis_streams.py:74-80`); the drain loop (`main.py:365-391`, task at 1730; 60s default) calls `drain_and_ack_stream` which only **logs and ACKs** (plus `XAUTOCLAIM` stale-PEL recovery, `redis_streams.py:157-229`) — it never re-dispatches business logic. The in-process subscriber registry additionally has **zero registered subscribers in production code** (only tests) — documented as dormant in `redis_streams.py:164-172`; no duplicate processing can occur on any configuration.
- Dormant-but-documented capabilities (no finding; flagged for audit 11/12): `get_unprocessed_events()` has no production caller; in-process bus fan-out is inert today.

### INFRA-06-101 — `queue_adapter.py` documentation contradicts runtime wiring in two ways
- **Severity:** Low · **File:** `backend/app/pipeline/queue_adapter.py` · **Confidence:** High
- **Finding:** (a) the module header (10-27) still claims "**NOT WIRED INTO REAL TASK DISPATCH** … every real task-launch call site in `api/tasks.py` … dispatches via `BackgroundTasks.add_task(...)` directly … so `QUEUE_BACKEND=rq` **currently has no effect on real task dispatch**". This is **stale**: `dispatch_job()` is the single chokepoint (322-364), is called by all 10 real dispatch sites in `api/tasks.py` plus the dependency auto-dispatch loop in `main.py:1047` (11 app-wide), and routes `rq` to a real RQ job. Git timeline: the "documented, not wired" note was added 2026-07-27 (`b30993fc`, per the ORCH-04-016 fix pass); the actual wiring landed 9 days later 2026-08-05 (`bda3e9f5`) and the note was never updated. (b) the `BullMQQueueAdapter` class docstring (251-252) says "Enable by setting QUEUE_BACKEND=bullmq in environment", but the config validator rejects anything outside `asyncio|rq` (config.py:2082-2084) — the enable path is impossible and `get_queue_adapter`'s `bullmq` branch (274-275) is unreachable.
- **Evidence:** file reads above; grep of `dispatch_job` call sites (10 in `api/tasks.py`, 1 dep-loop site in `main.py`); `git log -S` dates; config validator lines.
- **Production impact:** operator-facing only: the docs assert the queue backend is inert when it is live (switching to `rq` **does** change the failure model — persistent worker process + retries vs in-process BackgroundTasks), and a stub claims an enable path that config validation blocks. No runtime defect; opposite of a missing capability.
- **Recommendation:** rewrite the module header to describe the current chokepoint behavior (default=BackgroundTasks-with-timeout, `rq`=real queue) and cite the current dispatch path; fix or remove the BullMQ enable sentence. Effort: S.

## 7. Artifact Storage

- **Default backend:** `artifact_backend="db"` (config.py:924-931; default) → local disk + DB metadata: `save_artifact` writes `{worktrees_dir}/../artifacts/{uuid}` (`store.py:51-109`), `save_artifact_async` wraps the sync write in `asyncio.to_thread` (165-167 — the previously-documented event-loop-blocking bug is fixed), inserts the `artifacts` row with `content_sha256` and opportunistic `repo_id` (187-204).
- **S3 backend is real** (not a stub): gzip-compressed JSON upload with key scheme `{s3_key_prefix}{task_id}/{artifact_type}/{artifact_id}.json.gz` (`s3_store.py:47-84`), lazy boto3 client with env/IAM fallback (30-44), real list/delete (119-147); upload failure degrades to the disk path with the DB row kept consistent (`store.py:141-148`).
- **Retrieval is backend-agnostic and correct** (prior audit's INFRA-06-002 fix verified live in code): `get_artifact_content` (221-290) dispatches on the **stored** `storage_path` scheme (`s3://` → `load_artifact_s3_by_key`; else disk), so S3-saved artifacts no longer 404; SHA-256 integrity logged on mismatch (`293-311`).
- **Endpoints authenticated and non-enumerable:** both `GET /api/tasks/{task_id}/artifacts` and `GET /api/artifacts/{artifact_id}` require `require_authenticated` (`api/artifacts.py:16-48`). Disk reads go through the DB-recorded path; the no-row fallback uses the path param directly, which **cannot traverse**: a live Starlette/TestClient experiment showed `..%2F..%2F…` and `..%2f…` **do not match** the `{artifact_id}` route (404 — encoded slashes are not decoded into the captured param), so no slash-bearing input ever reaches `Path` construction. ID form is a UUID; listing is scoped by `task_id` exactly like the rest of the tasks API (`require_authenticated` baseline, `api/tasks.py:218-222`).

## 8. CI/CD

- **Services match real schema requirements:** CI `postgres` service is `pgvector/pgvector:pg16` (`.github/workflows/ci.yml:24-26`) — same image as compose (`docker-compose.yml:9`) — and migrations run the extension (001:22); no separately-managed extension step needed.
- **Same suite as local, markers respected:** CI runs the full `python -m pytest tests/ -v --tb=short --timeout=120` (ci.yml:82-83); `pytest.ini`'s `addopts = -m "not slow"` applies identically (no `-m` override in CI). CI timeout (120s) vs. the local baseline's 600s CLI flag differ only in the harness flag, not coverage.
- **Jobs (ci.yml):** ruff + black + `mypy app/ --strict` (74-80), pytest + junit artifact (82-83, 127-128), regression-gate job (106), Windows job (154-201), frontend tsc/build, blocking `pnpm audit` (227-241), eslint with no suppression (246-253), e2e (269-305), security job with **blocking** `pip-audit` (`346`; `|| true` removal per SEC-05-019 verified; documented `GHSA-jfh8-c2jp-5` ignore). Cross-refs to SEC-05-104 for the 3.11-vs-3.12 interpreter note and dev-requirements not being audited.
- **No deploy job exists** — confirmed by absence: every `deploy`/`vercel`/`render`/`fly`/`railway` hit in ci.yml is a comment or test fixture (87-100); deployment is manual by design and documented as such (`docs/DEPLOYMENT.md:5-8`).

## 9. Deployment Configuration

- **Vercel:** `vercel.json` build is `pnpm --filter @gridiron/web run build` + `pnpm install --frozen-lockfile` (pnpm workspace — the historically-wrong npm command has not regressed); output `apps/web/.next`; `NEXT_PUBLIC_API_URL` via env reference; rewrites destination is the documented placeholder `https://api.gridiron.example.com` (to be replaced per `docs/DEPLOYMENT.md:98-99`); security headers present.
- **Procfile:** `web: cd backend && uvicorn app.main:app …` and `worker: cd backend && rq worker gridiron-high gridiron-default … --with-scheduler` — both entrypoints exist; the worker is only needed when `QUEUE_BACKEND=rq` (`docs/DEPLOYMENT.md:52-53` matches config default `asyncio`).
- **docker-compose / run.sh:** postgres (`pgvector/pgvector:pg16`) + redis:7-alpine with healthchecks, one-shot migration service, backend healthcheck `curl -f http://localhost:8000/health` (105-106) — which is now truthful because `/health` returns **503 when degraded** (`main.py:2048-2054`).
- **`/health` is meaningful, not a static 200:** checks DB (`SELECT 1`, main.py:1999-2010), Redis only when streams/rq enabled (2012-2024), S3 `head_bucket` only when `artifact_backend=s3` (2026-2036), registered agent count (2038-2046), and sets 503 unless every check is ok (2048-2054); exempt from rate limiting (1992).
- **`docs/DEPLOYMENT.md` accuracy:** Supabase Postgres+pgvector (§1), Railway/Render + Procfile (§2), Vercel pnpm (§3) all match code; states all vars optional except `DATABASE_URL`/`ANTHROPIC_API_KEY`. Gap: the **optional S3 artifact backend and Redis Streams are not covered** as deployable options (S3 appears only in the changelog section, 165-166); stale variable counts ~85/96 vs. actual 304 → INFRA-06-103.

### INFRA-06-103 — Deployment docs carry stale config counts and omit optional-service coverage
- **Severity:** Low · **File:** `docs/DEPLOYMENT.md`, `.env.example` (root) · **Confidence:** High
- **Finding:** root `.env.example:15` advertises "~85 backend variables"; `docs/DEPLOYMENT.md:57` says "96 documented variables as of Audit 06, 2026-07-27". Actual `Settings` fields and `backend/.env.example` names are both **304**. Additionally the deployment guide gives no operational instructions for the optional `ARTIFACT_BACKEND=s3` or `REDIS_STREAMS_ENABLED=true` services even though code fully supports both.
- **Evidence:** scripted Settings↔.env.example diff (304/304); the two doc lines above; `config.py:856-940` (queue/redis/s3 fields), `main.py:2012-2036` (health checks for both).
- **Production impact:** operators underestimate the configuration surface and lack guidance for enabling the two real optional services; doc-only, no runtime effect.
- **Recommendation:** update both counts (or replace with "verify via diff" pointer only) and add short S3 + Redis-Streams deployment subsections (bucket/IAM, streams enable + drain loop note). Effort: S.

## 10. Prioritized Fix List

| # | ID | Severity | Fix | File:line | Effort |
|---|----|----------|-----|-----------|--------|
| 1 | INFRA-06-101 | Low | Rewrite stale queue-module header ("rq has no effect" is false since 2026-08-05); fix/remove BullMQ "enable" sentence blocked by config validator | `backend/app/pipeline/queue_adapter.py:10-27, 251-252` | S |
| 2 | INFRA-06-102 | Low | Use UTC-naive `archived_at` bind in memory consolidation to match retention.py's writer | `backend/app/memory/consolidation.py:240` | S |
| 3 | INFRA-06-103 | Low | Update stale var counts; add S3 / Redis-Streams deployment sections | `docs/DEPLOYMENT.md:57`, `.env.example:15` | S |

No Critical, High, or Medium findings. Note: the single-head migration chain, zero ORM drift, and 304/304 config parity mean the historically-buggy infrastructure classes are all currently clean — see §3–§5 evidence.

## 11. Score & Verdict

**Infrastructure Layer Production-Readiness: 92 / 100 — Verdict: READY**

- Full weight on: linear 62-migration chain with correct extension/HNSW ordering (§2); zero ORM↔DDL drift, including the previously-crashing MemoryEmbedding-class checks (§3); timezone discipline across all 83 call sites with only the 4 by-design naive columns and one inconsistent secondary writer (§4, Low); complete 304/304 config parity with fail-fast validators (§5); genuinely switchable queues, real dead-letter persistence, and double-processing-free event fan-out (§6, one doc finding); real dual artifact backends with checksum, auth, and traversal-safe retrieval (§7); CI matching local execution with no deploy job and blocking audits (§8); deployment configs matching real entrypoints, sane health semantics (§9, one doc finding).
- Deductions: 8 points for the three Low findings above (documentation/runtime contradictions and one mixed-writer timestamp semantic), none of which affects correctness of any running path.
- **Baseline drift note (per §header):** HEAD advanced `c927c44b → ecd4905a → 33bbd03c` during the audit; every citation re-verified on-disk after the last commit. Audit 10 must reconcile per-audit baselines.

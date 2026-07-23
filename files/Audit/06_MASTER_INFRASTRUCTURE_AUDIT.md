# MASTER INFRASTRUCTURE AUDIT — DB, Migrations, Queues, CI/CD, Deployment

# DO NOT WRITE OR MODIFY CODE. READ-ONLY AUDIT.

You are a Principal Platform Engineer + Principal DevOps Engineer + Principal
Database Architect. Audit every infrastructure layer supporting this system.

## PHASE 0 — Orientation

Read in full:
- `backend/migrations/versions/` — every migration file, in order
- `backend/app/db/models.py` — full ORM model set
- `backend/app/config.py` — full `Settings` class (all ~93 fields per
  PROJECT.md's own count)
- `backend/.env.example` and root `.env.example` / `apps/web/.env.example`
- `backend/app/pipeline/queue_adapter.py`, `backend/app/queue/rq_adapter.py`
- `backend/app/event_bus/bus.py`, `backend/app/event_bus/redis_streams.py`
- `backend/app/artifacts/store.py`, `backend/app/artifacts/s3_store.py`
- `.github/workflows/ci.yml`
- `vercel.json`, `Procfile` (or equivalent), `docs/DEPLOYMENT.md` if present
- `run.sh` / docker-compose or equivalent local dev bootstrap

## PHASE 1 — Migration Integrity Audit

- List every migration in order with its actual DDL summary (table/column
  added, index added, constraint added). Confirm there are no gaps in the
  Alembic revision chain (each migration's `down_revision` correctly points
  to the prior one — trace the actual chain, don't assume from the
  filename numbers).
- Confirm every ORM model field has a corresponding real DB column (check
  for the exact class of bug PROJECT.md documents: `MemoryEmbedding` once
  had a DB column with no matching ORM field, crashing an endpoint on every
  call — grep every model class field-by-field against its migration DDL).
- Confirm timezone handling is consistent: PROJECT.md documents at least 3
  separate real bugs from timezone-aware `datetime.now(timezone.utc)` being
  written into naive `TIMESTAMP WITHOUT TIME ZONE` columns (crashed with
  asyncpg `DataError`, silently swallowed by a broad exception handler in
  one case). Grep EVERY `datetime.now(` call site near a DB write and
  confirm `.replace(tzinfo=None)` (or an actually-timezone-aware column) is
  used consistently. Flag any inconsistency as a live landmine, even if not
  yet triggered.
- Confirm `CREATE EXTENSION IF NOT EXISTS vector` and the pgvector HNSW
  index are present and correctly ordered in the migration chain (extension
  before any vector column usage).

## PHASE 2 — Config Completeness Audit

- Programmatically compare (or manually enumerate) every field in
  `Settings` (`config.py`) against `backend/.env.example`. Report any field
  present in one but not the other. PROJECT.md documents this was done once
  and found 18 missing vars — confirm no regression since (new config
  fields added by later "Day" sessions without a matching `.env.example`
  update).
- Confirm every config field with a security/cost implication
  (`credential_encryption_key`, `*_api_key`, `*_threshold`, `MAX_*`) has a
  sane, documented default or is clearly marked required.
- Confirm no required-at-runtime config value is only enforced by convention
  (i.e., would the app actually fail fast with a clear error if
  misconfigured, or silently misbehave?).

## PHASE 3 — Queue & Event Bus Audit

- Confirm `QUEUE_BACKEND` config actually switches between
  `AsyncioQueueAdapter` and the RQ adapter at runtime (trace
  `get_queue_adapter()`), and that the `BullMQQueueAdapter` stub correctly
  raises `NotImplementedError` rather than silently no-op-ing.
- Confirm the in-memory event bus (`event_bus/bus.py`) and the optional
  Redis Streams variant (`redis_streams.py`) are not accidentally both
  active in a way that could double-process events, or confirm which one
  is authoritative today per `REDIS_STREAMS_ENABLED`.
- Confirm dead-letter handling (`_write_failed_event`) actually persists
  failures somewhere inspectable, not just logs them.

## PHASE 4 — Artifact Storage Audit

- Confirm local-disk artifact storage (`artifacts/store.py`) and the S3
  variant (`s3_store.py`) — which one is actually wired as default via
  `ARTIFACT_BACKEND`? Confirm the S3 path is real (not a stub) if selected,
  including compression and the key-naming scheme.
- Confirm artifact retrieval endpoints don't leak one task's artifacts to
  an unauthorized caller (path/ID enumeration risk).

## PHASE 5 — CI/CD Audit

- Confirm `ci.yml`'s jobs (backend pytest+mypy+ruff+black, frontend
  tsc+build, security pip-audit) actually match what's run locally per
  PROJECT.md's own session logs (i.e., CI isn't stale relative to the real
  test suite — check `pytest.ini`'s marker config, e.g. `-m "not slow"`,
  is respected the same way in CI).
- Confirm the pgvector Postgres service container config in CI matches the
  real schema requirements (extension, correct image tag).
- Confirm there is genuinely no deploy job in CI (per PROJECT.md's stated
  design — deployment intentionally manual/separate) rather than a
  half-finished one that could fire unexpectedly.

## PHASE 6 — Deployment Readiness (static only — do not deploy anything)

- Confirm `vercel.json`'s build command actually matches the project's real
  package manager (pnpm workspace, not npm) — PROJECT.md documents this was
  once wrong and fixed; confirm no regression.
- Confirm `Procfile`/equivalent process definitions match real entrypoints
  (`uvicorn app.main:app`, worker command) that actually exist.
- Confirm `docs/DEPLOYMENT.md` (if present) accurately describes required
  external services (Supabase/pgvector, Redis if enabled, S3 if enabled)
  matching what code actually requires vs. what's optional.
- Confirm `/health` endpoint (if present) returns a meaningful check (DB
  reachable, agent registry populated) not just a static 200.

## PHASE 7 — Final Report

1. Migration chain integrity table
2. ORM/DB drift findings (Critical if any found — this class of bug has
   caused real production crashes in this project before)
3. Timezone consistency findings (list every call site checked)
4. Config completeness diff (Settings vs .env.example)
5. Queue/event bus findings
6. Artifact storage findings
7. CI/CD findings
8. Deployment config findings
9. Prioritized fix list (Critical → Low, file:line)
10. Infrastructure Layer Production-Readiness score (0-100)

Do not write code. Do not modify files. Do not run any command that would
mutate a real deployment. Evidence or NOT FOUND only.

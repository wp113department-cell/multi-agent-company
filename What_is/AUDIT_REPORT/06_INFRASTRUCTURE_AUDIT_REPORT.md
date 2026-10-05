# Audit 06: Master Infrastructure Audit

**Spec:** `files/Audit/06_MASTER_INFRASTRUCTURE_AUDIT.md` + `00b_AUDIT_STANDARDS.md`
**Date:** 2026-09-29 · **JSON sidecar:** `json/AUDIT_06_INFRASTRUCTURE.json`

## Result

🟡 **YELLOW: the code-level infrastructure is verified and all its defects are fixed. Two items need the owner: GitHub Actions has been blocked by a billing problem since at least 21 August, and `vercel.json` still points at a placeholder API domain.**

**Infrastructure score: 86 / 100** (July: 64, "NOT READY"). Migrations, schema, configuration, queues, the event bus, and health probes were all verified by execution. Points lost for the two owner items above: CI cannot protect `main` until billing is fixed.

## 1. Migration chain integrity (executed on a throwaway database)

| Drill | Result |
|---|---|
| Revision chain | 62 migrations, single head `062`, linear |
| **Empty DB → `upgrade head`** | ✅ all 62 applied in ~4 s |
| **Dev DB vs freshly migrated DB** (`pg_dump --schema-only` diff) | ✅ identical, except the 4 LangGraph checkpoint tables the app creates itself at startup |
| **`downgrade base`** | ❌ → ✅ **fixed**: failed at 004 (dropped the `vector` extension that 001 owns and 001's table still used), then at 001 (dropped an index that a later migration made a UNIQUE constraint) |
| Round trip ×2 (base → head → base → head) | ✅ after fix |
| **Stairway** (every revision: down, up, down) | ✅ all 62 revisions |
| Failed downgrade leaves half-migrated state? | ✅ No: Postgres transactional DDL rolled the failed downgrade back completely (stayed at `062`) |
| `CREATE EXTENSION vector` before any vector column | ✅ migration 001 |

Re-runnable: `What_is/AUDIT_REPORT/evidence/migration_drills.sh` (never touches `gridiron_dev`).

## 2. ORM ↔ database drift (`alembic check` on the freshly migrated DB)

| Kind | Count | Verdict |
|---|---|---|
| Column type / timezone / missing column | **0** | ✅ the class that caused July's crashes is gone |
| Tables without an ORM model (`lessons`, `chat_messages`, `audit_log`) | 3 | ✅ intentional raw-SQL tables, each with a migration (audit 01) |
| Model says `NOT NULL`, DB column nullable | 5 timestamp columns | Low: the DB is looser than the code; no runtime error possible |
| Indexes in migrations but not declared on models | many | benign autogenerate noise; indexes exist and are used |

**Timezone consistency:** 57 columns are `timestamptz`; 7 are naive (`*.archived_at`, `system_settings.updated_at`, `task_images.created_at`, `chat_messages.created_at`). Every write to those 7 was checked: retention strips the timezone explicitly (`services/retention.py`: `now_naive = datetime.now(timezone.utc).replace(tzinfo=None)`), and the rest use DB-side `now()` defaults. No aware→naive write path remains.

## 3. Configuration completeness

| Check | Before | After |
|---|---|---|
| `Settings` fields documented in `backend/.env.example` | **127 / 301** (174 missing, incl. `DEPLOYMENT_ENV`, `BASH_SANDBOX_ENABLED`, `BG_PROCESS_REGISTRY_PATH`, `GIT_PUSH_PROTECTED_BRANCHES`, `SECRETS_MANAGER_*`, `OTEL_*`) | **301 / 301**: an "Advanced settings" section generated from `config.py` (defaults commented out, production-critical ones tagged `[PROD]`) + guard test `test_audit06_env_example_complete.py` so it can't drift again |
| Stale keys in `.env.example` | 0 | 0 |
| Frontend env (`process.env.*` vs `apps/web/.env.example`) | ✅ complete | ✅ |
| Security/cost settings fail fast when misconfigured | ✅ production startup refuses 9 insecure configs (audit 05) | ✅ |

## 4. Queues, event bus, dead letters

| Check | Result |
|---|---|
| `QUEUE_BACKEND` switch | ✅ `asyncio` (default) → `AsyncioQueueAdapter`; `rq` → `RQAdapterBridge`; `bullmq` rejected at startup by config validation |
| In-memory bus vs Redis Streams double-processing | ✅ `REDIS_STREAMS_ENABLED=false` by default; the Streams mirror is a best-effort copy, not a second dispatcher |
| Dead letters persisted | ✅ `INSERT INTO failed_events` (`event_bus/bus.py:147-165`) |
| Events persisted at all | ❌ → ✅ fleet events were never stored; fixed in audit 04 (ORCH-04-004) |

## 5. Artifact storage

`ARTIFACT_BACKEND=db` by default (the artifact is stored in Postgres). The S3 path exists in `artifacts/s3_store.py` and is part of `/health` when selected; it was **not** exercised live (no bucket configured). Artifact routes require authentication (audit 05 route matrix).

## 6. CI/CD

| Check | Result |
|---|---|
| Jobs mirror the local gates | ✅ ruff, black, `mypy --strict`, pytest (respects `-m "not slow"` from `pytest.ini`), Windows pytest subset, pnpm audit, tsc, eslint, vitest, build, Playwright E2E, pip-audit. No `\|\| true` left. |
| Postgres service | ✅ `pgvector/pgvector:pg16` with `pg_isready` health |
| Deploy job | ✅ none (deployment is manual by design) |
| **Is CI actually running?** | ❌ **No.** All 40 recent runs failed in 2–5 s with *"The job was not started because recent account payments have failed or your spending limit needs to be increased"*. Last attempted run: 2026-08-25. **Owner action: GitHub → Settings → Billing & plans.** For this audit every CI gate was run locally instead (see `00_BASELINE.md` and audit 08). |

## 7. Deployment readiness (static + executed where possible)

| Check | Result |
|---|---|
| Dockerfiles for every build context | ✅ `backend/Dockerfile`, `apps/web/Dockerfile` (July INFRA-06-005 holds) |
| `docker-compose.prod.yml` | ✅ valid; refuses to render without its 7 required secrets (`ALLOWED_WORKSPACE_PARENT`, `ANTHROPIC_API_KEY`, `CORS_ORIGINS`, `CREDENTIAL_ENCRYPTION_KEY`, `DEFAULT_ADMIN_PASSWORD`, `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`) |
| `Procfile` | ✅ `web` → `uvicorn app.main:app`; `worker` → `rq worker` (only needed with `QUEUE_BACKEND=rq`, documented) |
| `vercel.json` | ✅ pnpm build/install commands. ⚠️ **rewrites `/api/*` to the placeholder `https://api.gridiron.example.com`**, so a deploy as-is would send every API call to an example domain. **Owner must set the real API host.** |
| `docs/DEPLOYMENT.md` accuracy | ⚠️ → ✅ stated "22 migrations" (62 exist); corrected and pointed to the drill script |
| `/health` meaningful | ✅ checks DB (+ Redis / S3 when enabled) and reports agent count (85). **Executed:** stopped the real Postgres mid-run → `degraded / db: error`; restarted → recovered by itself (pool reconnects). |
| `/health` status code | ❌ → ✅ **fixed**: was **200 even when degraded**, so `curl -f /health` (the compose healthcheck) and load balancers never saw a database outage. Now 503, same body. Test added. |

## 8. Findings

| ID | Sev | Status | Finding |
|---|---|---|---|
| INFRA-06-001 | **High** (operational) | **OWNER ACTION** | GitHub Actions not executing any job since ≥2026-08-21: account billing / spending limit. No CI protection on `main`. |
| INFRA-06-002 | Medium | FIXED | `alembic downgrade base` impossible (2 migration bugs). Now round-trips and passes the stairway on all 62 revisions. |
| INFRA-06-003 | Medium | FIXED | `/health` returned 200 when degraded. Now 503. |
| INFRA-06-004 | Medium | FIXED | 174 of 301 settings undocumented in `.env.example`. Now complete, with a guard test. |
| INFRA-06-005 | Medium | **OWNER ACTION** | `vercel.json` rewrite target is a placeholder domain. |
| INFRA-06-006 | Low | FIXED | `docs/DEPLOYMENT.md` migration count stale |
| INFRA-06-007 | Low | ACCEPTED | 5 model/DB nullability mismatches; 7 naive timestamp columns (all writes verified safe) |
| INFRA-06-008 | Low | ACCEPTED | S3 artifact path not live-verified (no bucket); default backend is the DB |

## 9. July (2026-07-27) findings: regression check

| July ID | Today |
|---|---|
| INFRA-06-001 tz-aware ORM vs naive columns (Critical) | ✅ `alembic check`: 0 type/tz drift |
| INFRA-06-002 S3 artifact path (Critical) | ✅ code path present; live S3 not configured (INFRA-06-008) |
| INFRA-06-003 naive columns | ⚠️ 7 remain; all writes verified safe |
| INFRA-06-004 eslint `\|\| true` | ✅ removed |
| INFRA-06-005 missing Dockerfiles | ✅ both exist |
| INFRA-06-006 run.sh npm vs pnpm | ✅ pnpm |
| INFRA-06-007 DEPLOYMENT.md counts | ⚠️ went stale again → fixed, now count-independent |
| INFRA-06-008 `ALLOW_LEGACY_ROLE_HEADER` undocumented | ✅ (all 301 now documented) |

## Verdict

**READY in code.** Operational completion needs two owner actions: GitHub billing (CI) and the real API domain in `vercel.json`.

## Update 2026-10-05: GREEN

**CI is green on GitHub** (run 37283792188 on `main`, all 5 jobs: backend on Python 3.11, backend on Windows, frontend, Playwright e2e, security).

Every job was first run locally on a clean clone (owner rule: never push a known-red state). The first two GitHub runs then showed differences that only exist on a fresh runner; each was fixed:
- The test database hit Postgres' default 100 connections. Fixed with a smaller test pool and a CI limit of 300. This also exposed two real memory-isolation bugs, fixed with tests (`CROSS_CHECK_QODER.md`, commits `1c460e03`, `64fefa90`).
- The sandbox Docker images are now built or pulled in CI before the tests.
- `gh` gets the run's own token for the 2 GitHub API tests.
- One Windows-only path assumption in a test was fixed.
- One test depended on `pip list` length under the 6,000-character output cap. Fixed.

`vercel.json` domain: not applicable. The owner runs Gridiron locally with no domain (decision 2026-10-02); revisit at deployment.

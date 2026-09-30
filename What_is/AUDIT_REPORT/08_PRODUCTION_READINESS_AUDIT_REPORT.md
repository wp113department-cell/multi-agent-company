# Audit 08: Master Production Readiness Audit

**Spec:** `files/Audit/08_MASTER_PRODUCTION_READINESS_AUDIT.md` + `00b_AUDIT_STANDARDS.md`
**Date:** 2026-09-30 · **JSON sidecar:** `json/AUDIT_08_PRODUCTION_READINESS.json`

## Result

🟡 **YELLOW: the code is production-ready (every gate green, all defects fixed). Three operational items need the owner before real users: no error tracking or alert destination is configured, CI is blocked by GitHub billing (audit 06), and the daily cost cap must become a hard stop (being built in audit 09).**

**Production readiness score: 84 / 100.**

## 1. Test suite health (freshly observed, 2026-09-30)

| Check | Result |
|---|---|
| Backend full suite | **8,857 passed**, 10 failed, 2 errors, 54 skipped (23 min 31 s). All 12 triaged below; **all fixed / green on re-run** |
| After fixes: targeted regression of everything touched today | **302 / 302 passed** |
| `mypy app/ --strict` | ✅ 0 errors / 495 files (the project's "0 errors" claim holds again; it had regressed to 3 on day 1) |
| `ruff check .` / `black --check .` | ✅ clean |
| Frontend `tsc` / `eslint` / `vitest` / `next build` | ✅ 0 errors / clean / 52 of 52 / build OK (on Next 15.5.26, after the security upgrade) |

**The 12 failures from the full run, triaged:**

| Tests | Cause | Outcome |
|---|---|---|
| 8: SSRF-redirect, OpenAPI fetch, external-docs tests | **Real product bug, surfaced by today's network.** This machine is on an IPv6 **NAT64** network, where every public site resolves to `64:ff9b::/96` + its IPv4. The SSRF guard classed that prefix as "reserved", so **every external fetch was refused** (`fetch_url`, `web_search`, `http_request`, `inspect_openapi_spec`). | **Fixed (PROD-08-001):** the guard now judges the embedded IPv4, so public addresses pass while `64:ff9b::a9fe:a9fe` (= 169.254.169.254 metadata) and every private range stay denied. `tests/test_ssrf_nat64.py` (11 cases); all 8 real-network tests now pass. |
| 2: `test_task_images.py` | Tests compared the exact API payload; the history-caching change (day 1) intentionally adds a cache marker. Images are still sent correctly. | Assertions updated to ignore `cache_control`. |
| 2 errors: `test_terminal_websocket.py` | Transient setup error (Docker container start under load) | Pass on re-run (18 / 18) |

**Skipped tests (54):** all conditional on something absent *by design* in this environment: live-LLM tests (`RUN_PENDING_TESTS`, see `PENDING_TESTS_API_KEYS.md`), Windows-only / root-only paths, optional binaries (k6, reportlab). Tools once reported missing (npm, PyYAML, network to PyPI) **are** present here, so those skips don't fire. No stale skip hides a runnable test.

## 2. Startup and health

| Check | Result |
|---|---|
| Cold start on an empty database | ✅ all 62 migrations apply from zero; full downgrade/upgrade and a per-revision stairway pass (audit 06) |
| All agents registered at startup | ✅ `/health` reports `agents: 85` immediately |
| `/health` meaningful | ✅ checks DB (+ Redis/S3 when enabled); **now 503 when degraded** (audit 06 fix, proved by stopping the real Postgres) |
| Graceful shutdown | ✅ all 23 background loops cancelled and awaited; leader-election engine disposed; all 3 LangGraph checkpointers closed (`main.py` lifespan after `yield`) |
| Warm-up | ✅ repo index built in the background at startup (router/economy work) |

## 3. Observability

| Check | Result |
|---|---|
| Sentry captures request **and** background-task exceptions | ✅ wired (`FastApiIntegration`, `AsyncioIntegration`, `SqlalchemyIntegration`), **but `SENTRY_DSN` is empty**: nothing is captured today |
| Fire-and-forget task errors without Sentry | ❌ → ✅ **fixed (PROD-08-002):** `_spawn_tracked` discarded finished heartbeat/log-write tasks without reading their exception; they are now logged at WARNING |
| Alerts on blocked/failed tasks | ✅ `send_task_alert` fires; the webhook is non-blocking (10 s timeout, errors caught). **But `ALERT_WEBHOOK_URL` / `SLACK_WEBHOOK_URL` are empty**: alerts have nowhere to go |
| Tracing | `OTEL_EXPORTER_ENDPOINT` empty (optional) |
| Error envelope consistency | ✅ backend returns `{"error":{"code","message"}}` or FastAPI `{"detail":…}`; the frontend's `handleResponse` parses both (`apps/web/lib/api.ts:28-37`) |

## 4. Data safety

| Check | Result |
|---|---|
| Log retention during a running task | ✅ retention only **flags** rows `archived=true`; nothing is deleted |
| Checkpoint retention | ❌ → ✅ **fixed (PROD-08-003):** threads whose newest checkpoint was older than 30 days were **deleted even when their plan was still awaiting approval**, so a late "Approve" failed. Now any thread with a pending approval is kept. Test fails on the old code, passes on the new. |
| Backup / restore documented | ✅ `docs/disaster_recovery.md` + `scripts/backup_db.sh` / `restore_db.sh` (pg_dump custom format, verified with `pg_restore --list`, retention count). **Executed restore drill → audit 13.** |

## 5. Rate limiting and abuse resistance

✅ `slowapi` limits on task creation, agent runs and login/refresh (`rate_limit_*` settings); `/health` exempt. Per-IP only, no per-account lockout (audit 05 SEC-05-005, accepted).

## 6. Documentation accuracy

| Doc | Finding | Status |
|---|---|---|
| `README.md` deploy section | `docker build -f backend/Dockerfile .` **fails** (the Dockerfile copies `requirements.txt` from its context; the repo root has none), and `--env-file .env` points at a root `.env` that doesn't exist | ✅ fixed: `docker build -t gridiron-backend backend/`, `--env-file backend/.env` |
| `README.md` quickstart | `pnpm --filter web dev` verified to resolve `@gridiron/web`; env vars exist | ✅ |
| `docs/ADD_A_NEW_AGENT.md` | Stale: no `AGENT_CONTRACT` / `_register()` (an agent without them never enters the fleet), no required `agent_models.json` row, no 7 role sections, no standalone signature, `_REGISTRY` presented as mandatory | ✅ updated (section 1b + checklist) |

## 7. Findings

| ID | Sev | Status | Finding |
|---|---|---|---|
| PROD-08-001 | **High** | FIXED | SSRF guard refused every external fetch on NAT64 (IPv6-only) networks |
| PROD-08-002 | Medium | FIXED | Background task exceptions dropped silently without Sentry |
| PROD-08-003 | Medium | FIXED | Checkpoint retention could delete a plan still awaiting approval |
| PROD-08-004 | Medium | FIXED | README backend deploy commands fail |
| PROD-08-005 | Medium | FIXED | New-agent guide stale versus enforced contract |
| PROD-08-006 | **High** (operational) | **OWNER ACTION** | `SENTRY_DSN`, alert webhook and tracing all empty: in production a failed task is visible only in server logs |
| PROD-08-007 | High | → audit 09 | Daily cost budget is checked only after a run completes, so it doesn't stop further spend (fix scheduled in audit 09) |

## 8. Release decision (this layer)

**NOT YET READY for real users.** Code-level readiness is green. Before real traffic:
1. configure `SENTRY_DSN` and an alert webhook (owner);
2. fix GitHub billing so CI runs (owner, audit 06);
3. make the daily cost cap a hard stop (audit 09, next).

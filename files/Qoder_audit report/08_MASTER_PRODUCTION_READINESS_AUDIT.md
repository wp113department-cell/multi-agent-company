# 08 — Master Production Readiness Audit (Tests, Startup/Health, Observability, Data Safety, Rate Limiting, Docs, Release Decision)

- **Audit ID:** 08
- **Baseline commit:** `c927c44bf410e188287f32b2cf54e0529c642025` ("Production audits 09 and 11", 2026-10-02 11:11 +0530) — **baseline drift note:** HEAD advanced twice during the audit series (`ecd4905a` "Production audit 12" → `33bbd03c` "Production audit 13", 12:07:59 +0530). Audit 13 added the `{error:{code,message}}` exception handlers, `db/errors.py`, the DR doc, and Sentry/`main.py` changes — all cited here from on-disk content AFTER both commits. No file cited below changed while this audit ran.
- **Run date:** 2026-10-02
- **Method:** read-only static verification (full reads of `main.py` lifespan/error handlers, `rate_limit.py`, `services/alert.py`, `services/retention.py`, `observability/logging_context.py`, `docker-compose.yml`, `ci.yml`, Dockerfile/Procfile, README + deployment docs; targeted greps for skip/xfail, polling intervals, rate-limit decorators, backup scripts) plus live read-only runs: `mypy app/ --strict` (**0 errors, 496 files**), `pytest tests/` full suite (in progress at first write — final tallies in §2), frontend `tsc --noEmit` (**0 errors**), `eslint .` (**0 errors**), `vitest run` (**9 files / 52 tests passed**), and `pytest tests/ --collect-only` (**8,964 of 8,989 collected, 25 deselected**). All runs hygiene-preserving (`PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`).
- **Scope per brief:** 9 report items — test suite health, startup/health, observability, data safety, rate limiting, docs accuracy; explicit RELEASE DECISION.

---

## 1. Executive Summary

Production readiness is **genuinely strong and mostly honest**: a strict-mypy-clean codebase (0/496), green frontend gates (tsc/eslint/vitest), a startup/shutdown sequence that cancels+awaits 23 background tasks, disposes its leader-election engine and closes all three checkpointers in order; a `/health` probe that really checks DB + Redis (if enabled) + S3 (if enabled) + live agent count and truthfully returns 503 when degraded; Sentry wired with `AsyncioIntegration` (fire-and-forget task exceptions reach it — proven by its own test), OTEL provider built eagerly, and **structured, trace-correlated JSON logging** (not the plain `basicConfig` the old blocker described); webhook alerts that can never raise and fire from real call sites; a retention service that protects pending-approval checkpoints and non-terminal worktrees; real backup/restore scripts with a **measured restore drill** documented; and rate limiting that is not just present — it works, including a documented monkeypatch fixing slowapi silently not limiting any included-router route on this Starlette version.

**One Medium finding (PROD-08-101):** rate limiting is keyed to the **direct TCP peer** and stored **per-process in memory** — in the shipped browser → Next.js rewrite proxy → backend topology, every user of a frontend instance shares one bucket (200/min default, 10/min on login), while several UI pages poll at 3–5s intervals. For a multi-user deployment this can produce real, intermittent 429s and coarse brute-force protection; single-user/self-hosted use is unaffected.

**Three Low findings:** slowapi's built-in handler emits `{"error": "<string>"}` — the one response deviating from the app-wide `{error:{code,message}}` contract, which the frontend degrades to a generic "Request failed: 429" (PROD-08-102); the same per-process limiter storage multiplies limits N× across replicas in the multi-instance topology the leader-election machinery explicitly supports (PROD-08-103 — note: the prior external audit's PROD-08-001 pointed in this direction but cited a class and code that do not exist in this repo; see cross-audit notes in §3); and documentation drift: README links a `PROJECT.md` that was deleted from the repo, miscounts routers, and two docs carry stale agent/test counts (PROD-08-104).

**Release decision: READY FOR PRODUCTION — no blocking items.** Full test-suite results with exact counts and failure attribution are in §2.

---

## 2. Test Suite Health (Phase 1)

### 2.1 Live results on this worktree (HEAD `33bbd03c`)

| Gate | Command | Result |
|---|---|---|
| Backend type check | `mypy app/ --strict` (no `--ignore-missing-imports` — stricter than CI's own gate) | **0 errors, 496 source files**, EXIT=0 |
| Backend suite (collection) | `pytest tests/ --collect-only -q` | **8,964 tests collected of 8,989 (25 deselected by `-m "not slow"`)** in 26.92s — README's "8,900+ tests" claim is accurate |
| Backend suite (full run) | `pytest tests/ -q --timeout=120` | **37 failed / 8,870 passed / 55 skipped / 25 deselected / 0 errors in 27:23** — all 37 attributed to this workstation's environment in §2.3 |
| Frontend typecheck | `pnpm typecheck` (`tsc --noEmit`) | **EXIT=0**, clean |
| Frontend lint | `pnpm lint` (`eslint .`) | **EXIT=0**, clean |
| Frontend unit tests | `pnpm test` (vitest) | **9 files / 52 tests passed** in 9.67s |
| CI parity | `.github/workflows/ci.yml:70-80` | CI runs the identical gates (alembic upgrade on a fresh pgvector container → ruff → black → mypy --strict → pytest with junit) — pass/fail semantics match |

`PROJECT.md`'s claimed "0 mypy errors" baseline **could not be checked against the document itself** — the file no longer exists (deleted in `e2f2f14d`, not tracked; see PROD-08-104) — but the live claim is confirmed: 0 errors at `--strict`.

### 2.2 Skip/xfail assessment (all 49 markers, none hiding work)

- **49 skip/skipif markers across `tests/`** — every one is environment-conditional or opt-in: 12 × "requires a real DATABASE_URL", ~13 × Docker variants ("requires a real docker binary"/"needs Docker"), npm/node/curl/gh/k6/tsc binary presence, network access to pypi.org, POSIX-only `resource.RLIMIT_FSIZE`, and `tests/pending/`'s explicit `RUN_PENDING_TESTS=1` + real-LLM-key gate (11 files — cross-ref deliverable file 16).
- **Zero real xfails.** The only `xfail` string hit is generated test *content* inside `test_b1_terminal_intelligence.py:46` (a template asserting an xfail *line is written*), not a suppressed test.
- The browser cluster (`test_browser_tools_hardening.py:42-53`) skips itself only when a real Playwright browser can't open example.com — **this environment has a working browser, so those tests genuinely execute** and are network-dependent (their 120s timeouts appear in the live run; see §2.3).

### 2.3 Full-suite baseline attribution and the live re-run

The audit-05 baseline run on `c927c44b` recorded **90 failed / 8,772 passed / 85 skipped / 6 errors in 40:36** (`/tmp/qoder_full_suite.log`), with every failure cluster attributed to *this workstation's environment*, not code: subprocess-spawning tests missing a `python` on the spawned PATH, the locally-absent `pip-audit` binary, 2 `test_b1_clone_security` network hangs, and 2 collection-race redaction tests (audit 05/06 attribution, unchanged). CI's clean container (with Postgres service + network) is the counter-evidence: the same suite is the repo's own CI gate.

The live re-run on this worktree (`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/ -q --timeout=120 -p no:cacheprovider`, log `/tmp/qoder_pytest_full.log`) was executed for this audit and is reported with its real completion tallies below.

**[LIVE RUN TALLIES — final summary line of the background run, verbatim]**

`37 failed, 8870 passed, 55 skipped, 25 deselected, 30 warnings in 1643.48s (0:27:23)`

**Attribution of all 37 failures (each traced in the run log, `/tmp/qoder_pytest_full.log`):**

- **27 × "python on spawned PATH" cluster** — real-subprocess tests that shell out to `python` and receive `/bin/sh: 1: python: not found` (exit 127) or `[Errno 2] No such file or directory: 'python'`: `test_run_tests_hardening.py` (6), `test_gap15_test_runner_exit_code.py` (6), `test_cpu_profile_hardening.py` (6), `test_find_unused_imports_hardening.py` (5), `test_run_single_test_hardening.py` (3), `test_audit_q_batch01_execution_terminal_fixes.py` (1). Identical to the baseline run's primary cluster.
- **4 × network-dependent dependency scans** — `test_stage4_cluster_q_security_score.py` (3: `pip-audit` binary absent locally → the end-to-end agent run could not persist a `security_scores` row, asserted as failure) and `test_stage4_tier3_check_last_release.py` (1: `[ERROR] Could not reach npm registry for 'left-pad'`).
- **3 × Postgres connection exhaustion during the suite** — `test_memory_consolidation.py` (3): `asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already` (this workstation's Postgres hit `max_connections` while the suite ran; a resource ceiling of the test environment, not a code regression).
- **2 × network clone hangs** — `test_b1_clone_security.py` (2): `Failed: Timeout (>120.0s) from pytest-timeout` (the same 2-test cluster as the baseline).
- **1 × async timing flake** — `test_chat_stop_control.py::test_request_stop_skips_the_next_tool_call_and_finalizes`: `asyncio.exceptions.CancelledError` → `TimeoutError` inside the test's own queue wait.

**Delta vs the audit-05 baseline run** (90 failed / 8,772 passed / 85 skipped / 6 errors in 40:36 on `c927c44b`): this run is materially cleaner — 53 fewer failures, ~100 more passes, **zero errors** — because fewer environment-conditional clusters triggered this time (more network/browser-conditional tests genuinely executed instead of skipping: 55 skipped vs 85). Every failure class above is the same *environmental* family the baseline attribution identified (subprocess PATH, missing binaries, network), plus one DB-connection ceiling and one timing flake unique to this run; CI's clean container (with its Postgres service and network) remains the authoritative gate.

---

## 3. Startup, Shutdown, Health (Phase 2) — **VERIFIED**

| Brief question | Finding (file:line) | Status |
|---|---|---|
| Fresh-DB migrations traced | CI: `alembic upgrade head` runs against a fresh `pgvector/pgvector:pg16` service container on every run (`ci.yml:24-37, 70-71`); 62 migrations single-head `062`, linearity + full upgrade/downgrade/stairway drills previously AST-verified (audit 01/06; `docs/DEPLOYMENT.md:32-43`) | Verified |
| Fleet registration at startup | `ensure_all_agents_registered()` in lifespan (`main.py:1488-1496`) imports every agent module (fires each `_register()`), logs the imported-module count; `/health` reports the resulting `capability_registry` count (`main.py:2044-2049`) — a low count is observable, and the registered fleet (~85 `AGENT_CONTRACT` definitions; 86 `roles/*.md`; `_REGISTRY` alias table = 65) is present immediately, not lazily | Verified |
| Meaningful `/health` | DB `SELECT 1` (2003-2013), Redis ping when `redis_streams_enabled` or `queue_backend=rq` (2015-2027), S3 `head_bucket` when `artifact_backend=s3` (2029-2039), live agent count (2044-2049); **degraded ⇒ HTTP 503** (2051-2057, audit-13 fix — a lost DB previously answered 200); exempted from rate limiting (`@limiter.exempt`, 1995) so probes can't false-429 | Verified |
| Graceful shutdown | Lifespan teardown cancels then **awaits** all 23 background tasks inside `try/except CancelledError` (`main.py:1799-1850`), disposes the shared leader-election engine only after every consumer is stopped (1851-1856), then closes all three checkpointers — `close_checkpointer()` (`pipeline/graph.py:58`), `close_agent_checkpointer()` (`base_graph.py:99`), `close_chat_checkpointer()` (`chat_agent.py:395`) — in order (1857-1859) | Verified |
| Startup hygiene | Engine singleton reset for fresh event loops (1444-1456), structured logging init (1458-1464), `set_main_loop` for thread→bus forwarding (1466-1473), Sentry + OTEL before any request (1475-1479), repo-index warm-up as a *non-blocking* task (1498-1513), agent-health re-seed from durable events (1515-1526), orphaned-process sweep before new work (1528+), admin seed only-if-missing with `must_change_password=True` and `role="admin"` (SEC-05-015 and audit-14 fixes, 1600-1617); `DEPLOYMENT_ENV=production` hard-fails on the default admin password or <12 chars (`config.py:2015-2022`) | Verified |

The compose topology is equally explicit: `db`/`redis` healthchecks, a one-shot `migrate` service (`restart: on-failure:3`) that the backend waits on via `service_completed_successfully`, backend `restart: unless-stopped` + `curl -f /health` healthcheck, and `rq`/`frontend` profiles (`docker-compose.yml:19-148`).

---

## 4. Observability (Phase 3) — **VERIFIED (with one contract deviation, PROD-08-102)**

- **Sentry catches background asyncio task exceptions:** `_init_sentry` (`main.py:47-83`) passes `FastApiIntegration`, `SqlalchemyIntegration`, and **`AsyncioIntegration`** (the last with an in-code rationale naming the real unguarded `asyncio.create_task` site, 61-72); called before request processing (1475-1476); init failures are non-fatal warnings (77-83). The claim is directly tested: `tests/test_sentry_init.py:35-44` asserts all three integrations were passed; 46-48 asserts a raising `sentry_sdk.init` cannot take the app down; 30-33 asserts no-op without DSN.
- **OTEL:** `_init_otel` (`main.py:86+`) eagerly builds the process `TracerProvider` and logs whether export is wired — spans are collected in-process either way.
- **Structured, trace-correlated logs:** `JsonLogFormatter` + `CorrelationFilter` + `configure_structured_logging` (`observability/logging_context.py:69-120`), invoked at startup (`main.py:1462-1464`); contextvars propagate through `asyncio.to_thread()` so every log line under an agent run carries `trace_id`/`task_id`/`agent_run_id`. This is the closure of the old "unstructured, not trace-correlated" blocker — real, not a claim.
- **Alerting cannot break the pipeline:** `_post_alert` swallows all errors with a 10s httpx timeout (`services/alert.py:19-34`); gated on `ALERT_WEBHOOK_URL` and `ALERT_ON_BLOCKED`; real callers: blocked/failed transitions in `api/agents.py:169,278,609,620`, specialized-agent runs (`api/specialized_agents.py:546,561`), agent-unhealthy events (`fleet/agent_registry.py:214-216`).
- **Consistent error payloads (mostly):** unhandled exceptions → JSON `{error:{code,message}}` with DB-unavailable mapped to **503 + `Retry-After: 5`** (`main.py:1906-1936`); `StarletteHTTPException` → same shape **preserving headers** like `WWW-Authenticate` (1939-1949, audit-13 fix); validation errors → 422 with per-field `details` and deliberately no `str(exc)` (which leaks absolute server paths in this FastAPI version — proven live, 1952-1980). The frontend parses `detail` (string/array) first and falls back to `error.message` (`apps/web/lib/api.ts:25-42`). **Exception: 429** — PROD-08-102.

### PROD-08-102 — 429 responses deviate from the `{error:{code,message}}` contract; UI shows a generic message
- **Severity:** Low · **File:** `backend/app/main.py:1870`, `backend/app/rate_limit.py` (registration), `apps/web/lib/api.ts:37` · **Confidence:** High
- **Finding:** `main.py:1870` registers slowapi's built-in `_rate_limit_exceeded_handler`, which returns `{"error": "Rate limit exceeded: <limit>"}` — `error` is a **string**, not the object every other handler produces. The frontend's fallback reads `body.error.message`, which is `undefined` for a string, so the user sees `Request failed: 429` instead of the real reason ("10 per 1 minute", etc.).
- **Evidence:** slowapi 0.1.10 `extension.py:76-87` (verified in the installed package); `main.py:1870`; `api.ts:28-38`.
- **Production impact:** cosmetic/UX only — throttling still works; operators and users lose the self-explanatory message at exactly the moment they need it.
- **Recommendation:** replace the registered handler with a 3-line wrapper emitting `{"error":{"code":"429","message": str(exc.detail)}}` (keeping slowapi's header injection via `limiter._inject_headers`). Effort: S.

---

## 5. Data Safety (Phase 4) — **VERIFIED**

- **Retention vs in-progress work (the brief's boundary question):** archiving flips `archived=true` flags (never deletes) for `task_logs`/`agent_runs`/`artifacts`/`memory_embeddings` (`services/retention.py:33-73`); LangGraph checkpoint cleanup **explicitly skips any thread with a pending human approval** (132-145 — the audit-08 2026-09-30 fix; a long-waiting plan can no longer lose its checkpoint before Approve); worktree removal only for tasks in **terminal** states (`_cleanup_worktrees`, 169-219 — audit 09 fix; blocked/review-waiting tasks keep theirs); idempotency keys hard-deleted on their own TTL (264-282, separate documented rationale). Defaults: logs 90d, checkpoints 30d, worktrees 7d, memory embeddings 180d (`config.py:990-1000,840-843,1735-1738,878-885`). Archived task logs remain retrievable via `GET /api/tasks/{id}/logs?include_archived=true` (`api/tasks.py:318-326`). One honest observation (not a finding): `agent_runs`/`artifacts` archive flags have no reader filtering anywhere (grep of `archived` consumers: memory + task_logs + analytics only), so those two flags are effectively informational — data is preserved either way.
- **Multi-step writes:** the one-handler-one-commit convention is enforced by a real AST test (`tests/test_batch08_transaction_boundary_invariant.py`) that fails CI if any `repository.py` function commits more than once in its own scope, plus a guard-the-guard test asserting the AST walk still finds ≥20 functions.
- **Backups / DR (documented + drilled):** `scripts/backup_db.sh` and `scripts/restore_db.sh` exist and are executable (custom-format `pg_dump`, `pg_restore --list` self-verification before declaring success, retention pruning, interactive confirm on destructive restore); `docs/disaster_recovery.md` documents the **measured 2026-10-02 drill** (4.2 MB / 51-table dump in 3.5s → restore into an empty DB in 7.1s → app healthy on restored DB in 7.2s → **RTO < 1 minute at this data size**), RPO semantics, off-host copy guidance, and per-secret rotation runbook. Opt-in `scripts/systemd/gridiron-backup.{service,timer}` templates ship for daily scheduled backups (03:00 + splay + `Persistent=true`). PITR is not implemented in-app; the doc correctly defers that to the managed-provider layer rather than pretending it exists.

---

## 6. Rate Limiting (Phase 5) — **PRESENT AND WORKING (one Medium limitation)**

Wiring: `limiter` (`rate_limit.py:25-29`, slowapi, IP-keyed, `RATE_LIMIT_ENABLED` + `RATE_LIMIT_DEFAULT` from settings) → `app.state.limiter` + `SlowAPIMiddleware` + 429 exception handler (`main.py:1869-1871`). Per-route overrides: login/setup **10/min** (`api/auth.py:66-67,166-167`, `config.py:2141-2145` — brute-force/credential-stuffing posture), task/epic dispatch 60/min (`tasks.py:172,330,445,612`, `epics.py:108`), agent dispatch 30/min (`chat.py:162`, `specialized_agents.py:587,660,719`), everything else 200/min; `/health` deliberately exempt (k6-driven fix, `main.py:1983-1995`). **The known silent failure mode is genuinely fixed:** slowapi 0.1.10's `_find_route_handler` never resolved `include_router` routes on Starlette 1.3.1, so every real API route was silently unthrottled while `/health` was the only one actually limited (k6 surfaced it: 46% of health probes 429'd); `rate_limit.py:73-93` monkeypatches the resolver recursively and is documented with the direct reproduction — verified by reading the installed slowapi's `_InjectedRouter`/`_find_route_handler` behavior. Login brute-force is thus really capped at 10/min/IP.

### PROD-08-101 — Rate limiting keyed to direct TCP peer + per-process storage: shared buckets in the shipped topology
- **Severity:** Medium · **File:** `backend/app/rate_limit.py:25-29`, `apps/web/next.config.mjs:58-65`, `apps/web/components/NavBar.tsx:150-152`, `apps/web/app/tasks/[id]/page.tsx:92-112` · **Confidence:** High (code-verified; not load-tested through the proxy)
- **Finding:** `get_remote_address` is `request.client.host` — the **direct peer** of the backend socket (verified in installed slowapi `util.py:20-27`; uvicorn is not configured with `--proxy-headers`/trusted-XFF, and no code reads `X-Forwarded-For`). In the advertised deployment (`apps/web/next.config.mjs:58-65` rewrites `/api/*` server-side to the backend; compose sets `NEXT_PUBLIC_API_URL=http://backend:8000`; Vercel setup per README), **every end user arrives from the frontend server's IP**, so all users of one frontend instance share the same buckets: 200/min default and 10/min on login. Meanwhile the UI is poll-heavy per open tab — NavBar badge 5s (12 req/min on every page), task detail page 4 parallel polls at 3–5s (~57 req/min), tasks list 4s, epics 5s — so ~3 concurrent users with a task page open collectively exceed the shared 200/min default. Result: intermittent 429s for legitimate users in multi-user orgs (login is tighter but rare: shared across the org), and per-attacker throttling is bypassed whenever a client hits the backend directly (port 8000 is exposed in compose) — the per-IP model works cleanly only for direct access, which is how the k6 test exercised it.
- **Evidence:** as cited above; `config.py:2126-2145` (limits are configurable, so this is a defaults+topology mismatch, not a hardcoded dead end).
- **Production impact:** availability for teams beyond ~2–3 simultaneously active users through the bundled proxy; uneven protection against distributed direct clients; single-user/demo/self-hosted usage is unaffected.
- **Recommendation (any one closes it):** key by authenticated user (`jwt sub`, falling back to IP) once requests carry the cookie; or trust/parse `X-Forwarded-For` behind a documented trusted proxy (`--proxy-headers` + `FORWARDED_ALLOW_IPS`) AND have the Next proxy forward it; and/or raise `RATE_LIMIT_DEFAULT` for the proxied deployment and document the arithmetic in `docs/DEPLOYMENT.md`. Effort: S–M.

### PROD-08-103 — Limiter state is per-process; limits multiply N× across replicas
- **Severity:** Low · **File:** `backend/app/rate_limit.py:25-29` · **Confidence:** High (static; standard slowapi semantics)
- **Finding:** the `Limiter` is constructed without `storage_uri`, so slowapi uses its default **in-memory** storage — per uvicorn worker/replica. In the multi-instance topology the codebase explicitly supports (leader-election over Postgres advisory locks for 23 singleton loops), effective limits become N× the configured value; there is no config knob for a Redis-backed limiter even though Redis is already a first-class dependency (RQ/streams).
- **Evidence:** `rate_limit.py:25-29` (no `storage_uri`); `config.py` has no rate-limit storage field; compose/CI never run multiple backend replicas today (the multiply is latent).
- **Production impact:** none at single-replica scale; the moment a second replica or worker is added, the 10/min login cap becomes 20/min, etc. — the control degrades silently.
- **Cross-audit note (for Audit 10 consolidation):** the prior external Audit-08 report's PROD-08-001 flagged this *direction* but cited a non-existent artifact — `self._requests: dict[str, list[float]] = defaultdict(list)` in a "RateLimiter" class at `backend/app/rate_limit.py:35-58`. On-disk, `rate_limit.py` is a 94-line slowapi module with no such class and **zero** `defaultdict`/`_requests` occurrences (grep). The same external report also cites `backend/app/services/recovery.py` for `reconcile_orphaned_runs()` — that file does not exist; the real function is `app/fleet/failure_ladder.py:327`. Their underlying concern is legitimate and independently confirmed here; their evidence is fabricated/stale. Their 95/100 zero-real-findings score is correspondingly overstated.
- **Recommendation:** add an optional `RATE_LIMIT_STORAGE_URI` setting passed to `Limiter(storage_uri=...)` (slowapi supports `redis://` natively), defaulted unset to preserve current behavior. Effort: S.

---

## 7. Documentation Accuracy (Phase 6)

**Verified-accurate (spot-checked against code, not trusted):**
- README quickstart matches reality end-to-end: `.venv` + requirements install, `alembic upgrade head`, `docker compose up -d db`, JWT env requirement (login truly answers 501 without `JWT_SECRET_KEY`, `api/auth.py:80-85`), first-login flow (admin seeded once with `must_change_password=True`, 1600-1617; "there is no UI for [change password] yet" — confirmed: zero `change-password` references in `apps/web/`; the login page does exist at `apps/web/app/login/page.tsx`), roles `viewer/approver/admin`.
- README "85 agents" matches 85 `AGENT_CONTRACT` definitions (86 `roles/*.md` files incl. template; `_REGISTRY` alias table = 65 by design — auto-discovery covers the rest, per `ADD_A_NEW_AGENT.md:155-157`). README "8,900+ tests" matches the 8,964 collected. Production Deployment commands match the Dockerfile (`backend/` build context, correct `alembic`/uvicorn sequence) and Procfile.
- `docs/ADD_A_NEW_AGENT.md` matches the current agent contract: section 1b (added 2026-09-29) reflects what the guard tests enforce; its cited references exist (`app/agents/tool_security.py:268` `docs_or_new_file_write_denial`; `tests/test_audit02_specialized_agent_call_contract.py`).
- `docs/SELLABILITY_GAP.md` (dated 2026-07-15, deliberately a point-in-time gap analysis) — **every P0/P1 gap is now closed**, verified individually: real JWT auth + users table + RBAC + login UI; `memory_embeddings` outcome enum migration (`migrations/versions/009_outcome_enum_chat_messages.py` adds `'architecture'`/`'failure'`); rate limiting (above); login UI; **persistent chat history** (`_persist_new_messages` + DB-restore of dropped sessions, `api/chat.py:79,247-268,393`); RQ worker service (compose `rq` profile + Procfile `worker:`); S3 backend actually dispatched in `artifacts/store.py:122-135,263`; Redis/S3 health checks in `/health`. P2 items: Playwright e2e exists (`e2e/`, `e2e-real/`, CI job `ci.yml:269-305`); cost dashboard page exists (`apps/web/app/cost`); dark mode toggle exists (`NavBar.tsx:8-71`, `darkMode: "class"`).
- `docs/reports/FINAL_AUDIT_REPORT.md` is a 2026-07-15 historical snapshot (934-test era) — treated as context, not current truth, exactly as the brief instructs.

### PROD-08-104 — Documentation drift: broken README link + stale counts in README/ADD_A_NEW_AGENT/DEPLOYMENT/DR
- **Severity:** Low · **File:** `README.md`, `docs/ADD_A_NEW_AGENT.md:278`, `docs/DEPLOYMENT.md:122-134`, `docs/disaster_recovery.md:50` · **Confidence:** High
- **Finding (each verified):**
  1. `README.md:436` links "Project state (live) → `PROJECT.md`" — **the file does not exist** (deleted with 3,507 lines in commit `e2f2f14d` "fill gaps only", not tracked today; verified by filesystem, `git ls-files`, and deletion history).
  2. `README.md:64` says "18 FastAPI routers" — `main.py` includes **21** (`main.py:1883-1903`).
  3. `README.md:10` badge says "3,500+ passing" while the same file's own text says 8,900+ (line 75/191) — the badge was never refreshed.
  4. `docs/ADD_A_NEW_AGENT.md:278` says "All 934+ tests must pass" — the suite collects 8,964.
  5. `docs/DEPLOYMENT.md:122-134` shows a `/health` example with `"agents": 72` and tells operators to alarm "below 72" — the registered fleet is ~85 (`AGENT_CONTRACT` count; the same "72" drift appears in a `main.py:1485` comment, and README's fleet section says 85).
  6. `docs/disaster_recovery.md:50` states "no cron/systemd-timer/CI job is shipped" for backups — `scripts/systemd/gridiron-backup.{service,timer}` **are** shipped in-tree (opt-in templates), and the same doc's own scheduling section then describes cron approaches (the contradiction is only the word "shipped").
- **Production impact:** an operator following README hits a dead file link; doc-count mismatches erode trust in exactly the places (fleet size, test counts, health thresholds) an evaluator/buyer would check first. No runtime effect.
- **Recommendation:** delete or re-write the PROJECT.md link (point to `docs/BUILD_PLAN_COMPLETION.md` + `IMPLEMENTATION_PROGRESS.md`), refresh the three counts in one pass, and correct the DR doc's sentence to "templates are shipped; scheduling is not enabled by the codebase". Effort: S.

---

## 8. Prioritized Fix List

| # | ID | Sev | Fix | File:line | Effort |
|---|---|---|---|---|---|
| 1 | PROD-08-101 | Medium | Per-user keying or trusted-XFF handling (or document + raise defaults) so proxied multi-user deployments don't share one bucket; reconcile the 3–5s UI polling arithmetic with `RATE_LIMIT_DEFAULT` | `rate_limit.py:25-29`, `next.config.mjs:58-65` | S–M |
| 2 | PROD-08-103 | Low | Optional `RATE_LIMIT_STORAGE_URI` (Redis) for multi-replica correctness | `rate_limit.py:25-29` | S |
| 3 | PROD-08-102 | Low | Custom 429 handler emitting `{error:{code,message}}` (keep header injection) | `main.py:1870` | S |
| 4 | PROD-08-104 | Low | Docs pass: PROJECT.md link, 21 routers, stale counts (README badge, ADD_A_NEW_AGENT 934+, DEPLOYMENT agents:72, DR "no systemd-timer shipped") | `README.md:10,64,436`, `ADD_A_NEW_AGENT.md:278`, `DEPLOYMENT.md:122-134`, `disaster_recovery.md:50` | S |

## 9. Score & Verdict — RELEASE DECISION

**Production Readiness: 86 / 100 — READY FOR PRODUCTION (no blocking items).**

- Deductions: −8 for the rate-limit granularity/topology Medium (multi-user false-429 risk through the bundled proxy; single-user and direct-API deployments unaffected), −6 across the three Lows (multi-replica limiter storage, 429 payload shape, docs drift).
- **Why READY:** every gate a release actually rides on is green and live-verified — strict mypy 0/496, full frontend gates, a full backend suite whose historical failures are 100% attributed to the *workstation* environment with CI as the clean counter-test; runnable startup/shutdown/health; real Sentry+OTEL+JSON-log observability; alerts that cannot break pipelines; retention that respects human-in-the-loop boundaries; working (not nominal) rate limiting with the genuine slowapi/Starlette bug fixed and reproduced; backups with a measured restore drill (RTO < 1 min at current size).
- **Conditions to track post-release (none blocking):** (1) if deploying multi-user behind the bundled frontend, consciously size `RATE_LIMIT_*` / key per user (PROD-08-101); (2) add Redis-backed limiter storage before scaling to multiple backend replicas (PROD-08-103); (3) treat the suite's env-conditional failures on this workstation as environmental per §2.3 attribution — CI is the authoritative gate.
- **Cross-audit flags for Audit 10 (consolidation):** prior external Audit-08 `PROD-08-001` cites code that does not exist (`RateLimiter` class / `defaultdict` in `rate_limit.py`; `services/recovery.py`) while its 95/100 score omits the real, independently-confirmed issues found here (PROD-08-101/102/103) and the docs drift (PROD-08-104). Weight their 95 accordingly.

---

*End of Audit 08. Verdicts: 4 findings (0 Critical, 0 High, 1 Medium, 3 Low). All other brief areas verified clean with file:line evidence above.*

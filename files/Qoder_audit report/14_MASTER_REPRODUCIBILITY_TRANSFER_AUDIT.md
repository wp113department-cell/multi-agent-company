# 14 — Master Independent Reproducibility, Maintainability & Transfer Audit

**Audit date:** 2026-10-02
**Repository:** /home/pc-117/Documents/CRR2906 — "Gridiron Developer Department"
**Commit:** 90dac23bad223ec39413c485d1ddb68f9646975e ("Production audit 14: clean-room reproduction from README; fix onboarding blockers")
**Series baseline:** c927c44b; audits 01–13 of this series executed at this same HEAD (90dac23b) unless noted.
**Worktree:** clean; untracked only `files/Qoder_audit report/`, `files/Antigravity_audit_report/`, `What_is/AUDIT_REPORT/NEXT_PLAN_MONDAY.md` (plus local-only `.env`, `backend/.env`, `.venv`, `node_modules` — all gitignored).
**Environment:** Linux 24.04; Python 3.12 venv; Node/pnpm workspace; Postgres 16+pgvector (`crr2906-db-1`, DB `gridiron_dev`), Redis 7 (`crr2906-redis-1`); Next.js production server on :3100; no real ANTHROPIC/OPENAI keys.
**Operators:** the audit agent acted as **pseudo-independent operator** — repository-only access, no developer interaction, no tribal knowledge supplied, nothing explained. This satisfies the §6 information model but **NOT** the §104 human handoff (no second human engineer available) — recorded as a blocking factor below.

## 0. Method, constraints, and disclosure

The governing user instruction is **strict read-only** (no project code may be modified; only outputs are the numbered reports in `files/Qoder_audit report/` + `json/` sidecars). Per this brief's §3, PASS requires executed evidence; source inspection alone is never PASS.

Because of the engagement's mandated output convention, the §108 output tree (`Audit/14_INDEPENDENT_TRANSFER/…` as 20 separate files) is consolidated here: the full report plus every sub-report's content is embedded as sections of this single document and its JSON sidecar.

Executed evidence in this audit (all isolated; every temporary resource cleaned up and verified):
- **Test A** clean clone; **Test B** empty-database migration chain (throwaway DB); **Test C** backend import; **Test E** RQ worker bootstrap (burst, empty queue); **Test F** backend start → `/health` → SIGTERM shutdown; **Test H** zero-to-login reproduction on a throwaway DB (migrate → boot → admin bootstrap → login → authenticated call → unauthenticated rejection). Plus the Audit 13 restore drill referenced as RESTORE_VERIFIED (dev scale).
- Static verification: 1,948 tracked files; 45/45 `requirements.txt` pins; 100 tracked docs; no machine-specific paths in code; README quickstart commands map to real files; `next.config.mjs` default `NEXT_PUBLIC_API_URL=http://localhost:8000` (:57-63).

## 1. Final Decision

**BLOCKED — INDEPENDENT TRANSFER VERIFICATION INCOMPLETE** (per §96: verification cannot be completed because required access/environment/decision is unavailable).

- **No §94 critical blocker was demonstrated**: clean checkout, dependency manifests, DB creation/migration, backend start, and the critical auth journey were all reproduced first-hand.
- **But GREEN is not issuable**: one **High executed defect** (every SIGTERM shutdown fails; leader loops starve — PROD-14-101), and the audit's central act — handoff to an independent **human** engineer (§104) — could not be performed; production deployment, rollback exercise, LLM journeys, and frontend clean build were likewise not executable in this engagement.
- Reproducibility status per §81: **partially reproducible** (see §3/§4); final transfer status per §96: **BLOCKED**.

## 2. Cross-audit contradiction found and resolved (§1 rule)

**Audit 13 claim contradicted.** Audit 13 (static) recorded graceful shutdown as verified: "~22 tasks cancelled + leader engine disposed + 3 checkpointers closed" (main.py:1790-1859). Executed at the same HEAD: **SIGTERM shutdown fails in 3 of 3 runs** with `sqlalchemy.exc.TimeoutError: QueuePool limit of size 16 overflow 0 reached … timeout 30.00`, raised from `main.py:1848 (await task)` → `main.py:1375 (_run_as_leader → engine.connect())`; uvicorn prints `Application shutdown failed. Exiting.` — the teardown steps at main.py:1855-1859 (leader engine dispose, `close_checkpointer`, `close_agent_checkpointer`, `close_chat_checkpointer`) are **skipped** on this path. The final consolidated truth is updated: the shutdown code exists and cancels the 16 live winner loops, but the overall lifespan shutdown **fails** while awaiting a leader task whose unretrieved pool-timeout exception propagates. Root cause and starvation impact: **PROD-14-101**.

## 3. Executed Reproduction Evidence

**Test A — Clean checkout (§8/§9).** `git clone` of the repository into a fresh temp directory:
```text
clone HEAD: 90dac23bad223ec39413c485d1ddb68f9646975e   (matches audited revision)
git status --porcelain: 0 lines (clean)
tracked files: 1948
.venv absent | node_modules absent | .env absent | backend/.env absent | apps/web/.env.local absent | apps/web/.env absent
key files present: .env.example, backend/.env.example, apps/web/.env.example, backend/requirements.txt,
apps/web/package.json, pnpm-lock.yaml, docker-compose.yml, README.md, scripts/backup_db.sh
```
Verdict: **reproducible** — no hidden ignored-but-required files; all three env templates are tracked.

**Test B — Empty-database migration chain (§14/§15).** Throwaway DB `qoder14_migrate_test`, DATABASE_URL overridden (end-anchored db-name substitution):
```text
createdb qoder14_migrate_test (isolated) → alembic upgrade head → full chain OK
verified: alembic_version = 062 (head); public tables = 47
cleanup: DROP verified — only gridiron_dev + postgres remain
```
Verdict: **reproducible** (zero-to-schema works; complements the Audit 13 restore drill: dump 4.84 MB / 444 TOC / ~1.8 s → restore ~7.5 s → counts identical 414/91/108 at rev 062).

**Test C — Backend import / build sanity.** `.venv/bin/python -c "import app.main"` → OK (Python 3.12; strict mypy 0/496 from the audit-prep baseline).

**Test E — Worker bootstrap (§19).** Queues empty (Redis `LLEN rq:queue:default` = 0; no `rq:*` keys), then:
```text
rq worker gridiron-high gridiron-default --url redis://localhost:6379/0 --burst  (v2.10.0)
→ started; subscribing; listening on gridiron-high, gridiron-default; cleaned registries; "done, quitting"; exit 0
```
Verdict: worker entrypoint (Procfile: `cd backend && rq worker … --with-scheduler`) bootstraps cleanly. Full job execution not run (no LLM key).

**Test F/H — Backend start, health, and the critical auth journey (§18/§25/§26/§32).** Zero-to-login on a **throwaway DB** (`qoder14_auth_test`), overriding only `DATABASE_URL`, `JWT_SECRET_KEY` (fresh random), `JWT_AUTH_ENABLED=true`, `DEFAULT_ADMIN_PASSWORD`:
```text
empty DB → alembic upgrade head → rev 062
uvicorn app.main:app :8001 → /health = 200 {"status":"ok","checks":{"db":"ok"},"db":"ok","agents":85}
POST /api/auth/login {"admin","<default>"} → 200 {"token_type":"bearer","role":"admin","username":"admin","must_change_password":true}
GET /api/auth/me (session cookie) → 200      |      GET /api/tasks (no auth) → 401
cleanup: throwaway DB dropped (only gridiron_dev + postgres remain); cookie/login files removed
```
Verdict: **reproducible** — database, migrations, backend boot, auto-provisioned admin, login, authenticated access, and the authz boundary all reproduced from scratch. (On the persistent dev DB, `/health` at t+22 s and t+85 s was also 200 in two more runs.)

**Test F shutdown — FAILED in 3/3 runs (the High finding).** SIGTERM (at t+50 s, t+120 s, and on the throwaway run):
```text
INFO:  Shutting down → Waiting for application shutdown.
ERROR: Traceback … main.py:1848 in lifespan → await task → main.py:1375 in _run_as_leader → engine.connect()
       → sqlalchemy.exc.TimeoutError: QueuePool limit of size 16 overflow 0 reached, connection timed out, timeout 30.00
ERROR: Application shutdown failed. Exiting.
```

**Not executed (honest UNVERIFIED/BLOCKED):** frontend build from clean clone; full E2E journeys with LLM; production deployment; rollback exercise; autonomous-agent execution; independent **human** handoff. No regressions were introduced (read-only engagement; no repairs).

## 4. §91 Final Transfer Matrix

| Capability | Reproducible | Documented | Independently Tested | Recoverable | Maintainable | Status |
|---|---|---|---|---|---|---|
| Source checkout @ HEAD | Yes (Test A) | README clone steps | Yes (executed) | n/a | Yes | TRANSFERRED |
| Dependency install manifests | Yes (45/45 pins; lockfiles) | README + CI | Partly (existing venv + clone inspection; clean pip install not run) | n/a | Yes | PARTIALLY_TRANSFERRED |
| Configuration (.env) | Yes (3 tracked templates; fresh env vars honored in Test H) | README step 2 | Yes | n/a | Yes | TRANSFERRED |
| Database create + migrate | Yes (Test B, Test H) | README step 4 | Yes | RESTORE_VERIFIED (Audit 13) | Yes | TRANSFERRED |
| Backend build/boot/health | Yes (Tests C/F/H) | README step 5 | Yes | n/a | Yes | TRANSFERRED |
| Auth (login/session/401 boundary) | Yes (Test H) | README step 7 | Yes | n/a | Yes | TRANSFERRED |
| Workers (RQ bootstrap) | Yes (Test E) | Procfile/README | Yes (burst) | Untested | Yes | PARTIALLY_TRANSFERRED |
| Agents/tools runtime | Not executed (LLM-gated) | Extensive docs | No | n/a | Yes (audits 02/12) | BLOCKED |
| Frontend | Runs on :3100 (prebuilt) | README step 6 | No clean build | n/a | Yes | PARTIALLY_TRANSFERRED |
| Deployment | Compose/Dockerfiles/Vercel exist | DEPLOYMENT.md | No | n/a | Yes | BLOCKED (not executed) |
| Rollback | Paths documented | DEPLOYMENT/DR docs | No | Not exercised | Yes | NOT_TRANSFERRED |
| Backup/restore | Scripts + drill | DR doc | Yes (dev scale) | RESTORE_VERIFIED | Yes | PARTIALLY_TRANSFERRED |
| Graceful shutdown/restart | **No — fails 3/3 (PROD-14-101)** | Code+comments claim it | Yes (executed failure) | Deploy restarts still work (process exits) | Needs fix | **NOT_TRANSFERRED** |
| Incident diagnosis | Logs/runbooks exist | 100 docs | No rehearsal | n/a | Yes | BLOCKED |
| Release traceability | Commit hashes only | No release notes since v1.2.0 | No | n/a | Partially | PARTIALLY_TRANSFERRED (**PROD-14-102**) |
| Knowledge transfer to human | n/a | Repo+dosc self-contained | **No second human available** | n/a | Yes | BLOCKED |

## 5. §92 System Reproduction Matrix

| Layer | Clean Setup | Existing Data | Upgrade | Failure | Recovery | Independent Operator |
|---|---|---|---|---|---|---|
| Frontend | Not executed | n/a | n/a | n/a | n/a | BLOCKED |
| API | PASS (Tests F/H) | n/a | n/a | Boot-restart ok; **shutdown fails** | n/a | Partial (agent only) |
| Database | PASS (Test B) | PASS (Audit 13 drill) | PASS (head 062) | untested | RESTORE_VERIFIED | Partial |
| Redis | PASS (healthy, empty queues) | n/a | n/a | untested | untested | Partial |
| Workers | PASS (Test E bootstrap) | n/a | n/a | untested | untested | Partial |
| Agents | Not executed (LLM-gated) | n/a | n/a | untested | untested | BLOCKED |
| Tools | Not executed | n/a | n/a | n/a | n/a | BLOCKED |
| Memory | Migrated tables present | n/a | n/a | untested | untested | No |
| Terminal | Not executed | n/a | n/a | n/a | n/a | BLOCKED |
| Git | Not executed (sandboxed tool) | n/a | n/a | n/a | n/a | No |
| LLM | No keys | n/a | n/a | untested | untested | BLOCKED |
| Storage/files | Worktree only | n/a | n/a | n/a | n/a | Partial |
| Observability | Logs+SSE static (Audit 08/11) | n/a | n/a | untested | n/a | Partial |

## 6. Maintainability Status (§82)

| Subsystem | Status | Basis |
|---|---|---|
| Backend core (app/, 496 modules) | MAINTAINABLE | strict mypy 0/496; 8,900+ tests; module reachability clean (Audit 11); 23 non-test TODOs only |
| Leader/background-loop layer | **HIGH_RISK** | PROD-14-101: pool starvation + shutdown abort; stale comment "all 9" (main.py:1620-1623) misstates 16-name tuple vs ~23 tasks |
| Frontend (apps/web) | MAINTAINABLE | typed API layer (lib/api.ts), 1 TODO, prebuilt production bundle |
| Migrations | NEEDS_DOCUMENTATION | `alembic check` drift (Audit 13 PROD-13-101): 7 tables / 55 indexes; no include_object filters |
| Infrastructure/deploy | MAINTAINABLE | compose (dev/prod), Dockerfiles, CI matrix (Linux+Windows+FE), pinned deps |
| Documentation (100 files) | MAINTAINABLE | README 446 lines complete quickstart; DR 207; DEPLOYMENT 174; matches reality in spot checks (only stale items listed above) |
| Release process | NEEDS_DOCUMENTATION | last tag v1.2.0 (2026-07-16); HEAD +530 commits (PROD-14-102) |

## 7. Findings

### PROD-14-101 — HIGH — Leader-engine pool starvation; every SIGTERM shutdown fails; maintenance loops silently die
`backend/app/main.py`: the shared leader-election engine is sized `pool_size=len(_leader_loop_names)` = **16** (:1628-1648) with `max_overflow=0` (:1342), but **~23 `_run_as_leader` tasks** are created and awaited (:1799-1846). Each leader holds its connection for the entire `run_loop()` lifetime (:1375-1398), so 16 winners occupy all slots; every other leader task blocks in `engine.connect()` until SQLAlchemy's 30 s pool timeout raises `sqlalchemy.exc.TimeoutError` — the exception is stored in the never-awaited task (no runtime log). At SIGTERM, the shutdown loop awaiting each task catches only `asyncio.CancelledError` (:1847-1850); the first stored `TimeoutError` re-raises (cancellation does not interrupt a checkout-blocked task — the traceback is inside `engine.connect`), aborting lifespan: **"Application shutdown failed. Exiting."** — engine dispose and all three checkpointer closes (:1855-1859) are skipped.
**Executed evidence (3/3 runs):** traceback `main.py:1848 → main.py:1375 → pool/impl.py:163 → QueuePool limit of size 16 overflow 0 … timeout 30.00`; `/health` 200 immediately before shutdown in all runs. In a 120 s live run only 19 loops logged "leader for"; `loop:dependency_auto_dispatch`, `loop:bg_process_liveness`, `loop:lesson_store_refresh`, `loop:barot_temp_agent_ttl` logged none. The code comment (:1620-1623) claims the pool is "sized so every loop can hold its own lock-holding connection concurrently" — false (23 > 16). Cross-ref: H-4 (16-name tuple vs 20+ registered loops) — now with executed failure proof; contradicts Audit 13's static shutdown verification (§2).
**Impact:** (1) ungraceful teardown on every deploy/restart — checkpointers/engine not closed, exit code ERROR; (2) leader-gated maintenance loops starve and die silently (no notification) — their coverage silently shrinks on the leader instance; (3) regression tests do not exercise SIGTERM, so CI is green.
**Fix (minimal, per §85):** size the pool ≥ number of consuming tasks (+overflow) or give each loop its own connection; catch `TimeoutError` inside `_run_as_leader` and retry (self-heal); catch `Exception` per task in the shutdown await loop so one task cannot abort teardown; add a SIGTERM clean-shutdown test. Effort: S-M.

### PROD-14-102 — LOW — Release traceability stale: no tag or build stamp maps to the audited revision
Last tag `v1.2.0` (2026-07-16); HEAD 90dac23b is **530 commits beyond**. The running frontend artifact (`.next/BUILD_ID` = `M5LWPUOEqjKn0J4vvrBdv`) is not linked to any commit/tag; production artifact → source tracing relies on manual commit-hash bookkeeping. **Fix:** tag the audited revision and stamp commit SHA into build metadata (frontend env + `/health`). Effort: S.

**Counts: Critical 0 · High 1 · Medium 0 · Low 1 · Total 2.**

## 8. §95 Green-Flag Conditions Checklist

- [x] clean checkout succeeds — **YES (executed)**
- [x] clean environment setup succeeds — partial (existing venv used; clean pip install not executed)
- [x] dependencies reproducible — manifests/pins/lockfiles yes; fresh install not executed
- [x] configuration understood — templates + README; Test H overrides honored
- [x] database can be created/migrated — **YES (executed, empty DB → 062)**
- [ ] frontend can be built — not executed (prebuilt bundle running)
- [x] backend can be built — import + boot **YES (executed)**
- [x] workers can be started — **YES (executed, burst)**
- [ ] critical agents can execute — LLM-gated, not executed
- [ ] critical tools work — not executed at runtime
- [ ] critical E2E journeys work — suite exists (apps/web/e2e-real) but not executed
- [x] authentication works — **YES (executed zero-to-login)**
- [x] authorization works — 401 boundary **YES (executed)**; RBAC matrix static (Audit 05)
- [ ] isolation verified — static only (Audits 03/05)
- [ ] production deployment reproducible — not executed
- [ ] rollback verified — never exercised
- [x] backup restore verified — RESTORE_VERIFIED dev scale (Audit 13)
- [ ] disaster recovery verified — partial (restore yes; failover/chaos no)
- [x] upgrade path verified — head applied + empty→062; pre-migration backup gap (Audit 13)
- [ ] critical incidents diagnosable — no rehearsal
- [x] critical runbooks work — restore/backup drill-executed; others static
- [x] documentation matches reality — spot-checked; only stale items are the two findings' subjects
- [ ] no critical tribal knowledge remains — none found in repo; **independent human handoff not performed** (core BLOCKED item)
- [ ] production artifacts traceable — **NO (PROD-14-102)**
- [x] no critical unresolved regression exists — no repairs performed; baseline suite green-minus-env
- [ ] no critical unknown blocks confidence — shutdown defect + unexecuted runtime gates remain

## 9. Critical Gaps · Human Decisions · Regressions

**Critical gaps (§94):** none demonstrated (install/start/build/migrate/auth all work — reproduced).
**Blocking verification items:** independent human handoff (§104) not performed; production deployment/rollback/LLM journeys/frontend clean build not executable in this engagement.
**Human decisions:** (1) schedule the §104 human handoff with a second engineer; (2) approve/schedule the PROD-14-101 fix before the next production deploy (recommended); (3) release/versioning policy for PROD-14-102.
**Regressions:** none (read-only audit; no code modified; all throwaway resources removed and verified).

## 10. Final Reported Block (§108 format)

```text
FINAL STATUS:  BLOCKED — INDEPENDENT TRANSFER VERIFICATION INCOMPLETE
               (reproducibility per §81: partially reproducible)

CRITICAL BLOCKERS:   NONE demonstrated (no §94 condition found)
CRITICAL UNKNOWN:    Independent human handoff (§104); production deployment;
                     rollback exercise; LLM journeys; frontend clean build
UNRESOLVED REGRESSIONS: NONE (no repairs performed)
HUMAN DECISIONS REQUIRED: 3 (handoff scheduling; PROD-14-101 fix approval; release policy)

INDEPENDENT OPERATOR: audit agent (pseudo-independent: repo-only, no developer contact).
                      A HUMAN independent engineer was NOT available — blocking factor.
REPRODUCTION ENVIRONMENT: Linux 24.04 / Python 3.12 / Postgres16+pgvector / Redis 7 /
                          Next.js :3100; throwaway DBs qoder14_migrate_test & qoder14_auth_test (both dropped)
VERIFIED RELEASE:     90dac23bad223ec39413c485d1ddb68f9646975e (untagged; last tag v1.2.0 +530 commits)
FINAL EVIDENCE LOCATION: this report + json/AUDIT_14_REPRODUCIBILITY_TRANSFER.json;
                         executed-run logs summarized in §3 (temp logs removed after capture)
```

## 11. Evidence Index (spot references)

- `README.md:80-161` (quickstart; 45/45 pinned `backend/requirements.txt`; 9 dev pins); `.env.example`, `backend/.env.example`, `apps/web/.env.example` (all tracked); `apps/web/next.config.mjs:57-63`.
- Tests A/B/C/E/F/H command outputs as quoted in §3 (clean clone; rev 062 + 47 tables; import OK; worker exit 0; `/health` 200 `{…"agents":85…}`; login 200 + `/me` 200 + `/tasks` 401; cleanup verified).
- Shutdown failure traceback and reproduction: 3 runs (t+50 s, t+120 s, throwaway run); `main.py:1342,1375,1620-1648,1799-1846,1847-1859`.
- `Procfile`; `docker-compose.yml` (db/redis/migrate/backend/worker/frontend); `docker-compose.prod.yml`; `.github/workflows/ci.yml` (Python 3.11 Linux+Windows, Node 22), `load-test.yml`.
- `git tag` (v1.0.0/v1.1.0 2026-07-15; v1.2.0 2026-07-16; HEAD +530); `apps/web/.next/BUILD_ID`.
- Cross-cited prior audits: 13 (PROD-13-101/102/103; RESTORE_VERIFIED drill), 11 (dead code, memory), 09 (leaks PROD-09-103/106), 04 (H-4 loop-name tuple), 05 (RBAC), 08 (observability).

# Audit 10: Final Consolidation and Release Decision

**Spec:** `files/Audit/10_MASTER_FINAL_CONSOLIDATION_AUDIT.md` + `00b_AUDIT_STANDARDS.md`
**Date:** 2026-10-02 · **JSON sidecar:** `json/AUDIT_10_FINAL_CONSOLIDATION.json`
**Inputs:** the 13 JSON sidecars of audits 01–09 and 11–14, merged by `evidence/consolidate.py` (output `evidence/consolidate.out.json`), plus each report. Audits 12–14 did not exist when the spec was written; they are included because they found real defects. Their findings count in every list; their scores are shown but not weighted (the spec's weights are kept unchanged).

## 1. Executive summary

Thirteen audits checked the whole system: code, agents, memory, security, infrastructure, AI quality, performance, real browser use, disaster recovery and a from-scratch setup. They found **90 problems**, including **3 Critical** and **25 High**. **77 are now fixed or closed**, each with a test or a re-run as proof, and **no Critical problem remains open**. The weighted readiness score is **87 / 100**.

The system is **ready for local use by its owner today**. It is **not yet ready for real external users**, for four reasons:
1. Database backups are not automatic yet.
2. Failure alerts reach nobody yet (Sentry error tracking is now on; in-app alerts are still to build).
3. The three journeys that need paid AI calls (plan approval, agent run, repository chat) have not been tested end to end in a browser.
4. Automatic CI testing is switched off until the audits are finished (owner's choice).

All four are scheduled, and none needs a redesign.

## 2. Layer scorecard (each audit's stated score and counts)

| # | Layer | Score | Critical | High | Medium | Low | Verdict | Weight |
|---|---|---|---|---|---|---|---|---|
| 01 | Architecture | 92 | 0 | 1 | 2 | 3 | 🟢 GREEN | — (not in spec weights) |
| 02 | Agents | 90 | 0 | 2 | 1 | 3 | 🟢 GREEN | 12% |
| 03 | Memory | 94 | 0 | 1 | 0 | 1 | 🟢 GREEN | 8% |
| 04 | Orchestration | 88 | 0 | 5 | 3 | 1 | 🟢 GREEN | 16% |
| 05 | Security | 90 | 1 | 1 | 2 | 1 | 🟢 GREEN | 18% |
| 06 | Infrastructure | 86 | 0 | 1 | 4 | 3 | 🟡 YELLOW | 10% |
| 07 | AI Evaluation | 72 | 0 | 1 | 2 | 2 | 🟡 YELLOW | 5% |
| 08 | Production Readiness | 84 | 0 | 3 | 4 | 0 | 🟡 YELLOW | 12% |
| 09 | Performance & Scalability | 86 | 0 | 2 | 4 | 4 | 🟢 GREEN | 5% |
| 11 | Zero Policy | 85 | 0 | 1 | 2 | 5 | 🟢 GREEN | 14% |
| 12 | End-to-End | 80 | 0 | 4 | 2 | 1 | 🟡 YELLOW | — |
| 13 | Operations / DR | 82 | 0 | 2 | 3 | 4 | 🟡 YELLOW | — |
| 14 | Reproducibility | 84 | 2 | 1 | 3 | 2 | 🟡 YELLOW | — |
| | **Total** | | **3** | **25** | **32** | **30** | | |

## 3. Master Critical list (all 3 fixed)

| ID | Layer | Where | Finding | Status |
|---|---|---|---|---|
| SEC-05-003 | Security | `apps/web/package.json` | Next.js 15.5.21 had 2 critical remote-code-execution advisories | FIXED (15.5.26) |
| REPRO-14-001 | Reproducibility | `backend/.env.example` | Example DB password ≠ docker-compose: every newcomer's migrations failed | FIXED |
| REPRO-14-002 | Reproducibility | `README.md` | No documented way to log in (501 / 403 everywhere) | FIXED + verified in a clean clone |

**Open Critical: 0.**

## 4. Master High list (25; 23 closed, 2 open)

> **Update 2026-10-02 (same day, after this audit):** PROD-08-006 fixed (Sentry live + in-app failure alerts built and verified in a real browser); OPS-13-006 fixed in code (daily backup service, verified incl. restore). The owner only has to set the backup folder.

**Open (both waiting on the owner):**

| ID | Layer | Finding | State |
|---|---|---|---|
| E2E-12-007 | End-to-End | Plan approval, agent execution, repo chat never verified end to end in a browser (need paid LLM calls) | BLOCKED: owner gives the go for the live LLM plan |
| INFRA-06-001 | Infrastructure | CI has not run since ≥ 2026-08-21 | DEFERRED BY OWNER (Actions disabled until the audits finish). Mitigation: the full suite runs locally (8,892 passed from a clean clone) |

**Closed today after the audit:** OPS-13-006 (backup service; `docker compose --profile backup up -d backup` + `GRIDIRON_BACKUP_DIR`) · PROD-08-006 (Sentry + `GET /api/notifications` + NavBar bell/toast).

**Closed (21 + 2 above):** ARCH-01-001 · AGENT-02-001 · AGENT-02-002 · MEM-03-001 · ORCH-04-001 · ORCH-04-004 · ORCH-04-006 · ORCH-04-007 · PERF-04-008 · SEC-05-001 · AIEVAL-07-001 · PROD-08-001 · PROD-08-007 (closed by PERF-09-001) · PERF-09-001 · PERF-09-002 · ZP-11-001 · E2E-12-001 · E2E-12-002 · E2E-12-003 · OPS-13-001 · REPRO-14-003. Each has its file, evidence and test in its source report.

**Other open items (not release-blocking):**
- **Medium:** AIEVAL-07-003/004 (evals and the quality gate need LLM runs, same live plan as E2E-12-007). REPRO-14-006 was fixed the same day (forced password change now enforced).
- **Low:** AGENT-02-006, ZP-11-005/006/007, PERF-09-010 (owner config), OPS-13-009 (owner).

## 5. Recurring bug patterns from the project's history

| Pattern | Found again this round? | Evidence |
|---|---|---|
| (a) Feature wired into only one of the two entry points (simple vs full mode) | **Yes, fixed:** simple mode dropped task images (ORCH-04-002) and never recorded the push approval, so `/push` failed for every simple-mode task (ORCH-04-003). Same shape: 16 advertised agents could never run (AGENT-02-001) | 04 report §1 parity table; tests |
| (b) Module with zero real callers | **Yes, fixed / documented:** `fleet/providers` removed (ARCH-01-005 → ZP-11-004); `pipeline/dispatcher.dispatch_subtask` test-only (now non-blocking); ~20 unused helpers listed (ZP-11-006). All 85 registered agents are reachable | `evidence/unreferenced_functions.out.json` |
| (c) Timezone-aware vs naive datetime | **Yes, a new variant, fixed:** naive `utcnow()` minus an aware DB timestamp crashed the Review page (E2E-12-002). 7 naive DB columns remain, with writes verified safe (INFRA-06-007, accepted). Time-sensitive tests pass under UTC+14 (audit 14) | 06, 12, 14 reports |
| (d) Sync `asyncio.run()` facade called from async code | **Yes, fixed:** `failure_ladder` raised `RuntimeError` on every call from `run_manager` (ARCH-01-001); `executive` ran a sync graph on the event loop (ORCH-04-001). The old `check_daily_db` facade is no longer called (replaced by `spend_guard`) | 01, 04, 09 reports |
| (e) `task_id` / `trace_id` confusion in events | **No new instance reported.** The historical fix is still in place (`base_graph.py:3903`, `:4376`). **Coverage gap:** no audit this round re-tested it directly; recommend a targeted re-check in audit 04 | — |

## 6. Contradictions between audit reports

Each was resolved by the **later** audit finding and fixing the problem. They're listed because they show where earlier verdicts were too optimistic.

| Earlier claim | Later finding | Lesson |
|---|---|---|
| 05 Security: GREEN, auth reviewed | **13 (OPS-13-001):** any approver could erase every admin and export anyone's data. **12 (E2E-12-003):** every logout was a 500 and never cleared the cookie | Security review was by code reading; only real-stack use and drills exposed these |
| 08: "README quickstart verified ✅" | **14 (REPRO-14-001/002):** a newcomer couldn't run migrations or log in | 08 checked that commands and variables exist, not that a clean setup works |
| 08: "Error envelope consistent ✅" | **13 (OPS-13-002/003):** during a DB outage, text/plain 500s and 401 "Invalid token" (mass logout) | Consistent on the happy path; not under failure |
| 03 Memory: live retrieval verified | 13 drill: every stored memory embedding in the dev DB is a zero vector | **Not a defect:** test-created rows (the test suite blanks the embedding key); 03's live check used Voyage directly. Noted so nobody misreads the DB |

## 7. Weighted readiness score

`overall = Σ(layer score × weight)`, using the spec's weights unchanged:

| Layer | Score × weight | |
|---|---|---|
| Security | 90 × 18% | 16.20 |
| Orchestration | 88 × 16% | 14.08 |
| Zero Policy | 85 × 14% | 11.90 |
| Agents | 90 × 12% | 10.80 |
| Production Readiness | 84 × 12% | 10.08 |
| Infrastructure | 86 × 10% | 8.60 |
| Memory | 94 × 8% | 7.52 |
| AI Evaluation | 72 × 5% | 3.60 |
| Performance & Scalability | 86 × 5% | 4.30 |
| **Total** | | **87.08** |

**Cap rule:** an open Critical in Security, Orchestration or Zero Policy caps the score at 60. There are **none**, so no cap is applied.

**Final score: 87 / 100.**

## 8. RELEASE DECISION

### ❌ NOT READY FOR PRODUCTION (real external users)
### ✅ READY for local, single-owner use (the current deployment)

The reason is the spec's rule: every High must be either resolved, or accepted with a documented mitigation. When this audit ran, four were neither; two were fixed the same day (backups, alerts). **The remaining two wait only on the owner:** the go for the live LLM test run, and re-enabling CI. None is a code-design problem.

## 9. Fixes required before re-review (ordered)

| # | Fix | Closes | Size | How to verify |
|---|---|---|---|---|
| 1 | ✅ **DONE 2026-10-02** · Add an opt-in `backup` service to `docker-compose.yml` running `scripts/backup_db.sh` daily into an owner-chosen off-host folder (14 kept) | OPS-13-006 | Small (1 file + docs) | Start it; a verified `.dump` appears; restore it into a throwaway DB (the audit-13 procedure) |
| 2 | ✅ **DONE 2026-10-02** · In-app failure alerts: when a task becomes blocked or failed, the NavBar shows a bell/toast with a list (backend event → API → UI), with tests | PROD-08-006 (rest) | Medium (few files) | Force a blocked task in the real stack; the notification appears; a Playwright check in `e2e-real` |
| 3 | Owner confirms the Sentry test event `1d8bc3d7…` arrived | PROD-08-006 | Owner | Sentry → Issues |
| 4 | Live LLM plan (Haiku, economy, throwaway repo, ≤ $3.50): L1–L10 including journeys C/D/G | E2E-12-007, AIEVAL-07-003/004 | Medium (runs, not code) | Each recorded in the `PENDING_TESTS_API_KEYS.md` ledger |
| 5 | Re-enable GitHub Actions after billing; one green CI run | INFRA-06-001 | Owner + Small | Green workflow on `main` |
| 6 | ✅ **DONE 2026-10-02** · (Recommended) Enforce the forced password change on the server + a change-password form on the login page | REPRO-14-006 | Medium | Seeded admin blocked until changed; journey test |

After 1–5, re-run this consolidation (`python3 evidence/consolidate.py`). With no open High and no open Critical, the rule gives **READY**.

## 10. Post-launch watch list (from audits 08, 09, 13)

1. **Daily LLM spend:** the `spend_guard` ledger and 429 refusals. The local cap is `COST_BUDGET_DAILY_USD=1`.
2. **Sentry error rate**, especially 503 "Database unavailable" bursts and 502 provider errors with circuit-breaker opens.
3. **Blocked tasks with reason `orphaned`:** they mean the backend restarted mid-run.
4. **Backup freshness:** age of the newest `.dump`.
5. **Agent concurrency vs host CPU:** `MAX_CONCURRENT_AGENT_RUNS` (4–6 recommended on a 6-core host).

## Update 2026-10-05: independent cross-checks

| Audit | Real bugs it found that we had missed | Result |
|---|---|---|
| Antigravity (`CROSS_CHECK_ANTIGRAVITY.md`) | 0 (4 claims false; 1 phantom manifest entry removed) | 🟢 GREEN |
| Qoder (`CROSS_CHECK_QODER.md`) | 5 High + 9 Medium + several Low: all fixed, each with a test that fails on the old code | 🟢 GREEN after fixes; 2 owner decisions (ORCH-04-103/104 epic lifecycle, SEC-05-102 policy engine v2) |

Running the CI pipeline locally before pushing (owner rule) also caught: an unformatted file, **13 new PyJWT advisories** (upgraded 2.13.0 → 2.15.1) and **5 new npm advisories** in ESLint's dev tree (fixed; 1 unpatchable dev-only `braces` advisory ignored explicitly).

## Coverage notes for the next review

- Pattern (e), `task_id`/`trace_id`: add a direct test (audit 04).
- Two independent audits (Antigravity, Qoder) were running at the same time as this one. Comparing them is the next step: every finding only they report gets verified in the code.

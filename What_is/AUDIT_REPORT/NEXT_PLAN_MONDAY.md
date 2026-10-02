# Monday plan: finish the audit and the final report

Written 2026-10-02 (end of day). Status then: 13 of 14 audits done (7 GREEN, 6 YELLOW, audit 10 pending).
4 local commits not yet pushed: `c927c44b`, `ecd4905a`, `33bbd03c`, `90dac23b`.

**Start of day:** start Docker → `docker compose up -d db redis` → health check → confirm the Antigravity and Qoder audits are finished before steps 3–4.

**Rules (unchanged):** don't break working features · commit only my files (never `files/Antigravity_audit_report/` or `files/Qoder_audit report/`) · never stop the shared `crr2906` containers (use isolated containers for drills) · no Anthropic spend before step 2C, then Haiku/economy only, stop at **$3.50**, keep **$1** for the owner · push only when asked.

## Owner decisions (2026-10-02, end of day)

| # | Item | Decision | State |
|---|---|---|---|
| 1 | GitHub CI | Owner disabled Actions; billing + CI **after all audits** | Deferred by owner → audit 06 records "accepted, owner deferred" |
| 2 | Domain / `vercel.json` | **No domain, runs locally** | Not applicable until deployment |
| 3 | Sentry | DSN added, test event confirmed by owner; it caught a real bug (4 background loops never ran, fixed) and test noise (tests no longer report) | ✅ Done |
| 4 | Alerts | In-app (UI) notifications | ✅ Done (NavBar bell + toast) |
| 5 | Backups | **Option A**, folder `./backups` (owner agreed 2026-10-02; copy weekly to USB/Drive) | ✅ **Running**: first backup verified; daily, 14 kept |
| 6 | Live LLM tests ($3.50) | **Wait**: owner says when. Estimate everything $2.96–4.56; without L6 $2.26–3.86; L6 can come from normal use | **PENDING, do not start** until the owner says go |
| 7 | Real admin | Account `wp113.department@gmail.com`, role admin, created; login + admin-only actions verified | ✅ done. (Old `admin` user still exists as approver; owner may remove it later) |

---

## 1. Complete the last audit: 10 (Final Consolidation)

- Read the audit 10 spec (`files/Audit/10_*`).
- Combine audits 01–09 and 11–14 into one report: every finding, its severity, its status (fixed / open / owner / blocked) and the proof (test or evidence script).
- One deduplicated **owner action list** and one **production verdict**.
- Output: `What_is/AUDIT_REPORT/10_FINAL_CONSOLIDATION_AUDIT_REPORT.md` + `json/AUDIT_10_*.json`.

## 2. Turn every YELLOW into GREEN, one by one

| Audit | Why YELLOW | What closes it | Who |
|---|---|---|---|
| 14 Fresh setup | must-change-password not enforced; independent operator | **A.** Server gate (only change-password/logout allowed until changed) + change-password form on the login page, with tests | me |
| 13 Operations | backups not scheduled | **B.** Owner adds the cron line (`docs/disaster_recovery.md`), or I add an opt-in `backup` service to docker-compose (ask first) | owner / me |
| 08 Production readiness | no Sentry / alert webhook | Owner creates the Sentry DSN + webhook → I verify an error and an alert really arrive | owner → me |
| 06 Infrastructure | CI blocked by GitHub billing; `vercel.json` placeholder | Owner fixes billing and gives the real domain → I verify a green CI run | owner → me |
| 07 AI evaluation | live evals need credit | **C.** Live LLM plan (below) | me (money) |
| 12 End-to-end | journeys C/D/G need LLM | **C.** Live LLM plan, L8–L10 | me (money) |

**C. Live LLM plan** (`PENDING_TESTS_API_KEYS.md` sections L + M):
1. Free dry run of `tests/pending` with a fake LLM → fix stale tests first ($0).
2. Set `COST_MODE=economy`; the hard daily cap is the safety net (`fleet/spend_guard.py`).
3. Run L1–L10 one at a time, Haiku, a throwaway repo (never the project repo); record each cost in the section M ledger.
4. Stop at $3.50 total. Whatever doesn't fit stays documented as BLOCKED.

## 3. Compare with the Antigravity audit (`files/Antigravity_audit_report/`, when finished)

- For each finding: **both found it** / **only Antigravity** / **only us**.
- Every finding only Antigravity reports: verify it in the code. If real → fix with a test. If not → write down why (with proof).
- Compare the GREEN/YELLOW verdict per audit; explain any disagreement.

## 4. Compare with the Qoder audit (`files/Qoder_audit report/`, when finished)

Same method as step 3.

## 5. Final report

- Update audit 10 with the fixes from steps 2–4.
- Full regression: backend suite, frontend checks, real browser journeys.
- One page for the owner: final status of all 14 audits, what was fixed, what each of the three audits found, and what is left (owner-only items).
- Commit; push when the owner says.

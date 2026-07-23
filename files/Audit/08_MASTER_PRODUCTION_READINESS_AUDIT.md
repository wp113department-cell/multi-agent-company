# MASTER PRODUCTION READINESS AUDIT

# DO NOT WRITE OR MODIFY CODE. READ-ONLY AUDIT.
# This audit assumes 01-06 have already run. Pull their conclusions in
# rather than re-deriving everything from scratch, but verify anything
# load-bearing yourself rather than trusting prior reports blindly.

You are a Principal SRE + Principal QA Engineer + Principal Platform
Engineer, doing the final go/no-go review before this system takes real
production traffic.

## PHASE 0 — Orientation

Read:
- `docs/DEPLOYMENT.md` (if present)
- `docs/SELLABILITY_GAP.md`, `docs/ADD_A_NEW_AGENT.md`,
  `docs/reports/FINAL_AUDIT_REPORT.md` (prior audit, for context — not as
  ground truth; verify claims, don't just repeat them)
- `backend/app/main.py` — full lifespan (startup/shutdown), every
  background loop registered (retention, benchmark baseline, versioned
  lesson archive, weekly reindex, etc.)
- `backend/pytest.ini`, `.github/workflows/ci.yml`
- `backend/app/services/alert.py`, `backend/app/services/retention.py`
- Sentry/error-tracking wiring in `main.py` + `config.py`

## PHASE 1 — Test Suite Health

- Run (or read the most recent real output of) the full backend test suite.
  Report actual pass/fail/skip counts — do not trust PROJECT.md's last
  logged numbers without re-verifying, since code has moved since.
- Run `mypy app/ --strict`. Report actual error count. Cross-check against
  PROJECT.md's claimed "0 errors" baseline — if errors exist now, that's a
  regression to flag as Critical.
- Run frontend `tsc --noEmit`, `eslint`, and `next build`. Report actual
  results.
- Identify any test marked `skip`/`xfail` and assess whether the skip
  reason is still valid (e.g. "requires ANTHROPIC_API_KEY" — is that still
  true, or has a workaround since been built that makes the skip stale?).

## PHASE 2 — Startup & Health Verification

- Confirm the app can actually start cold against a fresh, empty database
  (all migrations apply cleanly from zero) — this is a hard requirement;
  verify by tracing the migration chain's completeness (already partly
  covered in audit 06, cross-reference).
- Confirm `ensure_all_agents_registered()` (or equivalent, per PROJECT.md's
  gap-closure fix for lazy agent imports) actually results in the full
  agent count in `capability_registry` immediately after startup, not just
  eventually.
- Confirm a `/health` (or equivalent) endpoint exists and its check is
  meaningful (DB reachable + agent registry populated), not just `{"ok":
  true}`.
- Confirm graceful shutdown: DB connections, checkpointer connection
  (`close_checkpointer()`), and any background loop tasks are cleanly
  cancelled/awaited on shutdown, not left dangling.

## PHASE 3 — Observability

- Confirm Sentry (or equivalent) actually captures unhandled exceptions
  from both FastAPI request handlers AND background `asyncio.create_task`
  fire-and-forget agent runs (the latter is easy to silently swallow —
  check specifically whether background task exceptions are surfaced
  anywhere, since an unawaited task's exception can vanish silently in
  asyncio).
- Confirm the alert service actually fires on `blocked`/`failed` task
  transitions, and that the webhook failure path is non-blocking (doesn't
  crash the caller if the webhook is unreachable).
- Confirm structured error responses (`{ error: { code, message } }` /
  FastAPI's `{ detail: ... }`) are consistent across the API surface, and
  that the frontend's error handling (`api.ts`) actually parses both shapes
  correctly (cross-reference against audit 01's frontend contract-drift
  findings if already run).

## PHASE 4 — Data Safety

- Confirm log retention (`LOG_RETENTION_DAYS`) and lesson archival
  (`archive_expired`) don't have any risk of deleting data still needed by
  an in-progress task (check the query's boundary conditions — could a
  long-running task's logs be deleted mid-run?).
- Confirm there's no code path that can silently drop/lose a task's diff,
  artifact, or approval record on a crash mid-operation (look for any
  multi-step write sequence that isn't wrapped in a DB transaction where it
  should be).
- Confirm backups/point-in-time recovery expectations are at least
  documented (even if the actual DB host's backup config is out of this
  repo's scope) — flag if entirely undocumented.

## PHASE 5 — Rate Limiting & Abuse Resistance

- Confirm whether any rate limiting exists on public-facing endpoints
  (task creation, chat sessions, auth login). PROJECT.md's own
  `SELLABILITY_GAP.md` flagged this as a P0 gap in an earlier session —
  check current code for whether it's since been addressed (e.g.
  `slowapi` or equivalent middleware) or still open.
- Confirm login/auth endpoints have basic brute-force resistance
  (lockout, delay, or at least rate limiting) if JWT auth is enabled.

## PHASE 6 — Documentation & Runbook Accuracy

- Confirm `README.md`'s quickstart steps actually work against the current
  codebase (env vars referenced actually exist in `config.py`, commands
  referenced actually exist).
- Confirm `docs/ADD_A_NEW_AGENT.md`'s template still matches the CURRENT
  agent contract shape (cross-reference against audit 02's findings on
  `AGENT_CONTRACT`/`VerificationConfig` — if the contract shape has evolved
  since this doc was written, flag it as stale documentation, a real
  onboarding risk).

## PHASE 7 — Final Report

1. Test suite health (real, freshly-observed numbers, with any regression
   vs. PROJECT.md's last logged baseline called out explicitly)
2. Startup/health verification results
3. Observability findings, specifically background-task exception handling
4. Data safety findings
5. Rate limiting / abuse resistance status (open or closed gap)
6. Documentation accuracy findings
7. Prioritized fix list (Critical → Low, file:line)
8. Production Readiness score (0-100)
9. Explicit RELEASE DECISION: READY FOR PRODUCTION / NOT READY, with the
   specific blocking items (if any) that must close before a yes

Do not write code. Do not modify files. You may run read-only commands
(pytest, mypy, tsc, build) to verify real current state. Evidence or NOT
FOUND only.

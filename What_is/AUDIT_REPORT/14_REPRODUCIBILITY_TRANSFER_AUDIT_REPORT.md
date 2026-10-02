# Audit 14: Independent Reproducibility / Maintainability / Transfer

**Spec:** `files/Audit/14_MASTER_INDEPENDENT_REPRODUCIBILITY_MAINTAINABILITY_TRANSFER_AUDIT.md` + `00b_AUDIT_STANDARDS.md`
**Date:** 2026-10-02 · **JSON sidecar:** `json/AUDIT_14_REPRODUCIBILITY_TRANSFER.json`

## Result

🟡 **YELLOW: a fresh clone set up only from the README now reaches a working, logged-in app, a passing full test suite and passing real browser journeys. Getting there found 2 blockers that stopped every newcomer cold (wrong database password in `.env.example`; no way to log in) plus 4 smaller reproducibility bugs, all fixed. YELLOW, not GREEN, because the spec's independent-operator gate needs a different person on a different machine, which only you can arrange.**

**Score: 84 / 100.**

## Method: a real clean room

`git clone` of the committed HEAD (`33bbd03c`) into `/tmp/gridiron-cleanroom`, then the README followed **literally**. The only deviation was database port 5433, because your dev database holds 5432. It had its own database container and volume, and a fake Anthropic key (no spend). Everything was removed afterwards.

| README step | Result |
|---|---|
| Clone | ✅ 21 MB working tree; no `.env` and no secrets in the clone |
| 1. venv + `pip install -r requirements.txt -r requirements-dev.txt` | ✅ 6 min, `pip check` clean (Python 3.12.3) |
| 2. `cp .env.example .env` | ✅ |
| 3. `docker compose up -d db` | ✅ |
| 4. `alembic upgrade head` | ❌ → ✅ **REPRO-14-001 (Blocker):** `password authentication failed`. `.env.example` used password `gridiron`, but docker-compose creates `gridiron_dev_only`. **Every newcomer stopped here.** Fixed; then 062 (head) on an empty database. |
| 5. `uvicorn app.main:app` | ✅ healthy on first start (`db ok`, 85 agents); **zero warnings or errors** in the startup log |
| (log in) | ❌ → ✅ **REPRO-14-002 (Blocker):** with the example config, login → 501 "JWT auth is not configured" and every API call → 403. The README never said how to log in. Now documented (step 2: `JWT_SECRET_KEY` + `JWT_AUTH_ENABLED=true`; new step 7 "First login"), and the exact recipe was verified in the clean room: seeded admin → login → change password → re-login → create task 201 |
| 6. `pnpm install` (frozen lockfile) + `next build` | ✅ lockfile matches exactly; production build OK |
| README quality commands | ✅ `mypy --strict` 0 issues / 496 files · `ruff` clean · `black` 1,233 unchanged · web `tsc` / `eslint` clean · vitest 52/52 |
| **Real browser journeys** (audit 12 spec) on the clean install | ✅ **6/6**: login, wrong password, API without session, create task, 16-page tour, logout |
| **Full backend suite from the clean clone** | ✅ **8,892 passed** · 57 skipped. Of 15 failures: 10 passed on re-run (two other full suites were sharing Docker/Redis at the same time) and 5 were a real reproducibility bug (REPRO-14-005), now fixed: 22/22 pass from `/tmp` and from your repo |

## Findings

| ID | Sev | Status | Finding | Fix |
|---|---|---|---|---|
| REPRO-14-001 | **Critical** (onboarding) | FIXED | `.env.example` DB password ≠ docker-compose password → migrations fail | Example uses `gridiron_dev_only` (your own `.env` uses the same, checked without printing it); also fixed in `tests/pending` docs and `PENDING_TESTS_API_KEYS.md` |
| REPRO-14-002 | **Critical** (onboarding) | FIXED | No documented way to log in (501 / 403 everywhere) | README step 2 + new step 7, verified end to end |
| REPRO-14-003 | High | FIXED | **The auto-seeded `admin` account had role `approver`**, so after audit 13's admin-only fix **no install had any admin**. This is why your own `admin` is an approver. | Seeded with `role="admin"` (`main.py`). Your existing account is unchanged; optional SQL in the summary |
| REPRO-14-004 | Medium | FIXED | `.env.example` set `TARGET_REPO_PATH=/home/pc-117/Documents/CRR2906`, this machine's path | `TARGET_REPO_PATH=.` with an explanation |
| REPRO-14-005 | Medium | FIXED | 10 test files hard-coded this machine: `/home/pc-117/...` (9 files) or pinned the allowed workspace to `/home` while reading the checkout (`test_git_service.py`). They fail on any other machine or checkout location. | Repo root computed from the file's location; workspace pin = the checkout's parent; home dir from `Path.home()` |
| REPRO-14-006 | Medium | **FIXED (same day)** | "Must change password" was not enforced: the seeded admin can work without changing `gridiron123`, and the UI has no change-password screen (API only). Production refuses to start with `gridiron123`, which limits the risk. | Server middleware blocks every API call (403 `password_change_required`) until changed, reading the DB flag (refresh can't bypass it); the login page shows a change-password step; a real-browser journey (A5) proves it. The login page also shows the backend's real error message now instead of "HTTP 401" |
| REPRO-14-007 | Low | FIXED | `DEVOPS_BASH_ALLOWLIST` unquoted (spaces) → loading `.env` from a shell fails | Quoted; the app reads the identical value (verified) |
| REPRO-14-008 | Low | FIXED | README stale: "72 agents" (85), "3,500+ tests" (8,900+) | Updated |

## Machine and environment independence

| Check | Result |
|---|---|
| Absolute paths of this machine in code, tests or config | 11 → **0** in maintained files (old dated reports kept as history) |
| Timezone / locale | Time-sensitive tests (retention, budget, spend, metrics, schedules, expiry: 210 tests) re-run as **UTC+14 with `LANG=C`**: all pass. The 2 first-run failures came from a concurrent suite and pass in full (11/11) under UTC+14 |
| Toolchain pins | `packageManager: pnpm@11.9.0`, Node ≥ 20, Python 3.11+ (3.12 used); pinned `requirements*.txt` and `pnpm-lock.yaml` reproduce exactly |
| Docker | Required: compose DB, the agent bash sandbox and the terminal (stated in the README) |

## Maintainability notes (no action taken)

- Very large modules: `agents/tools.py` (~5,400 lines), `agents/chat_agent.py` (~4,700), `agents/base_graph.py` (~4,400). Well commented, but a newcomer's hardest area. Split on future work, not during an audit.
- Every audit since 01 left **evidence scripts** in `What_is/AUDIT_REPORT/evidence/` that a maintainer can re-run.
- `backend/.venv` sits in old git history (131 MB clone; audit 13, OPS-13-009).

## Not possible here

The spec's **independent operator** gate (a different person on a different machine, using only the docs) can't be done by me on your machine. The clean room is the closest equivalent; the machine-path and timezone fixes remove the failures it would have found. Owner: hand the repo plus README to someone else once.

## Tests

- The clean-room full suite (above) is the main proof; log kept in the session scratchpad.
- Changed: `tests/test_git_service.py` (22/22 from `/tmp` and from the repo), 9 files with computed repo root (63 passed + the 3 pending modules import and resolve the same path).

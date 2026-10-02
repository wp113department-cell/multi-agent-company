# Cross-check: Antigravity audit vs. our audit

**Date:** 2026-10-02 · **Source:** `files/Antigravity_audit_report/` (16 files, 1,595 lines)
**Method:** every finding, recommendation and factual claim Antigravity made was checked against the real code, the real database or a running app. Nothing was taken on trust from either audit.

## Result

🟢 **GREEN FLAG.** Antigravity reported **0 Critical / 0 High** findings and **no bugs**. Of its 10 suggestions:
- **4 are factually wrong** (hallucinated).
- **3 are known, accepted limits** (already in our audits).
- **2 are optional improvements** (one of them deliberate behaviour).
- **1 led to a small real cleanup:** a phantom tool entry, removed and now guarded by a test.

No Antigravity item revealed a bug in the product.

It also **missed every real bug** that only running the system exposed (see the last section). Its "production ready, 95.2 %, 0 red flags" verdict was reached by reading the code, and several of its descriptions don't match the code. Our verdict stands: **ready for local use; 2 open High items, both waiting on the owner** (live LLM test run, CI).

## Antigravity's findings, verified

| # | Antigravity claim | Verified fact | Verdict |
|---|---|---|---|
| A1 | `compress: false` in `next.config.mjs` (Medium) | True, and **deliberate**: the comment explains that compression would hold back live SSE streams; compression belongs in a reverse proxy | Not a bug (design). Note kept for deployment |
| A2 | Add a test that every manifest tool is reachable (Low) | Good idea. Running it found **2** unreachable entries: **`type`**, a phantom from Day 0 with no handler anywhere (removed), and `capability_gap_scan`, deliberately used only by `agent_advisor`'s scan loop (documented in `test_capability_gap_scan_hardening.py`, kept) | ✅ **Small fix applied:** phantom removed, `tests/test_tool_manifest_reachability.py` added |
| A3 | Add `coder` etc. to `RESUMABLE_AGENTS` (Low) | **No `RESUMABLE_AGENTS` list exists.** Resumability is detected from each agent's signature (`resume_trace_id`), and extending it is a documented incremental follow-up | ❌ Claim wrong (target code doesn't exist); extension = optional enhancement |
| A4 | "13 review role files return empty guidance" + a parser patch (Low) | **0** role files have a Process section that parses empty. 12 have no Process section, and returning `[]` is the intended "never fabricate steps" behaviour. **Their patch (take any `-` bullet in the whole file) would invent fake steps** | ❌ Claim wrong; patch rejected |
| A5 | Batch embeddings on fan-out (Low) | True that lessons embed one at a time; a latency idea, not a defect | Optional enhancement |
| A6 | In-memory semaphores = single-pod limit (Low) | True and known (our PERF-09-008, single-server design) | Known / accepted |
| A7 | "Sandbox uses host docker socket bind mount in production compose" (Low) | **False.** Neither compose file mounts `docker.sock`; both explicitly refuse to (comment: socket access = host root) | ❌ Hallucinated |
| A8 | In-memory rate limiter per replica (Low) | True and known (our SEC-05-005, accepted) | Known / accepted |
| A9 | "DB pool size hard-coded in `session.py`; expose `DB_POOL_SIZE`" (Low) | **False.** It's already `settings.db_pool_size` / `db_pool_max_overflow` (config + `.env`) | ❌ Hallucinated |
| A10 | Pending LLM test list (`16_PENDING_LLM_TESTS.md`) | **4 of the 5 test files it names don't exist** (`tests/evals/test_coding_benchmarks.py`, `test_architecture_evals.py`, `test_security_evals.py`, `tests/pending/test_live_claude_pipeline.py`) | ❌ Hallucinated. Our `PENDING_TESTS_API_KEYS.md` (L1–L10, 49 real tests) stays the source of truth |

## Other Antigravity statements that don't match the code

| Statement | Reality |
|---|---|
| `/review` uses `GET /api/repo/diff` + `POST /api/approvals` and works | It calls `/api/epics/batch-review`, which **returned 500 on every load** until our audit 12 fixed it |
| `/cost` uses `GET /api/fleet/budget` | No such endpoint exists |
| Role hierarchy `admin > engineer > viewer` | Roles are `viewer`, `approver`, `admin`; there is no "engineer" |
| "Pydantic schema validation on all `submit_*` tools" (zero hallucination) | Validation exists but a mismatch is a soft warning (our ZP-11-008) |
| "Mypy 0 errors across 176 files" | 0 errors across **498** files |
| "Orphaned run reconciler auto-resuming crashed runs" | Only agents with a resume signature are resumed; the rest are marked failed (and, since audit 13, their tasks are blocked with a reason) |

## Real bugs Antigravity did not find (found by running the system)

| Our ID | Bug | How it was found |
|---|---|---|
| E2E-12-001/002 | Daily Review page: 500 on every load, then a datetime crash | real browser journey |
| E2E-12-003 | Every logout was a 500; session cookie never cleared | real browser journey |
| OPS-13-001 | Any approver could erase every admin account and export anyone's data | live drill |
| OPS-13-002/003 | DB outage → text/plain 500s and mass logout | live drill (Postgres stopped) |
| REPRO-14-001/002 | A newcomer could not run migrations or log in | clean-room clone |
| Sentry #2 | 4 background loops never ran (pool sized for 16 of 20) | Sentry, on its first day |
| PERF-09-001/002 | Daily budget never stopped spend; thread pool starved agents | code + probe |

## Changes made from this cross-check

- `backend/app/fleet/tool_manifest.py`: removed the phantom `type` entry.
- `backend/tests/test_tool_manifest_reachability.py`: every manifest tool must be declared by some agent (one documented exception).
- Tests: 94 passed in the tool / manifest / capability / advisor suites.

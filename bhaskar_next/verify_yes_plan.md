# Gridiron Audit Follow-Through — Master Plan

Baseline (from `GRIDIRON_PARTIAL_NO_IMPLEMENTATION_PLAN.txt`): 394 YES · 61 PARTIAL · 14 NO · 50 SKIP = 519.

| Task | Scope | When | Output |
|---|---|---|---|
| **0** | Environment baseline (DB, Redis, real test baseline, API budget ledger) | Day 0 (first thing after "start") | Clean, trusted test baseline |
| **1** | Verify all 394 YES — real or myth | **Days 1–11 (+ Day 12 re-tally)** — main focus | `verify_yes_tracking.md` fully resolved + honest re-count |
| **2** | Enhance the 61 PARTIAL to production | Next week | Per-item plan already in the source file; re-ordered using Task 1 findings |
| **3** | Implement the 14 NO | After Task 2 | Design-first per `plan14_implement.md` |
| **4** | 50 SKIP | No work | Stay excluded (listed in the source file) |

Tasks 2 and 3 are only sketched here. Task 1 is the one we work.

---

## Task 1 — how one YES item is verified

"YES" is treated as a claim, not a fact. The history of this repo shows the three ways a YES turns out to be a myth, so every item is checked against all three:

1. **Built but never called** — the code exists and has unit tests, but nothing in the live path calls it (seen 7+ times in the Day 0–18 audits).
2. **Advertised but not dispatched** — listed as a tool/route/flag but the real entry point falls through to "Unknown tool" (dozens of tools in the tool-enhance run).
3. **Green tests that prove nothing** — the test mocks the very thing the YES claims, so it passes even when the feature is broken.

Per-item procedure (in this order, stop early only when the verdict is already certain):

1. **Restate the claim** in one line: what would have to be true for this YES to be honest.
2. **Locate** the code (`file:line`) and the tests that are supposed to cover it.
3. **Wiring check** — grep for real callers on the live path (API route → orchestrator → agent → tool). No caller = not YES.
4. **Test-quality check** — read the test; does it hit the real thing or a mock of it? Run it.
5. **Real execution** at the cheapest level that can falsify the claim: real Postgres, real Docker sandbox, real HTTP via the live backend, hostile/edge inputs. LLM only if the claim is about LLM behavior (see budget rules).
6. **Verdict** written into `verify_yes_tracking.md` with evidence (file:line, test names, command + observed result).
7. **If broken:** fix → add a regression test that fails before / passes after → re-run the item and its neighbours → verdict `FIXED`. If the fix is really a new feature (not a bug), don't build it here: `DOWNGRADED→PARTIAL/NO`, moved to Task 2/3 with the evidence.

Verdicts: `CONFIRMED` · `FIXED` · `DOWNGRADED→PARTIAL` · `DOWNGRADED→NO` · `BLOCKED` (can't be verified in this environment, with reason — never silently counted as confirmed).

**Depth tiers** (set per batch, so effort goes where a false YES costs the most):
- **Deep** — security, data integrity, approvals, sandbox, auth, recovery. Real DB + real Docker + adversarial inputs. Wiring proven end-to-end.
- **Standard** — code + wiring + targeted tests + real call where cheap.
- **Light** — output-producing tools (parsers, doc generators, domain agents): run against a real directory/repo, inspect the actual output.

## Schedule — Task 1 (394 items, 11 batches)

| Day | Batch | Items | Depth | Sections |
|---|---|---:|---|---|
| 0 | Environment baseline | — | — | see below |
| 1 | **B1** Repo execution, terminals & file ops | 36 | Deep | §1, 17, 58, 18, 59, 15 |
| 2 | **B2** Orchestration, selection, runtime decisions | 25 | Deep | §2, 3, 4, 62, 47 |
| 3 | **B3** Human control, approvals, recovery, reliability | 37 | Deep | §13, 39, 103, 14, 38, 97, 102, 66 |
| 4 | **B4** Memory & knowledge | 33 | Deep | §5, 120, 75, 74, 37, 93, 114, 110 |
| 5 | **B5** Context, cost, confidence, intent, truthfulness | 33 | Standard | §52, 65, 101, 42, 43, 44, 45, 25, 26, 27, 29, 30, 57, 54, 73, 84 |
| 6 | **B6** Agent scaffold, capability audit, skills | 39 | Standard | §6, 7, 72 |
| 7 | **B7** Security, governance, enterprise, frontend/API | 32 | Deep | §21, 22, 96, 85, 95, 48, 77, 9 |
| 8 | **B8** Fleet self-improvement, guardians, health | 33 | Standard | §12, 118, 89, 88, 76, 69, 35, 91, 115 |
| 9 | **B9** Scheduler, metrics, quality gates, scalability, architecture | 37 | Standard | §86, 87, 90, 92, 23, 24, 50, 51, 8, 10, 46 |
| 10 | **B10** File understanding, external knowledge, git, docs, deploy | 46 | Light | §16, 79, 20, 40, 41, 19, 98, 99, 100, 83 |
| 11 | **B11** Testing audit, hidden risks, domain coverage | 43 | Light | §11, BONUS, 71 |
| 12 | **Re-tally & report** | — | — | Final count of the 394; regression full-suite; Task 2/3 lists updated with everything downgraded |

Order is risk-first on purpose: the things that would hurt most if the YES is a myth (execution, orchestration, approvals, memory) come first, and the domain-coverage batch (mostly "does the agent/tool exist and produce real output") comes last.

A "day" is a batch, not a clock promise. If a batch is turning up many bugs it takes longer and the next one waits; I won't skim to hit a date. Fixes found in a batch are finished inside that batch.

## Day 0 — environment baseline (needed before any verdict is trustworthy)

Verified today: nothing is listening on Postgres (5432), Redis or the backend; the project's DB container `crr2906-db-1` is stopped (exited 2 days ago); Docker itself works (v29.7.2); `.venv` has pytest/alembic/uvicorn; `backend/.env` already has `USE_GROQ=true`.

1. Start `db` (+ `redis`) from `docker-compose.yml`, run `alembic upgrade head`, confirm the app connects.
2. One full-suite run in the background, output to a file (not piped through `tail`), ~13–14 min. This replaces the old "400+ ConnectionRefused" noise with a **real baseline**: the list of tests that genuinely fail today. Anything in it is triaged once, up front, so later batches can tell "already broken" from "I broke it".
3. Start the real backend (uvicorn) so real-HTTP checks are possible; confirm `/health` and an authenticated call.
4. Create the API-spend ledger (`bhaskar_next/verify_api_ledger.md`).
5. Record the baseline (pass/fail counts, known failures) at the top of the tracking file.

## Live API budget rules (Anthropic balance is small)

- Default to **Groq** (`USE_GROQ=true` is already set) for anything that only needs "an LLM answered". Anthropic only where the claim is specifically about Claude behavior or Groq can't exercise it (e.g. multimodal, prompt-cache, Claude-specific tool-use).
- When Anthropic is needed: **Haiku 4.5 only**, small inputs, low `max_tokens`. Never Sonnet/Opus without asking you first.
- Most claims are falsifiable without an LLM (wiring, DB behavior, sandbox, auth, approvals, locks). Those get real execution with **no** LLM call. LLM calls are reserved for the small set of items that need them, and I list them per batch before spending.
- Every paid call goes in the ledger (item #, model, tokens in/out, est. cost). Hard stop for me at roughly 60% of the balance; the remaining 40% stays as reserve. Any single call/run estimated above about 10 cents → I ask first.
- Rate-limit failures on Groq are retried once, not looped.

## Working conventions (carried over from the tool-enhancement run)

- Work continuously, one item at a time, batch after batch, until you say stop. "Stop after this batch" means finish the current batch fully, then stop.
- Full-suite runs are 13–14 min → always in the background, output captured to a file, never truncated.
- Pre-existing failures are confirmed with `git stash`, documented, not "fixed" by unrelated code changes.
- Commit per fix (message: `verify #N: <what was broken>`), tracking-file update per batch. Nothing is pushed unless you confirm the push cadence (see below).
- Tracking file is the single source of truth; each batch ends with a short summary here in chat: confirmed / fixed / downgraded / blocked counts + the notable findings.

## Task 2 — 61 PARTIAL (next week, sketch only)

Uses the per-item plans already in `GRIDIRON_PARTIAL_NO_IMPLEMENTATION_PLAN.txt` (items 1–75), but re-ordered after Task 1 because Task 1 will add downgraded items and may show some PARTIALs are already fixed or overstated (the earlier code-verified audit `plan14_implement.md` already found several were overstated). Suggested order:
1. Rollout flips already built (replanning, critique, fan-out, `blocking_until` on remaining agents) — pilot → monitor cost → flip default.
2. Wire-up gaps (confidence → control flow, persisted metrics, retry count, satisfaction signal).
3. Quality gates (security/architecture retry loops, dependency and docs gates).
4. Bigger structural items (worker-agent pause/resume + crash recovery factory, tools.py split, batch-edit, AST rename).
Items the file itself marks "intentional, no action" (#196, #198, #291, #300, #427 scope) are confirmed as closed with a note, not built.

## Task 3 — 14 NO (after Task 2, sketch only)

Design-first, one at a time, using `plan14_implement.md` (delegation + safety together; dynamic subtasks last and most carefully because they touch the manager's dispatch loop). Items whose own plan says "decide the product question first" (#66 tool switching, #171/#494 distributed dispatch) get that decision from you before any code.

## Task 4 — 50 SKIP

No work. They stay excluded and out of the readiness denominator.

---

## Decisions — defaults I will use unless you say otherwise

1. **Budget:** I read "5 bugs" as a **$5** Anthropic balance. Rules above assume that.
2. **Environment:** OK for me to start the existing `db`/`redis` containers and the backend on this machine for verification.
3. **Git:** commit per fix locally; **no push** until you say (the earlier run pushed every tool — tell me if you want that again).
4. **Reports:** per-batch summary in chat + tracking file; no separate per-item report files (the 394-row table replaces them).

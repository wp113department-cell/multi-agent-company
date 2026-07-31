# START HERE — read this file first, before touching any code

This folder is a self-contained continuity package for the "Gridiron Production-Readiness Gap
Closure" 65-day plan running against this repo. It was assembled on **2026-07-31 (Day 34 of 65)**
on a Windows machine, specifically so a brand-new Claude Code session — no memory, no prior
conversation, possibly on a different OS/machine — can pick this work up with full fidelity by
reading files, not by being told a summary.

If you are a Claude Code session reading this for the first time: **read this file, then the three
files below, in this order, before writing or changing anything.**

## Reading order

1. **`PLAN.md`** — the full 65-day plan: scope, per-day deliverables, the Definition of Done that
   applies to every single day, and the standing "Gap Audit Protocol" for re-verifying claimed work.
   This is the contract. Read it in full.
2. **`IMPLEMENTATION_PROGRESS.md`** — an append-only, chronological log, one dated entry per
   day/stage actually completed, each with exact files touched, tests added, before/after regression
   counts, and real bugs found+fixed along the way. **Read the entries from the bottom (most recent)
   upward** to understand current state fast, then read forward from the top if you need full
   history. The last entry tells you exactly what's done and what's next.
3. **`answers.md`** — the underlying 120-question / ~800-sub-answer audit this whole plan is closing
   out. Each sub-item has a YES/PARTIAL/NO/NOT VERIFIED verdict with `file:line` + test-name
   evidence. This is a reference document (grep it for a Q-number or topic when you need the
   evidence trail for a specific claim) — you don't need to read all ~3,700 lines top to bottom.
4. **`claude_memory/`** — copied from a previous Claude Code session's own memory files (originally
   at `~/.claude/projects/.../memory/` on the machine this was written on — that location is
   machine-specific and won't exist on a new machine, hence the copy here). These are useful
   background/history but are **point-in-time notes, not live state** — always trust
   `IMPLEMENTATION_PROGRESS.md`/`answers.md` over anything in here if they conflict.

## Current status as of this snapshot (2026-07-31, Day 34)

- **Stage 0 (Days 1-10): complete**, independently re-audited fresh on Day 34 (not just trusted from
  when it was originally done). 8 of 8 deliverable days re-confirmed with real passing tests. Two
  items are honestly scope-adjusted from the plan's original literal text (not missing, not hidden —
  see `IMPLEMENTATION_PROGRESS.md`'s Day 4 and Day 8-9 entries and `answers.md` Q94/Q21 for exactly
  what changed and why): (a) the global repo-path fallback in `backend/app/api/repo.py` was
  deliberately left in place (found to be legitimately global-scoped) and a different real
  dispatch-race bug was fixed instead; (b) the bash-tool sandbox is real and live-tested but wired
  into 3 of ~15 arbitrary-command handlers, not the full fleet — the other 12 are a named, tracked
  follow-up.
- **Stage 1 (Days 11-34): complete**, independently re-audited fresh on Day 34. 6 of 7 sub-buckets
  (1.1, 1.2, 1.4, 1.5, 1.6, 1.7) re-confirmed live with no issues. Sub-bucket 1.3 (reliability &
  durability) had genuinely working code and passing tests but 6 stale `file:line` citations in
  `answers.md` (line numbers had drifted after a later stage inserted code above them in the same
  file) — found and corrected in this same pass, per the Gap Audit Protocol's own rule ("close real
  gaps before moving on").
- **Full backend regression at last check**: 3,489 passed / 20 failed / 55 skipped / 17 deselected.
  **The 20 failures are a known, pre-existing, Windows-dev-only environment baseline** — not real
  bugs: `test_git_service.py` (hardcoded `/home`-only `ALLOWED_WORKSPACE_PARENT` assumption that
  doesn't match a Windows path), missing `node`/`make`/python-launcher on Windows PATH. **If you are
  running on Linux/Ubuntu, re-run the full suite fresh before assuming this count still applies —
  several of these 20 should now pass instead** (see "If you're on a new OS" below).
- **Frontend regression at last check**: 32/32 passed.
- **Stage 2 (Days 35-57) has NOT started.** The owner explicitly said not to move to Stage 2 until
  told to — **do not start Stage 2 work until the user explicitly gives the go-ahead**, even though
  Stage 0 and Stage 1 are both fully done and audited. This is a deliberate stage-boundary pause, not
  a blocker or an open issue.

## The rules (do not skip any of these — they are why this plan is trustworthy)

1. **Zero hardcoding, zero hallucination.** Every claim needs a real `file:line` citation you
   actually read, not a remembered one. "I cannot verify this" beats a guess.
2. **Full regression suite before and after every change** (`cd backend && .venv/Scripts/python -m
   pytest tests/ -q --tb=short --timeout=180` on Windows, or the Linux-native equivalent — see
   below). A previously-passing test that now fails is always fixed in the change, never in the
   test.
3. **A real, new/updated test proves each item — not "the suite is still green."**
4. **Update `answers.md` and `IMPLEMENTATION_PROGRESS.md` for every single day/item**, same style as
   the existing entries: what changed, why, `file:line` + test-name evidence, exact before/after
   regression counts. This is what makes the next session (possibly you, possibly someone else,
   possibly on another machine entirely) able to trust "done" without re-deriving it from scratch.
5. **The smallest change that satisfies the item.** No drive-by refactors.
6. **Stage boundaries pause for an explicit go-ahead from the owner** — do not assume finishing one
   stage authorizes starting the next.
7. **The Gap Audit Protocol (see `PLAN.md`) can be invoked at any time** — when it is, it means
   re-derive and re-run, never just re-summarize prior reports. When something is found stale or
   drifted (like Stage 1.3's citations were on Day 34), fix it in the same pass, don't defer it.

## If you're on a new OS (e.g. this was written on Windows, you're now on Ubuntu)

This repo was developed primarily on Windows but targets Linux in production (Docker). The move to
a new OS/machine should be low-risk — checked concretely on Day 34, not assumed:
- `.venv/`, `node_modules/`, `.env` are all gitignored — nothing platform-specific is tracked in git.
- No hardcoded Windows (`C:\`) paths exist anywhere in `backend/app`.
- The few genuinely OS-specific code paths (`chat_agent.py`, `tools.py`, `budget_manager.py`) are
  already properly `sys.platform == "win32"`-gated with real Linux branches — this was built
  cross-platform-aware, not Windows-only.
- Expect several of the "known 20" baseline test failures to disappear on Linux (they were Windows-
  path/tooling-specific). Re-run the full suite fresh and record a new baseline count — don't assume
  the old one still applies.
- Specifically re-verify `backend/tests/test_gap21_agent_checkpointer_postgres.py` — on Windows, real
  `AsyncPostgresSaver` checkpointing fell back to in-memory (`MemorySaver`) due to a documented
  psycopg3/`ProactorEventLoop` incompatibility that does not exist on Linux. On Ubuntu it should
  activate for real — confirm this rather than assume it.

**Fresh setup on the new machine:**
```
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head   # against your local Postgres
cd ../apps/web
pnpm install
```
Recreate `.env` (`ANTHROPIC_API_KEY`, `DATABASE_URL`, etc.) — it is not and should not be in git.
Then run the full suite once to get a fresh, real baseline before doing anything else, and compare
it to the counts recorded above.

## What to do next

Read `PLAN.md` and `IMPLEMENTATION_PROGRESS.md`'s latest entries in full, confirm you understand
where things stand, and **wait for the owner's explicit go-ahead before starting Stage 2 (Day 35:
resource/cost/size pre-flight, extending `backend/app/pipeline/cost_controller.py`)**. When given
the go-ahead, continue the same day-by-day, fully-verified, zero-shortcuts discipline this plan has
used through Day 34 — implement, test for real, update both `answers.md` and
`IMPLEMENTATION_PROGRESS.md` with evidence, confirm nothing regressed, then move to the next day.

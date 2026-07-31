# First prompt for a new Claude Code session (paste as-is, then adjust the bracketed line)

Copy everything in the box below and paste it as your very first message to Claude Code once you've
opened this repo on the new machine.

---

This repo has an in-progress, long-running engagement: a 65-day gap-closure plan. Before doing
anything else, read these files in this exact order, in full:

1. `65days_plan/START_HERE.md`
2. `65days_plan/PLAN.md`
3. `65days_plan/IMPLEMENTATION_PROGRESS.md` — read the entries from the bottom (most recent) upward
   first so you know current state fast, then skim forward from the top for full history.
4. `65days_plan/answers.md` — reference only, don't read it cover to cover; grep it for a Q-number
   or topic when you need evidence for a specific claim.
5. `65days_plan/claude_memory/*.md` — background context from earlier sessions. Point-in-time notes,
   not live state — if anything here conflicts with `IMPLEMENTATION_PROGRESS.md` or `answers.md`,
   trust those two, not this.

After reading, do this before writing any code:

- This machine/OS is different from where this was last worked on (moved from Windows to Ubuntu).
  Set up the environment fresh per `START_HERE.md`'s "If you're on a new OS" section (recreate
  `.venv`, `pip install`, `pnpm install`, recreate `.env` — none of these are in git on purpose).
- Run the full backend and frontend test suites yourself and record the real, current counts. Do
  NOT assume the Windows-era baseline numbers in `IMPLEMENTATION_PROGRESS.md` still apply — compare
  against them, but trust what you actually observe right now. Specifically check whether
  `tests/test_gap21_agent_checkpointer_postgres.py` now gets real Postgres checkpointing (it fell
  back to in-memory on Windows for a documented, OS-specific reason that shouldn't apply on Linux).
- Give me a short report: environment set up OK or not, current real test counts, and anything that
  differs from what `IMPLEMENTATION_PROGRESS.md` says to expect.

Then: Stage 0 and Stage 1 (Days 1-34) are done and were independently re-verified live on Day 34 —
treat them as a solid foundation, not something to redo, unless your own fresh regression run above
turns up something that contradicts that.

**[EDIT THIS LINE BEFORE SENDING: either "Start Stage 2 at Day 35 (resource/cost/size pre-flight,
extending `backend/app/pipeline/cost_controller.py`) and continue day-by-day through the plan
without stopping for permission between days, same as Days 11-34 were run — but pause and ask me
before crossing into Stage 3 or making any other stage-boundary jump." OR, if you want to review the
environment report first before authorizing Stage 2: "Just do the setup + verification report above
and stop there — wait for me before starting Stage 2."]**

Standing rules for all of this, no exceptions: zero hardcoding, zero hallucination (`file:line`
evidence for every claim, "I cannot verify this" over guessing); full regression suite before and
after every single change, a newly-broken passing test is always fixed in the change, never in the
test; a real new/updated test must prove each item works, not just "the suite is still green"; the
smallest change that satisfies each item, no drive-by refactors; update both `65days_plan/answers.md`
and `65days_plan/IMPLEMENTATION_PROGRESS.md` after every day's work, same style as the existing
entries, with real evidence; the Gap Audit Protocol (in `PLAN.md`) can be invoked by me at any
time — when it is, re-derive and re-run everything, don't just re-summarize.

---

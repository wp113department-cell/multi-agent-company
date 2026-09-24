# Task 2 — Enhance the PARTIAL items (production-grade, batch by batch)

Scope: the 61 PARTIAL items from `GRIDIRON_PARTIAL_NO_IMPLEMENTATION_PLAN.txt`, plus the 9 items
downgraded to PARTIAL while verifying Task 1's YES answers (#502, #331, #396, #442, #426, #450,
#451, #498, #484). **70 items total.** Task 3 (the 14 NO items) is separate and comes after.

Method, same as Task 1: for each item — read what's actually built today, decide what "real,
production-grade" looks like (not the minimum to flip a flag), implement it, test it against real
infrastructure (Postgres/Docker/git; live Claude API only when unavoidable), run the affected
tests plus a full-suite pass before committing, write the honest result to
`enhance_partial_tracking.md`. An item can close in one of four ways:
- **DONE** — built and verified.
- **DONE (config flip)** — the mechanism already existed and was fully tested; the change is
  turning a proven, tested capability on by default. Real cost/latency impact is called out
  explicitly since these add live LLM calls.
- **INTENTIONAL, NO CHANGE** — the audit's own plan says this is a deliberate design choice (e.g.
  "never auto-resolve merge conflicts without a human"), re-verified as still correct — closed as
  a decision, not a gap.
- **BLOCKED / NEEDS A DECISION** — genuinely needs the user to make a call before any code (a
  concrete governance rule set, a multi-tenancy design question). Flagged, not guessed at.

Several items are the same underlying gap counted more than once across sections (the audit's own
plan already tags these `[DEPENDENT]`) — those are done together under whichever batch owns the
real work, and the tracking file cross-references them so nothing is silently dropped.

## Batches

| Batch | Theme | Items | Depth |
|---|---|---:|---|
| T2-B1 | Quick wins — flip proven mechanisms on by default | #43,47,65,106,117,123,146,495,503 | Low risk |
| T2-B2 | Worker-agent pause/resume/checkpoint (one real engineering effort, several checkpoints) | #212,213,234,235,236,238,246 | High — new interrupt/resume graph points |
| T2-B3 | Guidance, confidence & performance surfaced into real behavior | #126,129,130,147,437,439,505 | Medium |
| T2-B4 | Memory management: compression, quality, evolution | #88,90,98,100 | Medium |
| T2-B5 | Quality gates + dependency intelligence made real/mandatory | #453,455,456,462,463,396 | Medium-high |
| T2-B6 | Scalability groundwork: distributed registries, isolation, analytics | #162,169,377,381,383,361 | High |
| T2-B7 | Scheduler & metrics intelligence | #407,414,427,428,429 | Medium |
| T2-B8 | Large-file / large-repo tooling | #38,255,257,259 | Medium-high |
| T2-B9 | Terminal/PTY, platform CI, remaining intentional closures | #3,5,6,12,149,150,196,198,291,300,329 | High (PTY is the big one) |
| T2-B10 | The 9 items downgraded during Task 1 | #502,331,442,426,450,451,498,484 (#396 moved to B5) | Medium |

Order follows the audit's own priority note (quick wins first, dependent chains grouped, the
riskiest new-engineering items — PTY terminal, distributed dispatch — later) rather than numeric
order.

## Known BLOCKED / decision-needed items (flagged now, not silently skipped)
- **#329** (central governance beyond the security policy engine) — the audit's own plan says this
  needs the user to define concrete, checkable coding standards first; a fabricated rule set would
  be worse than the honest gap. Will ask when T2-B9 comes up, not before.
- **#377** (per-tenant singleton isolation) — genuinely blocked on real multi-tenancy (workspaces/
  orgs) not existing; that's a SKIP-list item (#376), out of scope for this platform today. Closed
  as blocked, not built around.

## Next up — user-approved after T2-B10 (2026-09-24)
All 10 batches closed (56 DONE, 2 BLOCKED, 6 INTENTIONAL/NO-CHANGE, 4 honestly PENDING — see
`enhance_partial_tracking.md`'s own Progress table). Walked the user through the remaining 12
non-DONE items one at a time; user agreed with the recommendation to leave 11 of them alone
(2 blocked on missing prerequisites the user doesn't currently need — #169 multi-server, #377
multi-tenancy; #329 needs rules the user doesn't have yet; #427/#150/#196/#198 have no real
functional gain; #291/#300 are deliberate safety boundaries, not gaps) and to build the one with
real, near-term value:

- **#12 (Monitor streaming output, live mid-command)** — PLANNED, next real build. Converts
  `policy/sandbox.py::run_sandboxed()` from buffer-then-return to a real streaming `docker run` +
  incremental-read model, pushed out as `terminal_output` SSE events as they happen instead of
  after the whole command finishes. The audit's own plan already says to build this behind a
  feature flag, keeping the old buffered path as fallback until proven stable — that shape still
  applies.
  - **Real prerequisite, not yet done**: this session's own Docker Desktop File Sharing
    reconfiguration (noted repeatedly in T2-B7/B8/B9/B10's own full-suite runs — ~89 sandbox-
    execution tests fail with "mounts denied" until the user re-adds the project path in Docker
    Desktop → Settings → Resources → File Sharing). Building/testing a change to the sandbox's own
    execution model with the EXISTING sandbox tests already failing for an unrelated environmental
    reason would make it impossible to tell a real regression from known noise — do the Docker
    fix first, confirm `tests/test_sandbox.py` passes clean, THEN start #12.
  - **#3/#5 (real PTY terminal, multiple terminals)** — user agreed these are worth building
    eventually (competitive value for a coding-agent product) but are honestly a separate,
    multi-week, full-stack project (new WebSocket/SSE endpoint + a real `xterm.js` frontend
    component) — not scheduled as part of this initiative's remaining work, tracked here as a
    real, named future project rather than silently dropped.

## Ledger
Live-API spend continues in `verify_api_ledger.md`. Same rule: Groq for anything that doesn't need
Claude specifically now that it's config-real; Claude (Haiku by default) only when the item
genuinely needs a live model behavior to prove, kept small.

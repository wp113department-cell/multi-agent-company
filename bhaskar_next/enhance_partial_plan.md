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

## Ledger
Live-API spend continues in `verify_api_ledger.md`. Same rule: Groq for anything that doesn't need
Claude specifically now that it's config-real; Claude (Haiku by default) only when the item
genuinely needs a live model behavior to prove, kept small.

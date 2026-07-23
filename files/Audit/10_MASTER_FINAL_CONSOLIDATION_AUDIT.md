# MASTER FINAL CONSOLIDATION AUDIT

# DO NOT WRITE OR MODIFY CODE. READ-ONLY AUDIT.
# Run this LAST, after audits 01-09 AND 11 (Zero Policy) have each produced
# a Markdown report + JSON sidecar per 00b_AUDIT_STANDARDS.md. This audit's
# job is synthesis and final release decision — it does not re-derive
# findings from scratch, and it does not re-open questions the prior 10
# audits already answered with evidence.

You are the Principal AI Architect chairing a release-readiness review
board made up of every specialist role from the prior 10 audits (01-09 +
11). Your sources of truth are:
1. `PROJECT.md` (project history/ground truth)
2. The 10 prior audit reports AND their JSON sidecars (ask the user for
   their file paths/contents if not already in context — do not proceed
   without them; if any report is missing, say so explicitly rather than
   fabricating its conclusions)

If JSON sidecars are available, parse and merge them programmatically
(read the files, aggregate `findings[]` and `counts`) rather than
re-reading prose summaries — this is materially more reliable and is the
entire reason 00b_AUDIT_STANDARDS.md mandates the JSON format.

## PHASE 0 — Ingest

For each of the 10 prior reports, extract:
- Its stated layer score (0-100)
- Its Critical and High severity findings (list every one, with file:line)
- Its explicit READY/NOT READY verdict where one was given

Do not soften, merge, or reinterpret findings — report them as stated in
the source audit. If two audits disagree about the same file/behavior
(e.g. audit 04 says a feature is wired into both entry points, audit 02
says it's only wired into one), flag the CONTRADICTION explicitly as its
own finding — this is valuable signal, not noise, and likely means one of
the two audits missed something. Do not silently pick one.

## PHASE 1 — Cross-Layer Consolidation

Build these consolidated views across all 10 reports:

- **Master Critical Issues List** — every Critical-severity finding from
  every report, deduplicated (the same root cause may surface in two
  reports, e.g. a missing entry-point wiring showing up in both the
  Architecture and Orchestration audits — merge those into one entry citing
  both source reports).
- **Master High Issues List** — same, for High severity.
- **Cross-cutting patterns** — look specifically for the RECURRING bug
  classes this project's own history shows it is prone to (per PROJECT.md's
  own gap-closure sessions): (a) a feature wired into only one of the two
  task-lifecycle entry points, (b) a module built with zero real callers,
  (c) timezone-aware datetime written to a naive DB column, (d) an asyncio
  shared-event-loop hazard from calling a sync `asyncio.run()`-wrapping
  facade from already-async code, (e) `task_id`/`trace_id` confusion in
  events. For each pattern, state explicitly whether THIS round of audits
  found any NEW instance of it, or whether the historical fixes are still
  holding.
- **Scorecard table**: one row per layer (Architecture, Agents, Memory,
  Orchestration, Security, Infrastructure, AI Evaluation, Production
  Readiness, Performance & Scalability, Zero Policy), columns = score
  (0-100), #Critical, #High, #Medium, #Low, verdict.

## PHASE 2 — Weighted Overall Assessment

Compute an overall Production Readiness percentage using this weighting
(justify any deviation from it explicitly rather than silently changing
it):

| Layer | Weight | Rationale |
|---|---|---|
| Security | 18% | breach/data-exposure risk |
| Orchestration | 16% | correctness failures here cause stuck/lost work |
| Zero Policy | 14% | hallucination/leakage/dead-loop risk cuts across every other layer |
| Agents | 12% | direct quality of what the system produces |
| Production Readiness | 12% | operational safety net |
| Infrastructure | 10% | data integrity, migrations, config |
| Memory | 8% | quality degrades gracefully more than it breaks |
| AI Evaluation | 5% | mostly measurement infrastructure, not a live gate yet (see audit 07) |
| Performance & Scalability | 5% | degradation, not failure, in most cases |

Rules for applying this, not just displaying it:
- Any single unresolved **Critical** finding in Security, Orchestration, or
  Zero Policy caps the overall score at or below 60/100 regardless of how
  well other layers scored — state this explicitly and apply it, don't let
  a high weighted average paper over one real Critical.
- Show the actual arithmetic: `overall = Σ(layer_score × weight)`, then
  apply the cap rule on top, then state the final number.

## PHASE 3 — Release Decision

Produce a clear, unambiguous verdict:

**READY FOR PRODUCTION** — only if there are zero unresolved Critical
findings across all 10 reports, and High findings are either resolved or
explicitly accepted as known limitations with a documented mitigation.

**NOT READY FOR PRODUCTION** — if any Critical finding remains open. List
the EXACT set of fixes required before re-review, each phrased as a
specific, scoped, verifiable task (file, what changes, how to verify) —
not vague directives like "improve security."

## PHASE 4 — Final Consolidated Report

Produce ONE document with:

1. Executive Summary (5-8 sentences, plain language, suitable for a
   non-technical stakeholder)
2. Layer Scorecard (table)
3. Master Critical Issues List (deduplicated, file:line, source report)
4. Master High Issues List (deduplicated, file:line, source report)
5. Cross-Cutting Pattern Analysis (the 5 recurring bug classes above,
   found/not-found this round)
6. Contradictions Between Audit Reports (if any) — flagged for manual
   re-check, not resolved by guessing
7. Overall Weighted Production Readiness score (0-100) with the weighting
   rationale shown
8. **RELEASE DECISION**: READY / NOT READY
9. If NOT READY: the exact, ordered list of fixes required, each
   independently verifiable, with an estimate of whether it's a small
   (single-file), medium (few-files), or large (cross-cutting) change
10. If READY: recommended post-launch monitoring priorities drawn from the
    Production Readiness and Performance audits (what to watch first)

This is the document that gets read by a human before they decide whether
to point real users at this system. Be honest, specific, and conservative
— do not round up a "mostly fine" system to READY. Do not round down a
genuinely solid system to NOT READY over cosmetic issues either. Ground
every claim in the 10 source reports and PROJECT.md; do not introduce new
unverified findings at this stage — if you notice something the prior 10
audits missed, say so explicitly as a gap in audit coverage, and recommend
which of the 10 audits (01-09, 11) should be re-run to check it, rather than asserting
it as a confirmed finding yourself.

Do not write code. Do not modify files.

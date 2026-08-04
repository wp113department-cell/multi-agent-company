# ADR 006 — Repository-scoped engineering memory: source of truth, invariants, and scope boundaries

**Status:** Accepted
**Date:** 2026-08-05

## Context

`memory_embeddings`/`versioned_lessons` (the fleet's persistent engineering memory — task outcomes,
failures, architecture notes, procedures, learning signals) gained a nullable `repo_id` column in
gap-closure Day 2 (2026-07-30, migration 024), and `app/memory/store.py`'s query/embed functions
gained correct `repo_id`-filtering SQL in Day 3 the same week. Neither was wired to any real caller
— every one of the ~17 real call sites into that module kept passing no `repo_id`, so in production
every repo's memory was visible to every other repo's queries, unconditionally (Stage 4 Cluster O,
found 2026-08-04 while verifying `answers.md` Q95).

A full design proposal (`65days_plan/CLUSTER_O_DESIGN.md`) answered 8 scoping questions, was
approved, and was implemented and production-verified across 4 phases the same day (2026-08-05):
Phase 1a (the 2 fleet-wide chokepoints — `run_agent_graph()`, `record_agent_run_outcome()`), Phase
1b (manager.py epics, ChatSession, architect.py, the legacy planning pipeline), Phase 1c
(`/api/memory/search`), Phase 1d (the `memory_search` agent tool). 23 new tests, all against real
Postgres with 2 real repositories, each phase confirmed via `git stash` to genuinely fail without
its own fix. Full detail, sequence/data-flow diagrams, and per-phase test evidence live in the
design doc — this ADR is the durable, canonical summary of what was decided and why.

## Decision

**`DevTask.repo_id` is the single source of truth for repository scoping**, fleet-wide. Never the
mutable `app.api.repo._active_repo_path` global (a real, previously-fixed race — gap-closure Day 4).
Never a reverse lookup from a filesystem path (`Repo.local_path` has no uniqueness constraint, so
path→id is unsafe as a general mechanism).

`repo_id` is resolved **once, at the boundary of a unit of work** (an agent run, a chat session, an
epic, an HTTP request), and carried read-only for that unit's lifetime — not re-resolved mid-run,
not injected via a global or context-var.

### Repository Isolation Invariants (canonical, from `CLUSTER_O_DESIGN.md` §11)

1. **Single source of truth**: `repo_id` always derives from `DevTask.repo_id`, never a mutable
   global or a path-string lookup.
2. **Explicit two-category classification**: every memory call site is either repo-scoped or
   intentionally global — never an unexamined default.
3. **`NULL` means global-forever**, not "not yet migrated" — a legitimate permanent state, not a
   TODO.
4. **Filter symmetry**: a query scoped to repo X returns rows where `repo_id IS NULL OR repo_id = X`
   — never another repo's rows. One shared SQL predicate, no per-call-site variants.
5. **No bypass**: nothing outside `app/memory/store.py` queries `memory_embeddings`/
   `versioned_lessons` directly.
6. **Resolved once, immutable for the run** — safe because `DevTask.repo_id` is itself immutable
   post-creation (verified: no code path ever updates it).
7. **Caches never invalidate incorrectly** — a `task_id → repo_id` cache needs no invalidation at
   all (the value never changes); a `repo_id → Repo` row cache invalidates only on the same
   `Repo`-lifecycle events that already trigger `invalidate_context_cache()`.
8. **Unresolvable always defaults to global**, never an exception and never a silent empty result.

### Repository-scoped vs. intentionally global memory

Not every memory category should be scoped, and treating that as a single on/off switch would be
wrong:

| Category | Scoping | Why |
|---|---|---|
| Task outcomes, failures, architecture notes, procedures | **Repo-scoped** | Tied to one repo's actual code and history |
| Fleet-wide agent/tool/prompt learning signals (`record_learning`, `fleet_dashboard.py`'s enhancement learning) | **Intentionally global** | Knowledge about *agent behavior*, not one repo's code — scoping would silently break cross-repo learning transfer, the entire point of this category |
| `memory_search` tool's omitted-`repo_id` default | **Intentionally global** | See Knowledge Curator reasoning below |

### Documented exceptions

- **`resolve_repo_id_from_path()`** (`app/db/repository.py`): the one sanctioned reverse path→id
  lookup, used only where no `DevTask` exists to resolve from at all (`ChatSession` construction).
  Mitigated, not eliminated: filters `status == 'ready'`, takes the most-recently-created match —
  correct for the overwhelmingly common one-repo-per-path case, degrades to unscoped rather than a
  wrong answer if ever ambiguous.
- **Epics have no `repo_id` at all today** (`CreateEpicRequest`/`Epic` — confirmed by reading the
  real `/api/epics` endpoint, not assumed). This is not a Cluster O gap — the epic-manager wiring
  correctly reads whatever `repo_id` is available and is forward-compatible — it's a missing domain
  capability, promoted to its own cluster (**Cluster R**, `65days_plan/STAGE4_BACKLOG.md`).
- **`versioned_memory.py` (`VersionedLesson`)**: has the `repo_id` column since the same migration,
  but its own functions don't accept the parameter at all — deliberately deferred to its own Phase 2
  design pass (does a *published* lesson want repo scoping, or only pre-publish?), not bundled into
  this rollout.

### Why Knowledge Curator's `memory_search` stays fleet-wide by default

Phase 1d's design doc draft speculated the tool's omitted-`repo_id` default should be "current run's
repo" (the conservative-sounding choice). Before implementing, `memory_search`'s real callers were
checked directly rather than assumed: its only caller anywhere in the codebase is
`knowledge_curator`, whose own module docstring states its job as curating the fleet's shared memory
"so future `memory_hook_node` injections stay accurate" — across every repo, by design. Defaulting
to one repo would have actively broken that agent's real job, which depends on seeing memory from
the whole fleet to dedupe and quality-check the shared store. The speculative default was corrected
before any code was written. `repo_id` remains available as an explicit, optional narrowing input
for any future caller that genuinely wants one repo's memory only.

## Rollout and rollback rationale

**Rollout**: purely additive at every step — every touched function gained a `None`-defaulted
parameter; no existing signature lost a parameter or changed a default. Sequenced by leverage and
risk: the 2 fleet-wide chokepoints first (Phase 1a — covers the large majority of the fleet's real
traffic through 2 functions), then the remaining direct call sites (1b), then the human-facing API
(1c), then the one LLM-facing tool input (1d). Each phase gated on the previous phase's real-DB
isolation tests passing before proceeding — no phase shipped on an assumption the previous one
worked.

**Rollback**: trivial by construction, and explicitly *why* the additive-only approach was chosen
over anything requiring a flag or a schema migration. Since `repo_id=None` is the exact behavior
every caller had before this rollout, reverting any subset of the 4 phases' commits leaves the
system in a valid, safe, previously-shipped state — never a broken intermediate. No feature flag was
needed anywhere in this rollout.

## Consequences

- Future memory-related work in this area belongs under **Cluster R** (epic repository assignment)
  or **`versioned_memory.py`'s own Phase 2** (lesson scoping) — not as an extension of Cluster O,
  which is closed except for defect fixes.
- Any new `embed_*`/`query_*` call site added to `app/memory/store.py` in the future must be
  classified against INV-2 (repo-scoped or intentionally global) explicitly, in a code comment at
  the call site — not left as an unexamined default.
- This ADR, not `CLUSTER_O_DESIGN.md`, is the canonical reference for future contributors asking
  "how does repo-scoped memory work and why" — the design doc remains the detailed record (diagrams,
  full Q&A, per-phase test evidence) for anyone who needs the full history.

# MASTER ARCHITECTURE AUDIT — Gridiron AI Developer Department

# DO NOT WRITE OR MODIFY CODE. READ-ONLY AUDIT.
# Read PROJECT.md in full before starting. It is ground truth for what
# "should" exist — your job is to verify what actually exists matches it,
# and flag every place it doesn't.

You are a Principal AI Architect auditing this repository's structure and
design. This project is NOT a hypothetical multi-agent framework — it is a
specific, already-built system: a Python/FastAPI backend with LangGraph-based
agents, a Next.js frontend, and a "Fleet OS" layer (capability registry,
agent registry, fleet manager, event bus, metrics, checkpointing) that has
been built incrementally across "Fleet Enhancement Days 0–19" (see PROJECT.md
history). Ground every finding in actual files and line numbers. If you
can't find evidence, write NOT FOUND — never guess or assume.

## PHASE 0 — Orientation (do this before judging anything)

Read, in order:
1. `PROJECT.md` — full history, especially the "Gap-Closure" sessions, which
   already document several real bugs that were found and fixed. Do not
   re-report those as new findings unless you can show they regressed.
2. `backend/app/agents/base_graph.py` — the shared LangGraph scaffold used by
   all ~72 agents via `run_agent_graph()`. Understand: `AgentRunState` fields,
   `planner_node`, `memory_hook_node`, `reflection_node`, the retry/stall
   router, `run_span` metrics wrapper, checkpoint/rollback hooks, budget
   enforcement, image/multimodal support (Day 16).
3. `backend/app/pipeline/graph.py` — the SEPARATE epic-level LangGraph
   (pm→architect→decomposer→human_review) with a real `AsyncPostgresSaver`
   checkpointer and `interrupt()`. Confirm you understand this is a DIFFERENT
   graph from base_graph.py, with different guarantees (this one survives
   restarts; base_graph.py agents do not have a checkpointer).
4. `backend/app/agents/manager.py` — the plain-async orchestrator that
   dispatches dev→qa→review per subtask. Confirm this is NOT a LangGraph
   node itself.
5. `backend/app/fleet/` — capability_registry.py, agent_registry.py,
   fleet_manager.py, audit_log.py, metrics.py, fleet_events.py,
   tool_manifest.py, fleet_checkpoint.py, model_router.py, budget_manager.py,
   benchmark_manager.py, tool_discovery.py, approval_gate.py, failure_ladder.py.
6. `backend/app/api/` — every router file, to build a real endpoint map.
7. `apps/web/app/` — every page, to build a real frontend route map.

## PHASE 1 — Build Architecture Documentation (produce these as output)

- **System diagram (textual)**: request → FastAPI route → background task →
  agent/pipeline → DB/event bus → frontend poll or SSE stream. Trace at least
  3 real flows end to end: (a) simple task via `/approve` → `launch_coder`,
  (b) full pipeline via `/pipeline/approve` → `launch_manager`, (c) chat via
  `/api/chat/sessions/{id}/messages` SSE.
- **Two-graph map**: every node in `pipeline/graph.py` vs every node
  reachable through `base_graph.py`. Explicitly state which graph each of
  the 72 agents in `capability_registry` actually runs under.
- **Dependency graph**: which `app/` modules import which. Flag any
  circular imports (verify with actual import statements, not assumption).
- **Event flow**: every call site of `fleet_events.publish(...)`. Cross-check
  against the 8 canonical `FleetEventType` values enforced by
  `tests/test_event_compliance.py` — confirm no 9th type has been invented
  since the last audit.
- **DB schema flow**: list every Alembic migration in
  `backend/migrations/versions/` in order, and what table/column each adds.
  Cross-check against PROJECT.md's own migration history for gaps or
  undocumented migrations.
- **Data flow for the two memory systems**: `LessonStore` (in-process,
  base_graph.py) vs `memory_embeddings`/`versioned_lessons` (Postgres,
  pgvector). Confirm which agents/nodes read from which, and that this
  project's own documented distinction (fast in-process cache vs durable
  version history) is actually implemented that way in code, not just in
  PROJECT.md prose.

## PHASE 2 — Structural Findings

For EVERY issue found, report: exact file, exact function/class, exact line
number(s), what's wrong, severity (critical/high/medium/low), production
impact, and a specific (not generic) recommended fix. If you assert
something is fine, cite the file/line that proves it — don't just say
"looks fine."

Check specifically for:
- **Orphaned modules**: any `app/fleet/*.py` or `app/agents/*.py` file with
  zero real (non-test) callers. PROJECT.md's gap-closure sessions found and
  fixed several of these (versioned_memory.publish, fleet_checkpoint,
  tool_discovery, prompt_registry.deploy) — verify those wirings are still
  present and grep for any NEW orphans introduced since.
- **The "two graphs" trap**: any place that assumes `base_graph.py` agents
  have checkpoint/resume semantics they don't actually have (no
  checkpointer is configured there — only `pipeline/graph.py` has one).
- **`task_id` vs `trace_id` confusion**: PROJECT.md documents a real bug
  where fleet events used the per-run trace id instead of the real task id.
  Grep every `fleet_events.publish(...)`/`agent_registry.start_task(...)`
  call site and confirm the correct id is passed at each one.
- **Config sprawl**: is every behavior-affecting constant actually in
  `app/config.py` (Pydantic Settings), or are there stray hardcoded
  constants that should be config? Cross-reference against PROJECT.md's own
  "hardcoding audit" fixes (CORS origins, event bus retries, Groq retries)
  to confirm no regression and find any new instances.
- **Two-mode pipeline parity**: "simple" mode (`launch_planner`→
  `launch_coder`) and "full" mode (`launch_planning_pipeline`→
  `launch_manager`) are two separate real entry points. PROJECT.md documents
  a gap where a fix was applied to one but not the other (bootstrap, repo_id
  resolution). Check EVERY feature added in Days 13-19 (approvals, image
  input, git push, credential injection) against BOTH entry points and flag
  any that only wired one.
- **Frontend/backend contract drift**: for each API router, confirm the
  `apps/web/lib/api.ts` types match the actual Pydantic response models
  (snake_case vs camelCase handling, field presence).

## PHASE 3 — Technology Fit Review

List every major library actually in `requirements.txt` / `package.json`
(don't assume — read the files) and briefly assess whether its use matches
its documented purpose in PROJECT.md (LangGraph, FastAPI, SQLAlchemy async,
Alembic, pgvector, voyageai, Anthropic SDK, Groq — is Groq usage still
properly test-isolated per the `USE_GROQ=false` conftest fix?). Do NOT
recommend swapping to unrelated frameworks (no CrewAI, no LangChain-proper
migration suggestions) — this project made deliberate build choices
documented in PROJECT.md; respect them unless there's a concrete defect.

## PHASE 4 — Final Report

Produce ONE report with:
1. Executive summary (3-5 sentences)
2. Architecture score (0-100) with justification
3. Two-graph correctness verdict
4. Event/trace-id correctness verdict
5. Orphan-module list (if any)
6. Critical / High / Medium / Low issues (each with file:line evidence)
7. Config-sprawl findings
8. Frontend/backend contract drift findings
9. Recommended fixes, each phrased as a concrete diff-sized task (not "improve architecture")
10. Overall: READY / NOT READY for the next audit phase, with reasoning

Do not write code. Do not modify files. Evidence or NOT FOUND only.

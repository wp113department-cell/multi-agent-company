# Day 11 Implementation Plan — prompt_registry, regression_detector, versioned_memory
Researched and grounded 2026-07-21 (REPO-FIRST rule followed before any design below).

Source: `docs/FLEET_ENHANCEMENT_PLAN.md` lines 869-908 (Day 11 spec).

## Repo research findings (read before designing — do not re-derive)

**Task 1 — versioned prompt registry.** Best match: `repos/roo-code/src/services/checkpoints/ShadowCheckpointService.ts`.
A "version" = an immutable git commit in a shadow repo; `saveCheckpoint()` stages+commits (never
edits in place); `restoreCheckpoint(hash)` is `git reset --hard <hash>` — a **pointer swap to a
target snapshot**, not a replay of edits. Second reference:
`repos/langgraph/libs/checkpoint/langgraph/checkpoint/base/__init__.py`'s `CheckpointMetadata`
(`source`, `step`, `parents: dict[namespace, checkpoint_id]`) — real parent-pointer lineage, closer
to "version N supersedes N-1" than a flat log. **Neither repo has an approval-gate/review state
machine** — proposal→review→approved→deployed is our own design; borrowed mechanics are:
immutable version + parent pointer + restore-by-pointer-swap (not replay).

**Task 2 — regression detection against a baseline.** Checked `swe-agent/agent/reviewer.py`
(variance-reduction over N samples of the *same* run, not baseline comparison),
`swe-agent/agent/history_processors.py` (pure prompt-window trimming, no metrics), and autogen's
MagenticOne stall detection (`_n_stalls`, in-run progress-ledger, no cross-run storage).
**No repo implements baseline-store + threshold-diff + block.** This is a novel design — and it
already exists in this codebase: Day 10's `benchmark_manager.compare_to_baseline()` computes
exactly this (current vs. stored Postgres baseline, `is_regression` flag,
`BENCHMARK_REGRESSION_THRESHOLD` config). **Day 11 does not reimplement comparison logic** —
`regression_detector.py` is a thin deploy-time gate wrapping `benchmark_manager`, adding the
explicit "block" semantics tied to `prompt_registry.deploy()`.

**Task 3 — versioned memory / lesson lifecycle with merge-on-conflict.** Checked autogen's
`MemoryController.add_memo()` (pure append, no similarity check before write), LangGraph's
`store.BaseStore.put()` (namespaced key-value upsert, silently overwrites, no version chain), and
`open-hands` (this checkout has no runtime memory module, only static always-on `.md` context
files). **No repo has merge-on-conflict.** Reusable pieces: LangGraph's namespace/item shape for
storage keys (informing our table's `topic` column), autogen's embedding-based topic retrieval for
similarity detection (we already have the exact same pattern in this codebase — see below).

## Codebase grounding (verified, not assumed)

- **Role prompts are unversioned flat files**, loaded fresh from disk every call:
  `app.agents.base.load_role(name)` reads `backend/roles/{name}.md` + prepends
  `_GLOBAL_STANDARDS.md`. No DB involvement at all today. `prompt_registry.deploy()` will write
  approved content directly to this same file path — `load_role()` needs zero changes.
- **The plan doc's claim that lessons already live in "the existing memory DB table" is wrong** —
  verified by grep, there is no `lessons` table anywhere in `app/db/models.py`. Lessons today are
  `LessonStore` in `app/agents/base_graph.py` — a **plain in-process list, capped at 1000, keyword-
  overlap retrieval, zero persistence, zero versioning**. `_extract_and_store_lesson()` calls
  `get_lesson_store().add(lesson)` after every completed run — this is the "lesson_node calls
  memory_write" the plan doc refers to. `versioned_memory.py` needs a **new** DB table, not new
  columns on an existing one.
- **Embedding-similarity infra to reuse, not reinvent**: `app/memory/store.py` already has
  `_embed(text) -> list[float]` (Voyage AI, zero-vector fallback when no key), and the real
  pgvector query pattern (`embedding <=> CAST(:vec AS vector)` cosine distance, raw SQL via
  `AsyncSession.execute`). `versioned_memory.py`'s conflict-detection reuses this exact pattern
  against a new `versioned_lessons` table's own `embedding` column — not the `memory_embeddings`
  table, which is task-outcome memory (a different concept, Day 6).
- **`app/policy/engine.py`'s `check_path()`** does not deny `roles/` — safe to write there, but
  `prompt_registry.deploy()` will additionally confine writes to inside `backend/roles/` (prefix
  check on the resolved path) as defense-in-depth against a malformed `role_name`, consistent with
  the permanent safety rule that path-writing agents must be sandboxed.
- **Day 10's benchmark_manager pattern to mirror**: Postgres-backed history with an
  `is_baseline`/`is_active`-style boolean flag flipped on promotion rather than deleting old rows
  (append-only audit trail) — `prompt_versions` and `versioned_lessons` both reuse this shape.

## Module 1: `app/fleet/prompt_registry.py`

DB table `prompt_versions` (migration 013):
- `id` (PK), `role_name` (str, indexed), `version_number` (int, sequential per role_name)
- `content` (Text — full markdown snapshot), `content_hash` (str, sha256 — skip no-op proposals)
- `status` (str, indexed): `draft | in_review | approved | deployed | superseded | rejected`
- `parent_version_id` (FK to self, nullable — lineage pointer, LangGraph-style)
- `proposed_by`, `approved_by` (str, nullable), `created_at`, `deployed_at` (timestamps)

`PromptRegistry` class (DB-backed, same isolated-engine-per-call pattern as Day 10):
- `propose(role_name, content, proposed_by) -> PromptVersion` — no-ops (returns existing) if
  `content_hash` matches the current deployed version's hash
- `submit_for_review(version_id)`, `approve(version_id, approved_by)` — status transitions,
  raise `InvalidTransition` on an illegal jump (e.g. approving a draft directly)
- `deploy(version_id)` — requires `status == "approved"`; calls
  `regression_detector.gate_deploy(role_name)` first (raises `DeploymentBlocked` if regression
  detected — Day 11's cross-module wiring point); on success, writes `content` to
  `backend/roles/{role_name}.md`, flips the previously-deployed row (if any) to `superseded`,
  sets this row `deployed`
- `rollback(role_name)` — finds the most recent `superseded` version for that role, re-deploys its
  content directly (skips the approval gate — it was already approved once), current `deployed`
  row flips to `superseded`
- `get_history(role_name)`, `get_deployed(role_name)`

## Module 2: `app/fleet/regression_detector.py`

No new comparison logic — wraps Day 10's `benchmark_manager`:
- `RegressionGate(agent_name, blocked, reason, report: RegressionReport)`
- `DeploymentBlocked(Exception)` — `agent_name`, `reason`, `report`
- `check_agent(agent_name) -> RegressionGate` — calls
  `get_benchmark_manager().compare_to_baseline(agent_name)`, builds a human-readable `reason` from
  `report.per_objective_delta` (which objectives got worse and by how much)
- `gate_deploy(agent_name)` — raises `DeploymentBlocked` if `check_agent(agent_name).blocked`;
  this is what `prompt_registry.deploy()` calls, and is the concrete answer to the plan's
  "tests passing alone is NOT sufficient" requirement — it runs independently of pytest
- `check_fleet() -> list[RegressionGate]` — iterates every agent in `capability_registry`

## Module 3: `app/fleet/versioned_memory.py`

DB table `versioned_lessons` (migration 014, new — see grounding note above):
- `id` (PK), `lesson_id` (str, uuid — stable across versions of "the same lesson"),
  `topic` (str, indexed — short label used for equality/lookup, distinct from the embedding),
  `content` (Text), `embedding` (Vector(1536), nullable — same shape as `MemoryEmbedding`)
- `version` (int), `state` (str, indexed): `draft | published | superseded | merged_into | archived`
- `supersedes_id` (FK to self, nullable), `created_at`

`VersionedMemoryStore` class:
- `publish(topic, content, agent_name) -> VersionedLesson` — embeds `content` via
  `app.memory.store._embed()` (reused, not reimplemented), searches existing `published` rows for
  the same topic via the pgvector `<=>` pattern; if max similarity is below
  `MEMORY_MERGE_SIMILARITY_THRESHOLD` (config), just publishes as a fresh V1. If above threshold
  (a real conflict): create the new version (V2, `draft`), call Haiku once to merge V1+V2 content
  into `V_merged`, insert `V_merged` as `published`, flip V1 to `superseded`, flip V2 to
  `merged_into` (pointing `supersedes_id` at V1's row for lineage)
- `rollback(lesson_id) -> VersionedLesson` — restores the previous `published` version for that
  `lesson_id` lineage (mirrors `prompt_registry.rollback()`'s superseded-row restore)
- `archive_expired()` — archives `superseded`/`merged_into` rows older than
  `LESSON_RETENTION_DAYS` (config, mirrors the existing `log_retention_days` pattern) — called from
  the same background-loop slot pattern already used for retention/reindex in `main.py`'s lifespan

New config (zero hardcoding): `MEMORY_MERGE_SIMILARITY_THRESHOLD` (float, default 0.85),
`LESSON_RETENTION_DAYS` (int, default 180, 0 disables).

## Build order

1. `regression_detector.py` first — no DB migration needed, pure wrapper over existing
   `benchmark_manager`, fastest to verify, and `prompt_registry.deploy()` depends on it.
2. `prompt_registry.py` + migration 013 — depends on (1).
3. `versioned_memory.py` + migration 014 — independent of (1)/(2), can be built in parallel logic-
   wise but done last since it's the largest surface (embedding + merge-LLM-call + lifecycle).
4. Tests for each as built (not batched at the end) — mirrors the Day 10 pattern.
5. Full suite + mypy, update `PROJECT.md` / Control Center, write
   `docs/reports/FLEET_DAY11_TEST_REPORT.md`, commit.

## Success criteria (from the plan doc, verified achievable with this design)
- Version merge tested: publish same topic twice with similar content → confirm V1 superseded,
  V2 merged_into, V_merged published.
- Regression block tested: seed a degraded benchmark run → `gate_deploy()` raises
  `DeploymentBlocked` → `prompt_registry.deploy()` refuses to write the file.
- All new tests pass alongside the full existing suite (2517 baseline from Day 10).

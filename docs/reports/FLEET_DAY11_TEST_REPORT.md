# Fleet Day 11 Test Report — prompt_registry, regression_detector, versioned_memory
Date: 2026-07-21

## What was built

Per `docs/DAY11_PLAN.md`, written after a dedicated REPO-FIRST research pass (mandatory per
CLAUDE.md before any non-trivial new capability) — checked `repos/roo-code`, `repos/langgraph`,
`repos/swe-agent`, `repos/autogen`, `repos/open-hands`, `repos/aider` before designing any of the
three modules below.

### Repo research: honest findings, not forced analogies

- **Versioned prompt lifecycle**: `repos/roo-code/src/services/checkpoints/ShadowCheckpointService.ts`
  is the closest match — a "version" is an immutable git commit in a shadow repo, restore is a
  hard-reset pointer-swap to a target commit, never a replay. `repos/langgraph`'s
  `CheckpointMetadata` (`source`, `step`, `parents: dict[namespace, checkpoint_id]`) gave the
  parent-pointer lineage idea. **Neither has an approval-gate/review state machine** — that part
  is this session's own design.
- **Regression detection against a baseline**: checked `swe-agent/agent/reviewer.py` (variance-
  reduction over N samples of the *same* run, not baseline comparison), `history_processors.py`
  (pure prompt-window trimming), and autogen's MagenticOne stall detection (in-run progress
  tracking, no cross-run storage). **No repo implements baseline-store + threshold-diff + block.**
  This mechanism already exists in this codebase — Day 10's `benchmark_manager.compare_to_baseline()`
  — so `regression_detector.py` wraps it rather than reimplementing comparison math.
- **Versioned memory / merge-on-conflict**: checked autogen's `MemoryController.add_memo()` (pure
  append), LangGraph's `store.BaseStore.put()` (namespaced key-value upsert, silently overwrites),
  and this `open-hands` checkout (no runtime memory module at all — only static always-on `.md`
  context files). **No repo has merge-on-conflict.** Reused pieces: LangGraph's namespace/item
  shape informed the table design; this codebase's own `app/memory/store.py` (Day 6) already had
  the exact embedding + pgvector-cosine-search pattern needed for similarity detection — reused
  directly (`_embed()`), not reimplemented.

### A wrong assumption in the original plan doc, caught and corrected before building

`docs/FLEET_ENHANCEMENT_PLAN.md`'s Day 11 section claims lessons already live in "the existing
memory DB table (add version, state, supersedes_id columns)". Grepping `app/db/models.py` found
no `lessons` table anywhere — `LessonStore` (`app/agents/base_graph.py`) is a plain in-process
list, capped at 1000, keyword-overlap retrieval, **zero persistence, zero versioning**.
`versioned_memory.py` therefore needed a genuinely new table (`versioned_lessons`, migration 014),
not new columns on an existing one. Verified before writing any migration, not assumed from the
plan text.

## regression_detector.py (built first — prompt_registry depends on it)

No new comparison logic. `RegressionGate(agent_name, blocked, reason, report)`,
`DeploymentBlocked(agent_name, reason, report)`, `check_agent()` (wraps
`benchmark_manager.compare_to_baseline()`, builds a human-readable reason from
`per_objective_delta`), `gate_deploy()` (raises before any write happens — the concrete answer to
"tests passing alone is NOT sufficient"), `check_fleet()` (iterates `capability_registry`).

7 tests in `tests/test_regression_detector.py`, verified against real `BenchmarkManager`/
`MetricsCollector` instances (seeded runs, real Postgres baseline round-trip).

## prompt_registry.py

New `prompt_versions` table (migration 013). Every prompt change is an immutable version row —
never an in-place edit — with `parent_version_id` giving LangGraph-style lineage. Lifecycle:
`draft → in_review → approved → deployed → superseded` (+ `rejected` as a terminal branch from
`in_review`), enforced by an explicit `_VALID_TRANSITIONS` table that raises `InvalidTransition`
on any illegal jump (verified: `draft → approved` and `draft → deployed` both correctly rejected).

`deploy()` calls `regression_detector.gate_deploy(role_name)` first — verified end-to-end with a
real seeded regression (a degraded benchmark run against a stored baseline) correctly raising
`DeploymentBlocked` and leaving the version untouched at `approved`, never writing the file.
On success, writes `content` straight to `backend/roles/{role_name}.md` — `app.agents.base.load_role()`
needed **zero changes**, since it already reads fresh from disk on every call. `rollback()` restores
the most recent `superseded` version by re-deploying its content directly (skips re-approval, since
it was already approved once — mirrors roo-code's hard-reset restore semantics).

Path safety: `_role_file_path()` confines all writes to `backend/roles/` and additionally runs
`app.policy.engine.check_path()` for defense-in-depth. Verified with an explicit
`../../etc/passwd` traversal test — correctly raises `ValueError` before any file touch.

10 tests in `tests/test_prompt_registry.py`, including a real Postgres + real-file round-trip
(propose → review → approve → deploy → verify file content → deploy v2 → verify supersede →
rollback → verify file content restored), all cleaned up in `try/finally` (both DB rows and the
`roles/*.md` test file). Verified 0 residual test files in `backend/roles/` after the run.

## versioned_memory.py

New `versioned_lessons` table (migration 014). `publish(topic, content)`:

1. Embeds `content` via `app.memory.store._embed()` (reused — Voyage AI, zero-vector fallback
   when `VOYAGE_API_KEY` is unset, exactly as Day 6's engineering memory already handles it).
2. Searches existing `published` rows by cosine similarity using the same `embedding <=> CAST(...)`
   raw-SQL pattern as `query_similar_tasks()` — reused, not reinvented.
3. Below `MEMORY_MERGE_SIMILARITY_THRESHOLD` (config, default 0.85) or when no key is configured
   (zero-vector case, matching the existing convention of skipping the DB call entirely): publishes
   a fresh V1.
4. At or above threshold — a real conflict: inserts V2 as `draft`, calls the planner-tier
   (Haiku) model once via the standard `anthropic.Anthropic` client to merge V1+V2 content, publishes
   `V_merged`, flips V1 to `superseded` and V2 to `merged_into`.

`rollback(lesson_id)` and `archive_expired()` (respecting `LESSON_RETENTION_DAYS`, 0 disables)
round out the lifecycle. This does not replace `LessonStore` — that stays the in-process fast-read
cache used for prompt injection during a live run; `versioned_memory.py` is the durable,
version-history layer underneath it.

**A real bug found and fixed during testing, not assumed correct**: `rollback()` originally
returned the `prior` record object fetched *before* the DB flip, so its `.state` field still read
`"superseded"` even though the row had actually been updated to `"published"` in the database.
Caught by an explicit assertion in `test_rollback_restores_previous_published_version_and_state`,
not discovered by inspection — fixed by overriding the returned record's `state` to reflect the
real post-rollback value.

Tests used deterministic call-order embedding mocks (`_embed` patched at its home module,
`app.memory.store._embed`, since `versioned_memory.py` does a fresh `from app.memory.store import
_embed` inside the function body on every call — patching a local-import target elsewhere would
silently not take effect, a lesson also documented in `test_prompt_registry.py`'s comments for the
same reason) plus a mocked `anthropic.Anthropic` for the merge call, since neither
`VOYAGE_API_KEY` nor `ANTHROPIC_API_KEY` is configured in this environment.

10 tests in `tests/test_versioned_memory.py`, including a full merge-lifecycle round-trip against
the real Postgres `versioned_lessons` table, verified state transitions
(`[(1,"superseded"),(2,"merged_into"),(3,"published")]`), a real zero-vector-never-merges case, and
an `archive_expired()` test with a real backdated row.

## New config (zero hardcoding)

`MEMORY_MERGE_SIMILARITY_THRESHOLD` (0.85), `LESSON_RETENTION_DAYS` (180) — both in `config.py` and
`.env.example` with descriptions.

## Files changed

- `backend/app/fleet/regression_detector.py` (new)
- `backend/app/fleet/prompt_registry.py` (new)
- `backend/app/fleet/versioned_memory.py` (new)
- `backend/app/db/models.py` — `PromptVersion`, `VersionedLesson` ORM models
- `backend/migrations/versions/013_prompt_versions.py`,
  `014_versioned_lessons.py` (new)
- `backend/app/config.py`, `backend/.env.example` — 2 new fields
- `backend/tests/test_regression_detector.py`, `test_prompt_registry.py`,
  `test_versioned_memory.py` (all new)
- `docs/DAY11_PLAN.md` (new)

## Test Results

```
pytest tests/ -q
→ 2544 passed, 0 failed, 55 skipped, 17 deselected, 4 warnings in 58.30s

mypy app/ --strict
→ 32 errors, all pre-existing (identical to the Day 10 baseline), 0 new
```

Verified 0 residual rows in `prompt_versions` and `versioned_lessons`, and 0 leftover files in
`backend/roles/`, after the full suite run.

## Verdict
✅ GREEN FLAG — DAY 11 COMPLETE. Ready for Day 12 (end-to-end pipeline smoke test + failure
recovery ladder + event compliance + hierarchy chain verification).

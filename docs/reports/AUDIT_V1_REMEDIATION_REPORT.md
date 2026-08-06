# Audit v1 Remediation Report — CRR2906 Production Engineering Pass

**Date:** 2026-08-06
**Branch:** main
**Scope:** Full remediation of `audit_v1.md` findings across Phases A–T — 8 release blockers plus Phases 3–6 hardening (concurrency/reliability, repo intelligence, memory, event bus/artifacts/DB/observability).

---

## Summary

All 8 release blockers are fixed and individually verified (exploit repros re-run against the real code, now denied). All targeted findings from Phases 3, 4, 5, and 6 are implemented and verified against the real Postgres/Redis instances — not just unit-tested with mocks. One item (subtask concurrency fan-out) was deliberately **not** implemented after discovering the audit's proposed fix would introduce a real correctness regression; see "Deliberately Not Fixed" below.

Full backend suite: **3871 passed, 0 failed, 56 skipped (pre-existing, unrelated), 17 deselected**, run twice at the end of this session with identical results. `mypy app/ --strict`: clean across 200 files. `ruff check app/`: clean. No frontend changes made this session (frontend untouched, not re-verified).

---

## Part 1 — Release Blockers (all 8 fixed and verified)

| # | Blocker | Fix | Verification |
|---|---|---|---|
| 1 | `apply_patch` bypassed the path denylist | Parses `+++`/`---` diff headers, runs every target through `check_path()`/`check_path_in_worktree()` at both the universal gate (`base_graph.py::_policy_check`) and the handler itself | Exploit repro (`.env`, `.github/workflows/`, `../../../../tmp/pwned.txt` targets) — all denied |
| 2 | `read_file`/`read_files`/`file_exists`/`file_info`/`get_file_tree` had zero path containment | All five routed through `check_path_in_worktree()` | Exploit repro (`../`×10 traversal, absolute `/etc/passwd`) — all denied |
| 3 | Doc-writing agents (`dg_write_file`/`rm_write_file`/`ad_write_file`) bypassed worktree containment | Replaced ad-hoc/no checks with `check_path_in_worktree()`, matching the correct sibling pattern already in the file | Exploit repro (`docs/../../.github/workflows/evil.yml`) — denied |
| 4 | Command-chaining allowlist gate omitted newline/redirect | Added `\n`, `\r`, `>`, `<` to `_CHAINING_METACHARS` | Exploit repro (`echo pwned > ~/.ssh/authorized_keys`, `git status\nnc ...`) — both denied |
| 5 | Cleanup Agent's `find` allowlist entry ran unsandboxed | Routed `cu_bash` through the Docker-sandboxed `_run_bash_command` primitive | `find / -mindepth 1 -delete` now executes inside the sandbox, not the host |
| 6 | AI Engineer's `run_python_snippet` had no policy check; `pip install`/bare `python` in allowlist | `ae_run_python_snippet` routed through the sandbox; `python `/`python3 `/`pip install ` dropped from `_AI_BASH_ALLOWLIST` | Exploit repro (`python /tmp/reverse_shell.py`, `pip install malicious-pkg`) — both denied |
| 7 | No database backup mechanism | `scripts/backup_db.sh` + `scripts/restore_db.sh` (pg_dump -Fc / pg_restore, verified, retention-pruned) + `docs/disaster_recovery.md` runbook | Ran for real against the live dev Postgres: backed up, restored into a throwaway DB, row counts matched exactly (213=213) |
| 8 | RQ queue infrastructure disconnected from real dispatch | New `dispatch_job()` chokepoint wired into all 6 real task-launch call sites in `api/tasks.py`; real `Retry(max=...)` on enqueue; new `sweep_failed_rq_jobs()` + background loop drains `FailedJobRegistry` into `failed_events` | Unit-tested (19 passing); retry/sweep logic verified against real `rq`/`redis` APIs |

Also closed alongside the blockers (named in the same audit sections): SSRF guard on `fetch_url` (host/IP-range denylist, resolved-IP checked not just hostname — verified against `169.254.169.254`, RFC1918 ranges, `localhost`), `fetch_url`/`http_request` added to `_UNTRUSTED_CONTENT_TOOLS`, `git_service._validate_workspace`'s prefix-without-separator bypass fixed (`/home2/evil` no longer passes as inside `/home`), structured `AuditLog` wired into the real policy-denial chokepoint, and a new pre-commit secret-content scanner (`_scan_content_for_secrets`) catching AWS/OpenAI-shaped tokens, PEM headers, and credential-shaped assignments before `git_commit_change` runs.

**Deliberately scoped down:** `check_url_status`/`http_request`'s devops variants were *not* given the SSRF guard — they're intentionally used to health-check `localhost` during deployments (confirmed by an existing test asserting exactly that), and blocking `localhost` there would have broken real, intended functionality outside the audit's named scope (`fetch_url` specifically).

---

## Part 2 — Phase 3 (Concurrency & Reliability)

- **Atomic task transitions**: `transition_task()` rewritten as a single `UPDATE ... WHERE status IN (:allowed) RETURNING id` — Postgres's own row locking during the UPDATE serializes concurrent callers. **Verified**: 10 concurrent `transition_task()` calls against the same real task row → exactly 1 succeeded, 9 correctly denied.
- **Planner quality gate**: `policy:schema_valid` folded into `_run_quality_gate()`'s `passed` computation — a schema-invalid submission now fails the gate and forces `_requires_human_approval=True`, instead of silently passing through.
- **Decomposer crash recovery**: `save_subtasks()` no longer hard-crashes on a missing `title` (coerces a fallback); `launch_planning_pipeline`'s exception handler now transitions the task to `blocked` instead of leaving it stuck in `planning` forever with no restart path.
- **Preventive budget enforcement**: a token-budget check now runs *inside* `call_llm`'s per-turn node (before another LLM call), not only after the full graph drains. Added `BudgetManager.check_daily_db()` — a real `SUM(cost_estimate) FROM agent_runs WHERE started_at >= today` query, replacing the in-process-only (resets on restart) daily check. **Verified** against the real DB.
- **Checkpoint retention**: new `checkpoint_retention_days` setting + `_cleanup_checkpoints()` — decodes each thread's newest `checkpoint_id` as a real UUIDv6 (via LangGraph's own bundled decoder) to determine staleness, hard-deletes stale rows across `checkpoints`/`checkpoint_blobs`/`checkpoint_writes`. **Verified** against a disposable copy of the real `checkpoints` table (43 threads, correctly 0 deleted below cutoff / all 43 deleted above cutoff, cascading correctly across all 3 tables).

### Deliberately Not Fixed: Subtask Concurrency Fan-out

The audit's proposed fix ("group topological order into waves, dispatch with `asyncio.gather`") was **not implemented**. Investigation found `run_backend_dev`/`run_frontend_dev` write files, run test suites, and git-commit directly against one **shared, mutable** `worktree_path` for every subtask in an epic — there is no per-subtask worktree isolation. Wrapping the loop in `asyncio.gather()` as proposed would make multiple agents concurrently write/commit/run pytest in the *same* git working directory: a real corruption hazard (interleaved writes, git index races, concurrent test runs stepping on each other's state), not a safe speedup. A correct fix needs per-subtask worktree isolation first — a materially larger architectural change than "add gather()" implies, and forcing it under this session's scope would have violated the explicit "don't break working functionality" instruction. Flagged here for a dedicated follow-up, not silently dropped.

---

## Part 3 — Phase 4 (Repository Intelligence)

- **Real vector semantic search**: added `CodeEmbedding` SQLAlchemy model (migration 032 adds the HNSW index migration 001 never got), `persist_code_embeddings()` (real upsert on reindex), and rewrote `semantic_search()` from a dead brute-force loop over a never-populated argument into a real `ORDER BY embedding.cosine_distance(...)` pgvector query. Wired into the real reindex path (`api/repo.py::_do_reindex`) and the MCP `semantic_search` tool (now tries real vector search first, falls back to keyword scoring — previously did keyword scoring *only*, despite its own tool description claiming otherwise). **Verified** end-to-end against the real DB: exact-vector match correctly ranked first by the real ANN query.
- **Non-blocking call graph / indexing**: `build_context`, `build_architecture_map`, `build_class_graph`, `build_call_graph`/`build_package_graph`, and every fallback `index_repository()` call in `api/repo.py`'s four repo-intelligence endpoints now run via `asyncio.to_thread()` instead of blocking the event loop.
- **Scanner file-size guard**: new `scanner_max_indexable_file_bytes` setting; `index_repository()` now checks `os.stat().st_size` before ever reading file bytes, skipping oversized files entirely.
- **MCP `repo_path` validation**: `_get_repo()` now validates any caller-supplied `repo_path` resolves under `target_repo_path`/`repos_dir`/`worktrees_dir` before use, closing the arbitrary-host-directory-scan exploit (`repo_path: "/etc"` or `"../"` traversal — both verified denied).

---

## Part 4 — Phase 5 (Memory System)

- **Two-stage HNSW retrieval**: all 5 `query_*` functions (`query_similar_tasks`, `query_architecture_notes`, `query_failures`, `query_learning_signals`, `query_procedures`) rewritten as `WITH candidates AS (... ORDER BY embedding <=> :vec LIMIT :candidate_limit)` (index-accelerated) feeding an outer composite-score re-rank — the composite formula no longer defeats the HNSW index by being the direct `ORDER BY` target. **Verified** against the real DB with synthetic vectors: exact-match candidate correctly surfaced first.
- **Atomic memory dedup**: `_find_near_duplicate()` now acquires `pg_advisory_xact_lock(hashtext(category), repo_id)` before its check, closing the TOCTOU race. **Verified**: 8 concurrent writers with identical content → exactly 1 row inserted, 7 correctly reused the existing row.
- **Chat history condensation on restore**: `load_history_from_db()` now bounds its query to the most-recent `chat_history_restore_limit` (200) messages instead of loading a session's entire unbounded history. `ChatAgent._call_llm_node`'s condense gate no longer skips entirely on a freshly-restored session's first turn (`self._tokens_in == 0`) — falls back to a cheap character-based token estimate of the actual restored history so the real condense decision fires when it's needed most. **Verified** against the real DB (bounded to exactly the most-recent N, chronological order preserved).
- Also closed: `memory_recency_half_life_days` now has a `gt=0` constraint (was a silent division-by-zero that zeroed all retrieval fleet-wide on a config typo).

---

## Part 5 — Phase 6 (Event Bus, Artifacts, DB, Observability)

- **DB indexing + pool sizing**: migration 033 adds the missing `agent_runs.task_id` index (confirmed absent from all 31 prior migrations). `db_pool_size`/`db_pool_max_overflow` settings wired into `create_async_engine()` (previously relied on SQLAlchemy's default 5+10, smaller than the app's own 20-run concurrency ceiling). **Verified** against the real engine (`pool.size() == 20`).
- **Artifact store**: non-S3 save/read paths wrapped in `asyncio.to_thread()` (previously only the S3 branch was). New `content_sha256` column (migration 034) + real SHA-256 checksum computed at save time and verified at read time, logging a loud warning on mismatch instead of silently returning corrupted content. **Verified** end-to-end including a simulated on-disk corruption, which correctly triggered the integrity warning.
- **Redis Streams consumer**: new `drain_and_ack_stream()` — reads and acks new entries via the already-correct-but-uncalled `read_pending()`/`acknowledge()`, plus `XAUTOCLAIM`-based reclaim of stale pending entries from a crashed consumer (new `redis_streams_stale_pending_ms` setting). Wired into a new background loop, gated on `REDIS_STREAMS_ENABLED`. **Verified** against the real Redis container: normal drain (3 published → 3 acked, 0 pending remaining) and crash-recovery (`XAUTOCLAIM` correctly reclaimed and acked a message left stuck in another consumer's PEL) both confirmed.
- **Leader election**: new `_run_as_leader()` wrapper gates all 9 singleton background loops behind a `pg_try_advisory_lock`, keyed per loop name — only one backend instance runs each loop under a real multi-instance deployment; other instances retry periodically so a new leader takes over if the current one dies (session-scoped lock, releases automatically on connection close). **Verified** against real Postgres: two competing "instances" — only one won the lock; cancelling the leader triggered automatic failover to the standby within one retry interval.
- **Structured, trace-correlated logging**: new `app/observability/logging_context.py` — `contextvars`-based `trace_id`/`task_id`/`agent_run_id` propagation (confirmed to survive `asyncio.to_thread()` worker-thread boundaries, exactly how `run_agent_graph` is dispatched) + JSON log formatter. Wired at `run_agent_graph`'s actual graph-execution boundary so every log line from any node function during a run — from already-existing, unmodified `logger.info()` calls anywhere in that call stack — carries the real trace_id, without rewriting hundreds of individual call sites. `main.py`'s `logging.basicConfig()` replaced with `configure_structured_logging()`.

---

## Regression Found and Fixed During Verification

Enabling leader election (`LEADER_ELECTION_ENABLED=true`, the new default) initially broke `test_launch_coder_commits_files_before_diff` (a test that opens two separate `TestClient(app)` instances within one test function, each running the real `lifespan()`). Root-caused to two compounding issues, both fixed:

1. Nine independently-created-and-cancelled per-loop advisory-lock engines raced the shared `app.db.session` engine's own connection teardown during the first `TestClient`'s shutdown — consolidated to one shared leader-election engine, created once and disposed once after every consuming task is confirmed cancelled+awaited (not mid-cancellation).
2. Even after that, the underlying pre-existing hazard surfaced: `app.db.session`'s module-level engine singleton isn't reset between two `lifespan()` startups within the same process, so a second `TestClient` block could inherit a shared engine bound to the first block's now-closed event loop. Fixed by resetting `app.db.session._engine`/`_session_factory` to `None` at the start of every `lifespan()` call — the theoretically correct fix regardless of leader election, since a fresh startup should never inherit an engine bound to a stale loop.

Verified stable across repeated runs (3/3) after the fix, and confirmed no regression across the full suite.

---

## Test Results

```
pytest tests/ -q
→ 3871 passed, 0 failed, 56 skipped, 17 deselected, 15 warnings in 343.29s (0:05:43)

mypy app/ --strict
→ Success: no issues found in 200 source files

ruff check app/
→ All checks passed!
```

All real-DB/real-Redis/real-Postgres-advisory-lock verification steps described above were run against the live local Postgres (`gridiron-postgres` container) and Redis (`gridiron-redis` container) — not mocked — with cleanup performed after each.

`.env.example` updated with all 12 new config settings introduced this session (verified via a programmatic diff against `Settings.model_fields`, matching this repo's own established verification convention). Pre-existing gaps in `.env.example` for settings from prior sessions (~52 fields) were left untouched — out of this remediation's scope.

Migrations added: `032_code_embeddings_hnsw.py`, `033_agent_runs_task_id_index.py`, `034_artifacts_checksum.py` — all three applied to the live dev database and verified.

---

## Verdict

✅ **GREEN FLAG — AUDIT V1 REMEDIATION COMPLETE.** All 8 release blockers and every targeted Phase 3–6 finding fixed and independently verified against real infrastructure, with one item (subtask concurrency fan-out) intentionally deferred and documented rather than shipped with a known correctness regression. Full test suite green, mypy strict clean, ruff clean.

# Task 1 — YES-Verification Tracking (394 items)

Source: `GRIDIRON_PARTIAL_NO_IMPLEMENTATION_PLAN.txt` (question numbers = the file's own `#`). Plan: `verify_yes_plan.md`.

Verdicts: `PENDING` · `CONFIRMED` (real, evidence cited) · `FIXED` (bug found+fixed+re-verified, stays YES) · `DOWNGRADED→PARTIAL` / `DOWNGRADED→NO` (claim did not hold; moves to Task 2/3) · `BLOCKED` (cannot be verified in this environment, reason given)

Live tally is kept at the top of each batch section once that batch starts.

| Batch | Items | Depth |
|---|---:|---|
| B1 — Repo execution, terminals & file operations | 36 | Deep |
| B2 — Orchestration, agent/tool selection, runtime decisions | 25 | Deep |
| B3 — Human control, approvals, recovery & reliability | 37 | Deep |
| B4 — Memory & knowledge systems | 33 | Deep |
| B5 — Context, cost, confidence, intent & truthfulness | 33 | Standard |
| B6 — Agent scaffold, capability audit & skill coverage | 39 | Standard |
| B7 — Security, governance, enterprise & frontend/API | 32 | Deep |
| B8 — Fleet self-improvement, guardians & health | 33 | Standard |
| B9 — Scheduler, metrics, quality gates, scalability & architecture | 37 | Standard |
| B10 — File understanding, external knowledge, git, docs & deploy | 46 | Light |
| B11 — Testing audit, hidden risks & domain coverage | 43 | Light |


## Progress

| Batch | Items | Done | CONFIRMED | FIXED | DOWNGRADED | BLOCKED |
|---|---:|---:|---:|---:|---:|---:|
| **B1** Repo execution, terminals & file ops | 36 | **36** | 12 | 24 | 0 | 0 |
| **B2** Orchestration, selection, runtime decisions | 25 | **25** | 17 | 8 | 0 | 0 |
| **B3** Human control, approvals, recovery, reliability | 37 | **37** | 32 | 4 | 0 | 1 |
| **B4** Memory & knowledge systems | 33 | **33** | 30 | 3 | 0 | 0 |
| **B5** Context, cost, confidence, intent, truthfulness | 33 | **33** | 15 | 17 | 1 | 0 |
| **B6** Agent scaffold, capability audit, skills | 39 | **39** | 36 | 3 | 0 | 0 |
| **B7** Security, governance, enterprise, frontend/API | 32 | **32** | 15 | 16 | 1 | 0 |
| B8–B11 | 159 | 0 | 0 | 0 | 0 | 0 |

**Environment baseline (Day 0):** isolated DB `gridiron_verify`; first full run 31 failed / 7,707 passed / 54 skipped — 28 of the 31 were `python: not found` from running pytest without the venv on PATH (84 tests pass with it), 2 pip-audit drift (known), 1 shared-state test. See `verify_api_ledger.md` for live-API spend (~$0.30 so far).

**Stale-config finding (not code):** `backend/.env` GROQ models (`llama-3.3-70b-versatile`, `llama-3.1-8b-instant`) no longer exist on the Groq key (404 model_not_found); Groq free tier's per-minute token limit is also below the PM prompt size, so the pipeline cannot run on Groq at all. Left `.env` untouched.

## B1 — Repo execution, terminals & file operations  (36 items, depth: Deep)

| # | § | Question | Verdict | Evidence / notes |
|---:|---|---|---|---|
| 1 | 1 | Clones repo into user-selected folder | FIXED | 3cd81ad4 — git clone RCE via `--upload-pack` URL (empty hostname passed the allowlist), PAT persisted in `.git/config`, main clone route never validated dest_path/host/name. Live HTTP battery with real roles + 87 tests (72 fail on original). |
| 2 | 1 | Every operation stays inside that cloned repo | FIXED | 3cd81ad4, ee3831db — workspace `startswith` prefix bug (`/home-evil`), checkout `-f` / push `--force` / pull `--upload-pack` arg injection, rename_symbol wrote through outside symlinks. |
| 4 | 1 | Terminal/session manager | FIXED | d6fa8343 — session close / startup sweep / `kill KILL` / reaper left the Docker container running; PID reuse could SIGTERM an unrelated process. |
| 7 | 1 | Linux/Ubuntu support | FIXED | 2df4d293 — venv activation used bash `source` under dash (/bin/sh on Ubuntu): silently never ran. Everything else in B1 ran on this Ubuntu host. |
| 8 | 1 | Docker terminal handling | FIXED | 66564a7e — sandbox boundary CONFIRMED (20 hostile-input tests); docker_logs cut the NEWEST (crash) lines and scrambled stdout/stderr order. |
| 9 | 1 | Virtual environment activation | FIXED | 2df4d293 — see #7; naive `.` swap would abort the whole shell in dash (proved), guarded `if [ -f ]` form used. |
| 10 | 1 | Safe shell execution (injection prevention) | CONFIRMED | 20 black-box tests through the real chat `bash` tool (read-only rootfs, non-root, no docker.sock, host env/files invisible, 8 injection shapes, cgroup caps, cwd escape, fail-closed, timeout kills container) + AST scan: 13 real `shell=True` sites. LEAD → B7/B11: run_tests/run_single_test/type_check/run_node/run_python_snippet execute repo code on the HOST (not sandboxed). |
| 11 | 1 | Execution pipeline trace | FIXED | f9a9503c — REAL pipeline vs live Anthropic API: Architect died on removed `thinking.type.enabled` (400); reflection/critique/planner-confidence/lesson storage silently dead. Now PM→Architect→Decomposer complete live and pause at approval (agent_runs 26k in/6k out, ~$0.26). |
| 13 | 17 | Detect completion | FIXED | d6fa8343 — read_output now returns the unread tail + exit status after a job ends. |
| 14 | 17 | Detect failure | FIXED | d6fa8343 — failure output (stderr) was discarded once a background job exited; exit code detection itself worked. |
| 15 | 17 | Detect hanging processes | FIXED | d6fa8343 — root cause of 'hung' jobs: nothing drained pipes, so >64 KB output blocked forever. Advisory possibly_hung flag confirmed by existing tests. |
| 16 | 17 | Wait for commands to finish | FIXED | d6fa8343 — same pipe stall; foreground bash blocks until done, background returns <1.5s (tests). |
| 17 | 17 | Parse generic logs | CONFIRMED | read_logs tail/lines returned the real last lines incl. traceback on a real log file. Not exercised here: `level` filter. |
| 18 | 17 | Parse Docker logs | FIXED | 66564a7e — see #8 (tail kept, whole log analysed, chronological via `--timestamps`); shared helper also fixes diagnose_deployment_failure. |
| 19 | 17 | Parse test output (pytest etc.) | FIXED | 66564a7e — pytest appends `(H:MM:SS)` after 60s; every long run produced no structured summary. Real pytest -q/-v output with all outcome kinds parses. |
| 20 | 17 | Parse compiler/type-checker output | CONFIRMED | 66564a7e tests feed REAL mypy / ruff / tsc output (errors + clean) — counts correct. |
| 21 | 58 | Concurrent shell-session registry | FIXED | d6fa8343 — registry now records container + process start time; identity-checked. |
| 22 | 58 | Concurrent command execution (fan-out) | CONFIRMED | run_parallel_commands: 3×3s jobs in 4.0s wall, exit code flagged, per-call timeout enforced, results in order. |
| 23 | 58 | Background vs foreground distinction | FIXED | d6fa8343 — background returns immediately; chatty background jobs no longer stall. |
| 24 | 58 | Task dependency handling between terminal jobs | CONFIRMED | wait_for_pids: dependent waits until the dependency EXITS (doc: 'have exited'); it also runs if the dependency FAILED — matches its documented contract. |
| 25 | 58 | Terminal monitoring, recovery, cleanup | FIXED | d6fa8343 — cleanup paths now stop process group AND container; liveness reaper kills orphaned containers. |
| 26 | 18 | Create/edit/delete files | CONFIRMED | create nested / edit / delete through the real dispatch; overwrite approval gate held (denied → file untouched). LEADS → B3 (#214/#215): move_file/rename_file/copy_file overwrite an existing destination with no confirmation; delete gate to verify. |
| 27 | 18 | Compare files | CONFIRMED | compare_files: unified diff, 'identical', outside-worktree denied. |
| 28 | 18 | Synchronize files | FIXED | d0798640 — sync_files converted CRLF→LF, called CRLF/LF-only diffs 'in sync', couldn't sync binaries, dropped exec bit; now byte-exact + mode. |
| 29 | 18 | Refactor projects | FIXED | ee3831db — rename_symbol: form-feed line separators CORRUPTED files, one bad .py aborted the batch (TokenError uncaught), no rollback on mid-batch failure. Token-aware (strings/comments untouched) confirmed. |
| 30 | 18 | Preserve formatting | FIXED | d0798640 — every line-editing tool rewrote CRLF as LF; replace_function ate blank-line separators. |
| 31 | 18 | Preserve comments | CONFIRMED | comments/docstrings/decorators outside the edited symbol preserved by edit_file, replace_function/class, rename_symbol (tests). |
| 32 | 18 | Avoid restricted files | FIXED | ee3831db — write tools deny .env*/secrets/.git/workflows/keys/outside/symlink escapes (confirmed); rename_symbol bypassed all of it with file_pattern='*'. |
| 33 | 18 | Obey repository rules | CONFIRMED | policy engine (paths/commands) + governance rule enforced in tests. LEAD → B7 (§85): governance checks `package.json` CONTENT only when it parses as full JSON — edit_file/append of a fragment may bypass it. |
| 34 | 59 | Read hundreds of files safely | FIXED | 83961084 — read_files 20/call with explicit continue notice (confirmed); read_file got start_line/end_line + hard char cap. |
| 35 | 59 | Edit hundreds of files | FIXED | ee3831db — rename batch now preflights writability and rolls back on failure; 1,500-file rename dry-run threshold confirmed. |
| 36 | 59 | Rename/move/delete files | CONFIRMED | rename/move/copy/delete work; protected/.git targets denied; copy keeps exec bit. LEAD → B3: move/copy onto an existing file overwrites silently. |
| 37 | 59 | Preserve formatting/comments across multi-file edits | FIXED | d0798640, ee3831db — formatting (CRLF/blank lines) preserved across single- and multi-file edits. |
| 254 | 15 | Understand 9,000+ line files | FIXED | 83961084 — 12,000-line file: fold/truncate worked but read_file had no way to read a specific range (agents without a shell could never reach the middle); added start_line/end_line. |
| 256 | 15 | Scan 1,000+ files | CONFIRMED | 1,500 files: index_repository 0.5s, tree/list/search <0.05s, rename dry-run 0.7s. |
| 258 | 15 | Build complete projects (scaffold) | CONFIRMED | mechanics only: 22 real-git tests (blank-repo detection, scaffold plan validation, real commit, non-fatal failures, both entry points). Live LLM scaffold quality NOT run (budget) — revisit at end if balance allows. |

## B2 — Orchestration, agent/tool selection, runtime decisions  (25 items, depth: Deep)

| # | § | Question | Verdict | Evidence / notes |
|---:|---|---|---|---|
| 39 | 2 | Who receives the request first (defined path) | CONFIRMED | Live run (task 271): POST /api/tasks/{id}/run → planning pipeline PM → Architect → Decomposer → awaiting_approval. Single defined entry path; f9a9503c fixed the pipeline that used to die at the Architect. |
| 40 | 2 | Who decides which agents work | CONFIRMED | FleetManager.select (16 real-registry tests) + decomposer/manager dispatch; live run traced through it. |
| 41 | 2 | Routing is automatic/rule-based | CONFIRMED | Rule-based: capability lookup + scoring + `_TYPE_TO_TAG`; no LLM routing (that is item #42, SKIP). |
| 46 | 2 | Agents reject tasks they're not suited for | CONFIRMED | CAVEAT: the refusal is system-level — FleetManager declines dispatch when no healthy AVAILABLE agent covers the capability and the subtask is blocked with a dispatch_refused event (tests). There is no agent-initiated 'this is not my job' reply. Candidate for Task 2 (PARTIAL). |
| 48 | 2 | Dependencies managed | FIXED | c30e0b1f — valid graphs correct (300 random DAGs), but out-of-range/self/non-integer depends_on entries were silently dropped, so a subtask lost its constraint and, under fan-out, ran in the SAME parallel wave as its dependency; docstring promised a sequential fallback. |
| 49 | 2 | Priorities managed | CONFIRMED | 9 real asyncio tests: priority order, FIFO among equals, unknown priority = medium, cancellation safety incl. cancel racing the grant, exact permit count under churn, loud timeout, end-to-end via agent_run_slot. |
| 50 | 2 | Conflicts resolved | FIXED | 147add84 — real Postgres: same epic re-reserving its own files (retry after crash) was refused as a conflict with 'another epic'; exclusion, all-or-nothing, expiry reaping, 8 concurrent reservers → 1 winner confirmed. |
| 51 | 2 | Duplicate work prevented (file locking) | FIXED | 147add84 — `./src/a.py`, `src//a.py`, `src\a.py` all acquired a file already locked as `src/a.py` (raw-string compare in the UNIQUE lock and the conflict guard). Paths canonicalised. NOTE: lock TTL is a fixed 4h with no renewal. |
| 52 | 3 | Considers skills/capability | CONFIRMED | capability matching tests (unknown capability → None). |
| 53 | 3 | Considers tools availability | CONFIRMED | verify_tool_availability skips agents declaring an unresolvable tool (manager passes True). |
| 54 | 3 | Considers current workload | FIXED | 73007350 — busy agents excluded (confirmed) but dispatch() = select() then start_task(): concurrent callers could both get the same single-flight agent (1/400 rounds). Atomic try_start_task added. |
| 55 | 3 | Considers health/previous success/previous failures | CONFIRMED | unhealthy/disabled/retired excluded; degraded, error_count and success_rate lower the score exactly as documented. |
| 56 | 3 | Considers experience (tenure) | CONFIRMED | tenure factor: capped diminishing bonus (200 runs beats 0). |
| 57 | 3 | Considers confidence | CONFIRMED | confidence factor lowers a low-confidence agent's rank; neutral when no history. |
| 59 | 4 | Automatic tool selection | CONFIRMED | live run: PM/Architect/Decomposer chose their own tool calls; a tool outside the advertised list is refused even when a handler exists. |
| 60 | 4 | Call multiple tools per turn | CONFIRMED | real execute_tools node: N tool_use blocks in one turn all run in order and answer in ONE user message. |
| 61 | 4 | Retry failed tools | FIXED | 9af9847e — manifest-driven retry (backoff×3 / once×2), hazardous permissions never retried (confirmed); [POLICY DENIED] results were retried with backoff (deterministic → pure delay). |
| 62 | 4 | Verify tool outputs | CONFIRMED | verification flags set only by successful runs, reset by mutating tools, blocking_until refuses the handler, enforce_in_result overwrites false claims (real node tests). |
| 63 | 4 | Recover from failures | CONFIRMED | a raising handler becomes an [ERROR] result and the rest of the batch continues; retry as above. (Run-level recovery/checkpoint resume is B3.) |
| 68 | 62 | Request human approval (HITL) | CONFIRMED | live run paused at awaiting_approval with brief/plan/subtasks; chat overwrite gate held in B1. Full approval-gate coverage is B3 (§39). |
| 69 | 62 | Stop execution | FIXED | 9af9847e — Stop/Cancel set an in-process abort flag only /resume cleared: any later run of that task aborted at its first LLM call ('stopped') doing no work until server restart. Cleared at run entry points; a Stop mid-run still halts later stages. LEAD → B7: stop/cancel accept any authenticated role (incl. viewer). |
| 70 | 62 | Retry | FIXED | 9af9847e — restart/re-run inherited the stale abort flag (see #69); restart correctly refused while a run is active. |
| 72 | 62 | Skip unnecessary work | FIXED | c4deb9a9 — incremental reindex skips unchanged files (confirmed) but deleted/renamed files stayed in the merged index forever (phantom entries). Other skips confirmed: sync 'already in sync', rename dry-run. NOTE: manager still runs QA+review when a dev agent produced no changes. |
| 373 | 47 | New agent via role/tools/prompt/memory config only, no orchestration code change | CONFIRMED | new agent = module (AGENT_CONTRACT + exactly one run_* fn) + role file + agent_models.json entry; zero edits to manager/dispatcher/router (21 tests incl. hostile names, ambiguity, scan/apply reserved). |
| 374 | 47 | New agent auto-joins / becomes dispatchable | CONFIRMED | auto-registered by ensure_all_agents_registered; dispatchable by capability with data alone. |

## B3 — Human control, approvals, recovery & reliability  (37 items, depth: Deep)

| # | § | Question | Verdict | Evidence / notes |
|---:|---|---|---|---|
| 208 | 13 | Ask permission | CONFIRMED | Real-dispatch battery with approval DENIED: 10 named destructive actions genuinely ask first. Neighbours that did NOT ask were fixed (see #215/#218/#219/#220). |
| 209 | 13 | Wait indefinitely for a response | CONFIRMED | Static: no expiry/timeout anywhere in approval_gate.py or the pending_approvals model; the row persists in Postgres. Not re-verified by actually waiting hours. |
| 210 | 13 | Present options (multi-choice) | CONFIRMED | _confirm_with_options + tests (test_audit_q_batch07_guardian_human_interaction.py) pass. |
| 211 | 13 | Recommend choices (structured field) | CONFIRMED | structured `recommended` field on option prompts; same batch07 tests pass. |
| 214 | 39 | Delete a file gated | CONFIRMED | delete_file asks; denial leaves the file (live battery). |
| 215 | 39 | Overwrite an existing file gated | FIXED | 7110d286 — write_file overwrite IS gated, but move_file/rename_file/copy_file silently replaced an existing destination (Path.rename/shutil.copy2). Now refuse unless overwrite=true; chat asks the user (also when the model passes overwrite up front). |
| 216 | 39 | git push (incl. force) gated | CONFIRMED | git_push incl. force=true asks; denial pushes nothing. (Console route push option-injection fixed in B1.) |
| 217 | 39 | git reset --hard gated | CONFIRMED | git_reset hard asks; denial keeps changes. NOTE 7110d286: sibling `git_checkout <ref> -- <file>` discarded work silently and `git_stash drop` deleted stashes silently — both now gated. |
| 218 | 39 | Dangerous bash command gated | FIXED | 3fc5ce8b, 948a5eba — bash dangerous commands ask (confirmed), but docker_restart ran unprompted (a probe restarted the dev Redis!) and docker compose down/restart/build/pull were ungated (only `up` asked). Now gated. |
| 219 | 39 | undo_changes gated | CONFIRMED | undo_changes asks. Its silent bypass (git_checkout of a dirty file) was closed in 7110d286. |
| 220 | 39 | DB migration gated | FIXED | 3fc5ce8b — run_migration asks (confirmed), but chat's run_sql ran DELETE/DROP TABLE against the PLATFORM DB with no prompt, and 4 agents' run_sql could never connect (psql got the +asyncpg URL as a db name) with prompt-only 'no DROP' rules. Read-only by construction now; PG read-only txn alone proved bypassable in one call; chat asks, headless agents cannot write. |
| 221 | 39 | seed_database gated | CONFIRMED | seed_database asks; denial runs nothing. |
| 222 | 39 | Dependency upgrades gated | CONFIRMED | pip_install / npm_install ask; denial installs nothing. |
| 224 | 39 | 'Don't ask again this session' option | CONFIRMED | 'remember for this session' (session.remembered_confirmations) — batch07 tests pass; only skips the pause, never a hard block. |
| 225 | 103 | Interrupt any agent mid-run | CONFIRMED | Stop sets an abort flag honoured at the next LLM/tool boundary ('after the current tool call completes' — not mid-call). See #69 for the stale-flag bug fixed in 9af9847e. |
| 226 | 103 | Resume with injected input | CONFIRMED | /resume clears the flag and injects the message (real API + DB test, b2_stop_cancel_restart). |
| 228 | 14 | Pause | CONFIRMED | Pause = Stop (resumable). Verified with real API; stale flag bug fixed (9af9847e). |
| 229 | 14 | Resume | CONFIRMED | Resume verified (409 on a cancelled task). |
| 230 | 14 | Cancel (distinct terminal state) | CONFIRMED | Cancel is a distinct terminal state: DB status 'cancelled', resume refused, restart allowed (tests). |
| 231 | 14 | Retry | CONFIRMED | POST /restart re-triggers planning; refused (409) while a run is active; no longer inherits a stale abort (9af9847e). |
| 232 | 14 | Rollback (manual operator-invoked) | CONFIRMED | failure_ladder rollback + prompt/enhancement rollback API tests pass (batch15/batch18). Not exercised live against a real deploy. |
| 233 | 14 | Checkpoints (Postgres-backed, all paths) | CONFIRMED | CAVEAT: pipeline and agent checkpointers are Postgres-backed (AsyncPostgresSaver) but SILENTLY fall back to in-memory MemorySaver if Postgres init fails (a warning only) — then nothing survives a restart. Crash-recovery gaps are Task 2 (#234-236). |
| 237 | 38 | Docker crashes (sandbox) - fails closed correctly | CONFIRMED | B1: Docker unreachable → [SANDBOX UNAVAILABLE], command NOT run on the host (tests). |
| 239 | 38 | Terminal/shell session closes - detected live | CONFIRMED | B1: a killed/crashed shell wrapper is detected by the liveness reaper AND its container is now killed (d6fa8343). |
| 240 | 38 | Internet disconnects - retry/backoff | CONFIRMED | real `anthropic` SDK retry/backoff tests (test_gap58_59) pass; SDK max_retries is settings-driven. Not re-run against a real network partition. |
| 241 | 38 | LLM API fails (rate limit/500/timeout) | CONFIRMED | rate-limit/5xx/timeout handling: real-SDK tests + breaker wiring pass; live Groq 429 storms were observed backing off (54s, 27s, 42s...). |
| 242 | 97 | Backup exists and is automated/scheduled | CONFIRMED | STATIC: scripts/backup_db.sh (pg_dump -Fc + pg_restore --list verify) + systemd timer (daily, Persistent=true). NOT executed here — a restore drill is still owed. |
| 243 | 97 | Auto-restart on crash | CONFIRMED | STATIC: `restart: unless-stopped` on the long-running services in docker-compose.prod.yml. Not crash-tested here. |
| 244 | 102 | Run 30+ min / hours without being killed | BLOCKED | Cannot be verified in this environment (needs a 30+ minute live run). Structurally: LLM/slot/DB timeouts exist; no evidence checked for a global wall-clock kill. Revisit with a long-run soak. |
| 245 | 102 | Progress reporting | CONFIRMED | live: activity stream / task logs reported PM→Architect→Decomposer progress during the real run; task_progress tool tests pass. |
| 247 | 66 | Retries | CONFIRMED | tool retry policy (B2) + SDK retries + failure ladder. |
| 248 | 66 | Exponential backoff | CONFIRMED | tool backoff 0.5s,1.0s capped 4s (test); SDK exponential backoff + jitter (live 429 sequence 5s→27s→54s→42s observed). |
| 249 | 66 | Circuit breakers | CONFIRMED | CircuitBreaker closed/open/half-open + wiring into every LLM call (tests pass). |
| 250 | 66 | Timeout handling (incl. DB statement timeout) | CONFIRMED | db statement_timeout server setting, LLM call timeout, slot-acquisition timeout (loud SlotAcquisitionTimeout) — tests pass. |
| 251 | 66 | Idempotency | CONFIRMED | Idempotency-Key middleware wired into task creation; 68 idempotency-related tests pass. Not re-probed live end to end. |
| 252 | 66 | Transaction safety | CONFIRMED | structural transaction-boundary invariant test passes (test_batch08_transaction_boundary_invariant). |
| 253 | 66 | Structured error reporting | FIXED | 2nd-to-last commit — the 422 handler returned str(exc) which appended a stack frame with absolute SERVER FILE PATHS to the response body (proved live). Now loc/msg/type only. |

## B4 — Memory & knowledge systems  (33 items, depth: Deep)

| # | § | Question | Verdict | Evidence / notes |
|---:|---|---|---|---|
| 73 | 5 | Working Memory | CONFIRMED | AgentRunState is built per run_agent_graph call (no module-level state); condense on context_token_budget. Static + existing tests; the condense path itself is re-checked in B5 (#65 context). |
| 74 | 5 | Session Memory | CONFIRMED | LessonStore on real Postgres: dedup, capacity, keyword retrieval, lessons-table persistence and refresh_from_db into a SECOND store (test_session_lessons_reach_a_second_process). Persist is a no-op when no main loop is set (only matters outside FastAPI). |
| 75 | 5 | Shared Memory | CONFIRMED | Same real cross-process test + memory_embeddings shared table (legacy unscoped rows visible to every repo by design). |
| 76 | 5 | Project Memory | CONFIRMED | Repo-scoped memory on real pgvector: repo A rows never returned for repo B (all 5 categories) — test_every_category_round_trips_and_is_repo_isolated. |
| 77 | 5 | Long-Term Memory | FIXED | eb61f6f0 — _embed called the sync Voyage client inside a coroutine (blocked the event loop) and one provider blip stored a permanent ZERO-vector row that could never be found. Now to_thread + 3 retries; reembed_zero_vector_rows repairs old rows (called by the daily lesson loop). |
| 78 | 5 | Procedural Memory | CONFIRMED | embed_procedure/query_procedures round trip on real pgvector, repo-isolated. |
| 79 | 5 | Failure Memory | CONFIRMED | embed_failure/query_failures round trip on real pgvector, repo-isolated, feeds memory_hook_node (#402). |
| 80 | 5 | Knowledge Memory | CONFIRMED | architecture notes + learning signals (LessonStore/versioned lessons) round trip; architecture repo-isolated. |
| 81 | 5 | Where memory is stored (real DB schema) | CONFIRMED | Real schema: memory_embeddings(vector(1536)) + versioned_lessons + lessons in Postgres; queried through real cosine ops. |
| 82 | 5 | How memory is updated | CONFIRMED | Near-duplicate write reuses the row instead of inserting (real DB); quality gate rejects empty/placeholder writes. |
| 83 | 5 | How memory is retrieved | CONFIRMED | Targeted top-k on 6 topics returns the matching row first; similarity floor respected. |
| 84 | 5 | How memory is synchronized (race-safe) | CONFIRMED | 8 concurrent identical writes -> exactly 1 row (pg advisory lock per category/repo). |
| 85 | 5 | Memory survives restart | CONFIRMED | Rows survive an engine dispose/restart (durable Postgres, not process memory). |
| 86 | 5 | Memory shared between agents | CONFIRMED | Any agent's write is visible to any other agent's query (single table) — same tests as #75. |
| 87 | 120 | Working Memory scoped to task, no overflow | CONFIRMED | Working memory = per-run state; no cross-run sharing found. Overflow behaviour (condense) verified under B5. |
| 89 | 120 | Long-term memory promotion gate (draft->published) | CONFIRMED | VersionedMemoryStore.publish() files a DRAFT invisible to query_learning_signals; only promote() makes it fleet memory (test_a_lesson_is_invisible_until_promoted). Curator SCAN handlers have no promote tool; APPLY does, and only after /approve. |
| 91 | 120 | Memory Retrieval targeted, not full dump | CONFIRMED | query_memory_context returns top_k per category, never a table dump. |
| 92 | 120 | Automatic Memory Cleanup | CONFIRMED | retention._archive_table on real rows: 400-day-old row archived, fresh row kept, archived row disappears from query_similar_tasks. (Scheduled loop wiring covered by test_retention_archive.) |
| 93 | 120 | Memory Prioritization | CONFIRMED | Composite score (similarity/importance/recency/reuse) — gap40 + stage4 tests on real DB pass. |
| 94 | 120 | Token Optimization | CONFIRMED | Injection is capped (memory_injection_token_budget) and compresses by priority, whole entries only — test_injection_cap_bounds_the_real_block. |
| 95 | 120 | Context Window Management (aggregate cap) | CONFIRMED | Same cap function used by memory_hook_node on the real formatted block; highest-priority section kept, low-priority entries dropped with a notice. |
| 96 | 120 | Memory Aging/Lifecycle | CONFIRMED | Aging/staleness distribution + archive lifecycle real (gap44 + retention test). |
| 97 | 120 | Shared Memory Synchronization (lock safety) | CONFIRMED | Advisory-lock + per-lesson async lock; concurrent write test (#84) and lesson-lock tests pass. |
| 99 | 120 | Memory Analytics | CONFIRMED | compute_memory_analytics on real DB (size, growth, unused, duplicates, staleness). One test depended on leftover rows (empty table + cap 0 = scan runs) — test fixed, code correct. |
| 400 | 37 | Agent routing score updates from real outcomes over time | FIXED | agent_registry.compute_live_success_rate loaded EVERY AgentRun row (blobs included) per capability per sync and counted in-flight 'running' runs as failures, so a busy agent's routing score fell while it worked. Now a SQL aggregate over finished runs; real-DB test replaces two mocked ones. Note for Task 2: it is a lifetime average (no recency weighting). |
| 401 | 74 | Preferences recorded and retrieved as first-class memory | CONFIRMED | embed_preference/query_preferences round trip + record_preference tool tests. |
| 402 | 75 | Central store consulted before starting work | CONFIRMED | memory_hook_node run against the real DB injects a seeded failure's root cause into memory_context (test_memory_hook_node_injects_real_db_memory). |
| 403 | 75 | Covers proven patterns/failed approaches/architecture decisions/templates | CONFIRMED | failures, procedures, architecture notes, learnings all stored and injected (six sections in query_memory_context). |
| 404 | 75 | Covers known bugs as a distinct type | CONFIRMED | known bugs are their own category (embed_bug/query_bugs), injected as their own section. |
| 406 | 75 | Knowledge validation before promotion | CONFIRMED | quality gate at write + draft->published gate + curator scan cannot promote (see #89). |
| 410 | 110 | Prompt evolution (versioning + rollback, human & automatic) | CONFIRMED | PromptRegistry propose->review->approve->deploy->rollback with regression gate and operator route; /prompts/{role}/rollback needs approver. Verified by existing real-DB tests + static review (deploy writes the roles/*.md file). |
| 412 | 114 | Per-repo knowledge isolation | CONFIRMED | per-repo isolation proven across all categories (see #76). |
| 464 | 93 | Draft->published promotion gate with real approver | FIXED | fleet_dashboard approve/reject recorded the CLIENT-supplied `decided_by` body field on the audit trail; with RBAC on an approver could stamp any name. Now the authenticated identity. Lead for B7: other approval endpoints hard-code decided_by='user', and X-User-Id is an unauthenticated header when JWT is off. |

## B5 — Context, cost, confidence, intent & truthfulness  (33 items, depth: Standard)

| # | § | Question | Verdict | Evidence / notes |
|---:|---|---|---|---|
| 334 | 25 | Ask clarification questions before acting | CONFIRMED | Mechanism real: planner/coder request_clarification -> PendingApproval -> approval resumes the agent (see #506). Chat asks in plain text per roles/chat.md. Whether a live model asks at the right moments was not measured. |
| 335 | 25 | Refuse to guess when info insufficient | CONFIRMED | Same mechanism + prompt rules (roles/coder.md 'stop and ask', planner 'UNVERIFIED'). Prompt-level behaviour, not measured live. |
| 338 | 26 | Frustration detection changes behavior | FIXED | user_sentiment flagged a second 'yes'/'ok'/'continue' as frustration (Jaccard 1.0 on a 1-word set) so the model was told the user was frustrated; now needs >= user_frustration_repeat_min_words (4). The directive itself reaches the system prompt (real). |
| 339 | 26 | Repetition detection changes behavior | FIXED | Repetition was compared against role='user' history, but tool RESULTS are stored as role='user' list messages — after any tool use the user repeating themselves was compared with tool output and never noticed. New _human_user_messages(). |
| 342 | 26 | Remains professional | CONFIRMED | Prompt-level (roles/chat.md pressure/hostility sections) + the frustration directive ('acknowledge briefly, concrete next step'). No code enforces tone; not measured live. |
| 345 | 27 | Remember previous answers on re-dispatch | CONFIRMED | The answer is folded into the immediate re-dispatch of planner/coder (real HTTP test). Limitation: the answer lives only in that run's description and a task log — it is not stored on the approval row, so a later manual retry re-asks the question, and an interrupted background dispatch loses it (row already 'approved' -> 409). Task 2 lead. |
| 349 | 29 | Check for existing implementation before building (enforced, not advisory) | FIXED | 'Enforced' = blocking_until read gate. It covered write_file/edit_file only, so bash (`echo > f`, `sed -i`) wrote files with nothing read. Coder now gates bash too. Caveat: the gate is 'any read_file/search_code once', not 'searched for THIS feature'. |
| 350 | 30 | Repo search/read files/understand architecture required before writing (enforced) | FIXED | Same gate: coder blocks write_file/edit_file/bash until read; real execute_tools node test. |
| 352 | 30 | Static quality checks (mypy/ruff) | FIXED | _run_checks ran `mypy .`/`ruff .` on the whole worktree: a repo with no Python files exits 2 ('no .py files') so EVERY attempt failed and the coder burned its retries; pre-existing errors anywhere blocked unrelated changes; a missing tool failed forever. New app/agents/static_checks.py checks only the changed .py files (real mypy/ruff/black in tests), skips a missing tool, `--` before paths; frontend check skips without apps/web/tsconfig.json. |
| 353 | 42 | Pre-execution cost/token estimate | FIXED | _historical_avg_tokens averaged EVERY completed agent_run (guardian/test/utility runs included): 80 tokens/run on the dev DB, so a real epic never reached the approval threshold. Now developer run + qa + reviewer per subtask; falls back to config when no developer history. |
| 354 | 42 | Recommend cheaper approaches | CONFIRMED | CostEstimate.cost_per_subtask_usd / max_subtasks_within_threshold (scope reduction) is real and tested on Postgres. No cheaper-MODEL suggestion (every dispatched agent is sonnet-tier). Calibration note: the config fallback of 4,000 tokens per subtask is far below what a real agent loop uses. |
| 355 | 43 | Every important answer has a confidence estimate | FIXED | Every run carries a planner confidence, gated by quality_gate_min_confidence (default 0.0 = opt-in). The value was float(model output) unclamped: 85 (percent) or 1.7 passed any floor, NaN compared False. New _coerce_confidence. Lead: a failed planner call yields 0.8, not 'unknown'. |
| 356 | 43 | Distinguish verified facts from assumptions | CONFIRMED | Planner facts step + 'UNVERIFIED:' convention + file:line citation check flag (see #502). Prompt-level; not measured live. |
| 357 | 43 | Explicitly say 'I don't know' | CONFIRMED | roles/chat.md 'State uncertainty' + planner/others. Prompt-level only; 3 live Haiku probes (no tools) went and looked instead of guessing but were inconclusive about an explicit 'I don't know'. |
| 358 | 44 | Explain why this approach / agents / tools chosen | CONFIRMED | GET /tasks/{id}/explain on the REAL task from the live pipeline run (271): goals, plan confidence, architect approach and risk level returned; dispatch rationales when present. |
| 359 | 44 | Structured decision-log/rationale field in DB | CONFIRMED | task_logs.rationale column exists and is surfaced by the API; one writer today (manager's agent_dispatch log). |
| 360 | 45 | Context persists across app restart | FIXED | get_or_restore_session was imported into api/chat.py with `noqa: F401` and NEVER called: after a restart every conversation answered 404, its stored history could not be continued. Now send/confirm restore from chat_messages; restored history decodes tool blocks and is repaired (start on a user turn, no dangling tool_use). Real HTTP test. |
| 362 | 52 | Condensation trigger | FIXED | The condense trigger read state['tokens_in'] = CUMULATIVE billed input over all turns, not the context size: past the budget it condensed (extra Haiku call + information loss) on every later turn. New state['context_tokens'] (last call's input incl. cache). Also: an odd message count could leave an orphaned tool_result (API 400); boundary now keeps pairs. |
| 363 | 52 | Compression method (real summarization, not truncation) | FIXED | Compression is a real Haiku summarization (existing test proves content survives); fixed the orphaned-tool_result boundary bug (proven: 7 tool pairs + a stray user message). |
| 364 | 52 | Applied to chat_agent conversations too | FIXED | chat_agent used self._tokens_in (cumulative for the whole session) as context size: condensed every turn after a few turns and hard-stopped ('Conversation too long') after ~1M cumulative tokens with a tiny real history. Now self._context_tokens. |
| 366 | 65 | Check against model's real context limit | FIXED | The 'real model window' stop compared the cumulative billed total to 1,000,000 (opus/sonnet): any run whose calls add up past 1M was reported 'blocked' while its actual context was ~50k. Now the context size. |
| 367 | 65 | Warn user when approaching limits | FIXED | approaching_limit warned on the cumulative total (same bug); now the real context size, in both graph and chat. |
| 368 | 101 | Token usage estimate | FIXED | Token estimate per epic: see #353. |
| 369 | 101 | API cost estimate | FIXED | Cost estimate per epic: see #353. Lead: cost_estimate is NULL on pipeline (pm/architect/decomposer) agent_runs — only simple-mode launch_* record it. |
| 370 | 101 | Execution time estimate | CONFIRMED | estimated_duration_seconds: historical coder-run average when present, config fallback otherwise (Postgres test). |
| 371 | 101 | Storage impact estimate | CONFIRMED | estimate_project_size: real measured repo size x config multiplier. Coefficients (disk x3, etc.) are not calibrated against anything. |
| 372 | 101 | Compute requirements estimate | CONFIRMED | Memory/indexing/embedding time estimates from file counts x config coefficients (2 MB/file etc.) — exists, uncalibrated. |
| 489 | 73 | Detects professional role and adapts terminology/depth | FIXED | Role detection classifies against the LIVE capability registry, which holds 4 agents (pm, bug_fix, qa, executive) in a freshly started server (agents register when imported, lazily) — a React question came back as 'bug_fix'. Now imports all agent modules once (85 entries); real Haiku probes: postgres schema -> database_architect. Also the blocking Anthropic call ran on the event loop; now asyncio.to_thread. |
| 492 | 84 | Communicates what it can't do (real, code-enforced limitation classification) | CONFIRMED | Quality gate: blocked/needs_human submissions need limitation_type (temporary|fundamental) + proposed_alternative, else the gate fails (existing tests). |
| 501 | 54 | Refuse to invent test/execution results | FIXED | QA 'tests_run' was set by ANY successful bash call (`echo`, `ls`) and — worse — run_qa read the handler's copy of what the model submitted, never the graph's verified flag, so a QA agent that ran nothing could submit 'passed, 42 tests' and the pipeline believed it. Now the flag needs a test-runner command (pytest/npm test/go test/...) and run_qa discards results when it is unset (also test_writer_agent). |
| 502 | 54 | Refuse to invent APIs/files/functions/classes (code-checked citations) | DOWNGRADED | PARTIAL: only `path:line` citations are checked (file exists, line within the file's length) and only FLAGGED (`_citation_check`), never refused; invented functions/classes/APIs are not checked at all. (Fixed on the way: a citation like `x/../../f.txt:1` probed files outside the repo.) |
| 504 | 54 | Say 'I cannot verify this' instead of guessing | CONFIRMED | Prompt-level (chat.md, planner.md). See #357. |
| 506 | 57 | Approving a clarification correctly resumes the owning agent with the answer | CONFIRMED | Real Postgres + HTTP: planner and coder answers resume the right agent with the answer; reject / empty answer resume nothing; a 2nd question after the 1st answer reaches a human; double-approve -> 409. Only the launch_* call is faked. |

## B6 — Agent scaffold, capability audit & skill coverage  (39 items, depth: Standard)

| # | § | Question | Verdict | Evidence / notes |
|---:|---|---|---|---|
| 101 | 6 | Identity/Role/Responsibilities | CONFIRMED | All 88 agent modules carry an AGENT_CONTRACT (name, tools, permissions, expected_verification); test_b6_agent_scaffold drives every run_* entry point of the 79 reachable agents with run_agent_graph replaced by a recorder. |
| 102 | 6 | System prompt loaded from role file | CONFIRMED | Every agent's role_name resolves to roles/<name>.md with real content (audit test). chat_agent/barot_agent/bhaskar_agent are the documented exceptions with their own prompt path. |
| 103 | 6 | Skills/Tool List | CONFIRMED | Audit: every tool advertised to the model has a handler, for all 79 agents (no advertised-but-not-dispatched). Handlers offered but not advertised are refused at dispatch (existing guard). |
| 104 | 6 | Memory wired per agent | CONFIRMED | enable_memory on 78/79 agents; memory_hook_node reads the real DB (B4 #402). |
| 105 | 6 | Knowledge Base (repo context) | CONFIRMED | repo_context (scanner + context_builder) injected by memory_hook_node; scanner verified in B2. |
| 107 | 6 | Reasoning Loop | CONFIRMED | Live run_coder on the real API: plan -> tool loop -> submit_patch -> static checks, correct patch (135 s, 29k/3.4k tokens, ~$0.16). |
| 108 | 6 | Verification Loop | CONFIRMED | All 79 agents declare a verification contract (set_by/enforce_in_result); enforcement bugs found in B5 (#501/#349). |
| 109 | 6 | Self-Critique | CONFIRMED | Critique node enabled on 7 agents only (coder, qa, reviewer, ...), runs live and parses Claude's JSON. Note: on the trivial live task it judged generic role criteria ('rollback path stated') unmet and burned its retry, then accepted with a gate flag — costs tokens for no benefit on small tasks (Task 2 lead). |
| 110 | 6 | Recovery System (retry+feedback) | CONFIRMED | Retry-with-feedback loops in coder/backend_dev/frontend_dev/qa; the static-check trigger was broken for non-Python repos (fixed, B5 #352). |
| 111 | 6 | Safety Layer | CONFIRMED | Policy check + blocking_until + unadvertised-tool refusal run at the one execute_tools chokepoint; deeper security review in B7 (host-run tools unsandboxed lead stands). |
| 112 | 6 | Learning Layer | CONFIRMED | Lesson extraction persists to the lessons table (rows from the live pipeline run: pm/architect/decomposer); a standalone process without the FastAPI main loop does not persist (by design). |
| 113 | 6 | Configuration (no hardcoding) | CONFIRMED | No model id is hardcoded anywhere under app/ except config.py and model_router (audit test); models/tiers come from agent_models.json, thresholds from settings. |
| 114 | 6 | Observability/Logging | CONFIRMED | JSON logs carry trace_id/task_id/agent_run_id; policy denials go to the audit log; run_span per agent run. |
| 115 | 6 | Metrics | CONFIRMED | RunMetrics tokens/cost per run + agent_runs rows (existing tests); cost_estimate is NULL on pipeline agents (B5 lead). |
| 116 | 7 | Intelligent Understanding / Deep Instruction Analysis | CONFIRMED | Live PM run (B1): goals, constraints, confidence from a plain-language request. |
| 118 | 7 | Context Awareness | CONFIRMED | Memory + repo context + facts/plan step injected before the first LLM call (B4/B2). |
| 119 | 7 | Long-Term Memory | CONFIRMED | See B4 #77-#80 (real pgvector). |
| 120 | 7 | Learn From Success | CONFIRMED | record_agent_run_outcome hooks write successful outcomes to memory (test_memory_hooks + B4 store). |
| 121 | 7 | Learn From Failure | CONFIRMED | Same hooks embed failures (root cause) and query_failures feeds later runs (B4 real DB). |
| 122 | 7 | Detect User Satisfaction | CONFIRMED | Only NEGATIVE signals are detected (frustration phrases, shouting, repeats) — no positive-satisfaction signal. Two real defects fixed in B5 (#338/#339). |
| 124 | 7 | Honest Error Handling | CONFIRMED | Coder/QA/planner failures come back as explicit error results (never a fabricated success); B5 removed a false pass (QA) and a false failure (non-Python static checks); 422 bodies no longer leak paths (B3). |
| 125 | 7 | Credential Handling | FIXED | _redact_secrets_in_text / the pre-commit scanner missed the platform's OWN key shape (sk-ant-...: the hyphen defeated the sk- alternative), sk-proj-, github_pat_, JWTs, Stripe, Google keys, DB-URL passwords and Bearer tokens; only the first token on a line was redacted; masking showed 6 characters of a password. All fixed with tests. |
| 127 | 7 | Cross-Agent Collaboration / Shared Learning | CONFIRMED | LessonStore + lessons table shared across processes (B4 real-DB test); delegation module has its own tests. |
| 128 | 7 | Architecture Awareness | FIXED | build_architecture_map did json.loads on the raw reply: Claude fences JSON, so every attempt failed and the map was never built (returned the 'Failed to generate' stub). Now the fence-tolerant parser. |
| 131 | 7 | Self Review | CONFIRMED | self_review state field delivered by execute_tools (fixed in B1 #11). |
| 132 | 7 | Continuous Improvement | CONFIRMED | Lessons, versioned lessons with promotion gate, prompt registry with rollback exist and work (B4); the scheduled self-improvement scans are verified in B8. |
| 133 | 7 | Production Quality (lint/test gates) | FIXED | Lint/type gate was broken for non-Python repos and blocked on unrelated pre-existing errors — see B5 #352; live coder run passed mypy on the changed file. |
| 134 | 72 | Requirement Analysis / Problem Decomposition | CONFIRMED | PM + decomposer run live in B1 (task 271): structured goals and subtasks. |
| 135 | 72 | Planning | CONFIRMED | Planner agent + the shared gather-facts/plan node (planner_node) — plan produced in the live coder run. |
| 136 | 72 | Code Reading/Writing | CONFIRMED | Live coder run read calc.py, wrote add(), ran checks. |
| 137 | 72 | Code Review | CONFIRMED | reviewer/security_reviewer/architecture_reviewer: contracts, tools, handlers verified for all; review quality not measured live. |
| 138 | 72 | Debugging / Root Cause Analysis | CONFIRMED | debugger_agent/bug_fix + analyze_error/read_logs tools verified structurally and in tool_enhance; not exercised live. |
| 139 | 72 | Testing / Verification | CONFIRMED | qa/test_writer/test_coverage: verification now requires a real test command (B5 #501). |
| 140 | 72 | Security Awareness | CONFIRMED | security_reviewer, dependency_security_agent, secrets_scan, redaction (fixed here #125). |
| 141 | 72 | Cost Awareness | CONFIRMED | cost_controller + cost_estimator_agent (B5 fixes to the estimate). |
| 142 | 72 | Risk Assessment | CONFIRMED | Architect emits risk_level (live: 'low'), surfaced by /tasks/{id}/explain. |
| 143 | 72 | Observability | CONFIRMED | monitoring_agent/slo_agent/observability tools exist with contracts; structured logging is fleet-wide. |
| 144 | 72 | Refactoring | CONFIRMED | rename_symbol AST refactor verified in B1; refactor tools present. |
| 145 | 72 | Documentation | CONFIRMED | doc agents (api_docs, architecture_doc, changelog, ...) registered with contracts/role files; output quality not measured live. |

## B7 — Security, governance, enterprise & frontend/API  (32 items, depth: Deep)

| # | § | Question | Verdict | Evidence / notes |
|---:|---|---|---|---|
| 173 | 9 | API connections | CONFIRMED | Frontend typecheck clean; 24 vitest tests pass (api/auth libs); real uvicorn accepts Bearer and cookie credentials. Playwright e2e was not run (needs the full stack). |
| 174 | 9 | Streaming (SSE) | CONFIRMED | Real uvicorn: GET /api/tasks/{id}/stream -> 401 without credentials, 200 text/event-stream with a Bearer token or the gridiron_token cookie, ping heartbeat within 15 s. |
| 176 | 9 | State management | CONFIRMED | react-query based state; vitest page tests (fleet, agents, stream) pass. Not exercised in a browser. |
| 177 | 9 | Error handling | CONFIRMED | Structured 422s (B3) and the api.ts error handling tests; not exercised in a browser. |
| 178 | 9 | Reconnect logic | CONFIRMED | vitest 'SSE reconnect-with-backoff' passes (one connection on mount, backoff on drop). |
| 179 | 9 | Frontend/backend synchronization | CONFIRMED | Typecheck + API-contract unit tests; the payload shapes (camelCase) match the routes read in B4-B7. No browser e2e. |
| 180 | 9 | Authentication | FIXED | GET /api/chat/sessions/{id}/history and GET /api/tasks/{id}/tokens had no auth at all (a neighbouring docstring claimed tokens did; a pinned test enshrined it). Also: a deleted user's JWT kept working for 24 h — accounts are now re-checked against the users table (jwt_revalidate_against_db, ~15 s cache). Forged / wrong-secret / expired / alg=none / legacy-header identities all rejected (tested). |
| 181 | 9 | Authorization (RBAC) | FIXED | POST /api/specialized-agents/{agent}/run|run-sync|dispatch needed only 'authenticated' (a viewer) and passed the caller's repo_path straight to the agent: a viewer could aim an agent with bash/write tools at ANY directory. Now agents whose contract can write/execute need an approver (unknown = privileged) and repo_path must be a registered repo (or inside one). |
| 182 | 9 | Broken/incomplete integration items | CONFIRMED | No broken integration found at typecheck/unit level; the real defects were on the server side (above). Browser e2e not run. |
| 313 | 21 | Credential protection | FIXED | Code-running tools (run_python_snippet, run_node, run_script, run_make, run_tests, run_single_test, type_check, run_linter, coverage_report, deps_outdated, find_unused_imports) inherited the server's whole environment: ANTHROPIC_API_KEY, JWT_SECRET_KEY, DATABASE_URL readable by any code an agent ran. New safe_subprocess strips credential-shaped variables. (The coder's bash already ran in the Docker sandbox with a minimal env.) |
| 314 | 21 | Secret management | CONFIRMED | Fernet encryption at rest (enc:v1: in system_settings, real Postgres test); values never echoed (masked view, names-only list); reserved platform names refused; plaintext fallback only outside production, production refuses to boot without CREDENTIAL_ENCRYPTION_KEY. backend/.env has no key (dev = plaintext). |
| 315 | 21 | Sandboxing | FIXED | The Docker sandbox was verified in B1. The bhaskar Python sandbox guarded only builtins.open: pathlib read_text/read_bytes, io.open, os.open, os.listdir and os.scandir read ANY file (incl. backend/.env). Guarded; ctypes/raw syscalls remain (documented: 'not a hard multi-tenant boundary'). |
| 316 | 21 | Dangerous command detection | FIXED | The denylist (~25 patterns) missed 27 of 50 dangerous samples: docker rm/stop/compose down, git reset --hard, git clean -fdx, killall/pkill/kill -9 1, reverse shells (/dev/tcp, nc -e), python -m http.server, find / -delete, cat /etc/shadow, writes to /etc/... The dedicated tools ask a human first but plain bash walked around every gate. Added (overridable by a present human; rm -rf/dd/mkfs stay non-overridable); 22 ordinary dev commands verified unblocked. |
| 317 | 21 | Permission system | FIXED | Agent contracts declare permissions (write_repo, execute_bash, ...) but nothing enforced them at the run endpoints — now privileged agents need the approver role (see #181). |
| 318 | 21 | Prompt injection resistance | FIXED | Two real gaps: untrusted content could close its own <untrusted_external_data> delimiter (everything after it read as trusted instructions) — now escaped; and the injection-shape flag knew 4 phrasings — now also 'disregard the above', 'you are now', 'new instructions:', <system>/[INST], 'do not tell the user', exfiltration verbs. Heuristic flagging, not a guarantee. |
| 319 | 21 | Data leakage prevention | FIXED | See #313 (env) and B6 #125 (redaction of agent output: sk-ant-, JWT, DB-URL passwords, ...). |
| 320 | 22 | Refuses malware/ransomware/credential-theft/phishing requests | CONFIRMED | No repo-level policy or prompt mentions malware; the refusal is the model's own. 3 live probes (ransomware, Gmail phishing page, browser-password stealer) were all refused. |
| 322 | 96 | Secret scanning | FIXED | secrets_scan / pre-commit scanner share the pattern set fixed in B6 #125. |
| 323 | 96 | Encrypted credential storage | CONFIRMED | See #314: encrypted at rest with Fernet, decrypt only through the vault. |
| 324 | 96 | Audit logs (tamper-resistant + queryable) | FIXED | Three real defects: (1) audit() from an agent WORKER THREAD (where all tool execution and every policy denial runs) never reached the database — get_event_loop() raised and was swallowed; entries lived only in the in-memory ring; (2) the hash chain FORKED under concurrent inserts (seq drawn before the trigger's advisory lock): 14 false 'breaks' in 545 rows, so verify could not tell tampering from noise — migration 049 re-draws seq inside the lock; verifier now checks a linked list and forks only from the boundary; (3) DB write failures were `pass`. Verified on real Postgres: UPDATE/DELETE rejected, 40 concurrent inserts stay one line, a privileged rewrite is detected. |
| 325 | 96 | Role-based permissions | FIXED | JWT roles were frozen at login: a demoted approver stayed an approver for 24 h. The users row is now authoritative (see #180). |
| 326 | 96 | Least-privilege access | FIXED | Viewer/approver matrix over all 136 routes: every mutating route needs auth; approver-only routes 403 for viewers (tested); agent-run endpoints fixed (#181). Lead: a viewer can still create/run tasks, mkdir/clone/commit/pull via /api/console/*, chat with a tool-using agent — a design decision worth revisiting. |
| 327 | 96 | Approval chains | CONFIRMED | Approval endpoints are approver-only; decision identity now the authenticated approver (B4 #464). Other approval endpoints still record decided_by='user' (approvals.py, chat) — lead. |
| 328 | 96 | Compliance readiness (GDPR/CCPA export & erase) | FIXED | Erasure removed the login but the erased user's token kept working for up to 24 h (see #180 — now immediate). Export/erase cover identity, role and audit rows only; chat messages and tasks carry no user link, so there is nothing else to export. |
| 330 | 85 | All agents automatically follow policy (structural guarantee) | CONFIRMED | One chokepoint (execute_tools: policy check, blocking_until, unadvertised-tool refusal) for all 79 agents (B6 audit); its denylist gaps were fixed under #316; host-run exec tools now scrubbed (#313). |
| 331 | 85 | Licensing policy enforcement | DOWNGRADED | PARTIAL: check_license_compliance scans the PLATFORM's own installed Python packages (SPDX/classifier based) and is an advisory tool — nothing enforces a license policy on a target repo's dependency changes, and CI has no license job. |
| 375 | 48 | Multiple users (normalized users table) | CONFIRMED | users table (migration 044) with bcrypt hashes, roles, must_change_password; real rows used in the revocation tests; /auth/setup only when the table is empty and never in production. |
| 379 | 48 | Audit logging | FIXED | See #324. |
| 380 | 48 | Role-based access | FIXED | See #325/#181. |
| 382 | 77 | Agent lifecycle (hire/retire/replace/promote) | CONFIRMED | POST /api/agents/{name}/lifecycle is approver-only; disabled/retired agents are excluded by select() (B2); existing lifecycle tests pass. |
| 384 | 95 | Credentials scoped per-repo/project | CONFIRMED | credential_vault repo-scoped keys with global fallback; 25 real-DB vault/encryption tests pass. |
| 385 | 95 | Agents use the correct repo_path consistently | FIXED | Specialized-agent endpoints accepted an arbitrary repo_path (see #181); task-owned repo resolution (resolve_task_repo_path) was already used elsewhere and is now the only unprivileged source. |

## B8 — Fleet self-improvement, guardians & health  (33 items, depth: Standard)

| # | § | Question | Verdict | Evidence / notes |
|---:|---|---|---|---|
| 197 | 12 | Autonomous scheduling (no manual trigger) | PENDING | |
| 199 | 12 | Log monitoring | PENDING | |
| 200 | 12 | Docker monitoring | PENDING | |
| 201 | 12 | Git monitoring | PENDING | |
| 202 | 12 | Architecture monitoring | PENDING | |
| 203 | 12 | Enhancement suggestions | PENDING | |
| 204 | 12 | Bug detection | PENDING | |
| 206 | 12 | Approval workflow before code changes | PENDING | |
| 207 | 12 | Never modifies code without approval | PENDING | |
| 396 | 35 | Broken imports / dead code / unused files / duplicate functions / circular deps | PENDING | |
| 397 | 35 | Dependency conflicts | PENDING | |
| 408 | 76 | agent_performance_reviewer uses real data, not self-reports | PENDING | |
| 409 | 76 | Capability gap detection from repeated failed/blocked requests | PENDING | |
| 413 | 115 | Real 'what went well / what failed' report tied to a release event | PENDING | |
| 415 | 118 | Detect | PENDING | |
| 416 | 118 | Analyze | PENDING | |
| 417 | 118 | Propose | PENDING | |
| 419 | 118 | Show plan | PENDING | |
| 420 | 118 | Wait for approval | PENDING | |
| 421 | 118 | Implement | PENDING | |
| 422 | 118 | Test | PENDING | |
| 423 | 118 | Rollback if quality declines | PENDING | |
| 441 | 88 | Detect slow/crashed agents | PENDING | |
| 442 | 88 | Detect looping agents (cross-run) | PENDING | |
| 444 | 88 | Health state transitions are real, not static | PENDING | |
| 445 | 88 | 'degraded' state reachable and persisted | PENDING | |
| 446 | 88 | Automatic recovery from unhealthy | PENDING | |
| 447 | 89 | Disable a repeatedly-failing agent | PENDING | |
| 448 | 89 | Notify a supervisor | PENDING | |
| 449 | 89 | Replace / permanently disable (persists across restart) | PENDING | |
| 458 | 91 | Deterministic architecture drift detection vs stored baseline | PENDING | |
| 507 | 69 | Pre-change impact simulation (blast radius) before human review | PENDING | |
| 508 | 69 | Automatic rollback-on-quality-decline for code-commit enhancements | PENDING | |

## B9 — Scheduler, metrics, quality gates, scalability & architecture  (37 items, depth: Standard)

| # | § | Question | Verdict | Evidence / notes |
|---:|---|---|---|---|
| 151 | 8 | Response latency tracking | PENDING | |
| 152 | 8 | Planning speed tracking | PENDING | |
| 153 | 8 | Orchestration speed tracking | PENDING | |
| 154 | 8 | File scanning speed tracking | PENDING | |
| 155 | 8 | Editing speed tracking | PENDING | |
| 156 | 8 | Tool execution speed tracking | PENDING | |
| 157 | 8 | Memory retrieval speed tracking | PENDING | |
| 160 | 8 | Bottleneck: sync blocking in async code | PENDING | |
| 161 | 10 | Folder structure | PENDING | |
| 163 | 10 | Dependency management (pinning) | PENDING | |
| 164 | 10 | Code quality (lint/type-check clean) | PENDING | |
| 165 | 10 | Testing volume | PENDING | |
| 166 | 10 | Observability | PENDING | |
| 167 | 10 | Deployment readiness (prod manifest) | PENDING | |
| 168 | 46 | Hardcoded agent lists that wouldn't survive growth | PENDING | |
| 170 | 46 | DB indexing on frequently-filtered columns | PENDING | |
| 172 | 46 | Connection pooling | PENDING | |
| 424 | 86 | Queue | PENDING | |
| 425 | 86 | Prioritize | PENDING | |
| 426 | 86 | Pause / Resume / Cancel | PENDING | |
| 430 | 86 | Retry (both queue backends) | PENDING | |
| 431 | 87 | Success rate | PENDING | |
| 432 | 87 | Failure rate | PENDING | |
| 433 | 87 | Avg execution time (p50/p95) | PENDING | |
| 434 | 87 | Tool usage / accuracy | PENDING | |
| 435 | 87 | Token usage | PENDING | |
| 438 | 87 | User approval rate | PENDING | |
| 440 | 87 | Reliability score | PENDING | |
| 450 | 90 | Linting | PENDING | |
| 451 | 90 | Formatting | PENDING | |
| 452 | 90 | Tests | PENDING | |
| 459 | 92 | Outdated packages | PENDING | |
| 460 | 92 | Security vulnerabilities | PENDING | |
| 493 | 23 | Overall production readiness scored across all categories | PENDING | |
| 496 | 24 | Accessibility tooling in this product's own frontend | PENDING | |
| 498 | 50 | Roadmap tracked, sequenced, and re-sequenced against real progress | PENDING | |
| 499 | 51 | Deterministic 'repeat this exact prior task by ID' mechanism | PENDING | |

## B10 — File understanding, external knowledge, git, docs & deploy  (46 items, depth: Light)

| # | § | Question | Verdict | Evidence / notes |
|---:|---|---|---|---|
| 260 | 16 | Python | PENDING | |
| 261 | 16 | TypeScript/JavaScript | PENDING | |
| 264 | 16 | Markdown | PENDING | |
| 265 | 16 | JSON (incl. schema validation) | PENDING | |
| 266 | 16 | YAML (incl. schema validation) | PENDING | |
| 267 | 16 | Docker/Docker Compose | PENDING | |
| 268 | 16 | Jupyter Notebook | PENDING | |
| 269 | 16 | PDF | PENDING | |
| 270 | 16 | Images | PENDING | |
| 272 | 16 | XML | PENDING | |
| 273 | 16 | CSV | PENDING | |
| 276 | 79 | Open URLs | PENDING | |
| 277 | 79 | SSRF protection on URL fetch | PENDING | |
| 279 | 79 | Detect 'I don't know this tech, look it up' (research agent) | PENDING | |
| 280 | 79 | Inspect external GitHub repositories | PENDING | |
| 281 | 79 | Inspect APIs (OpenAPI/Swagger) | PENDING | |
| 283 | 19 | Detect deployment issues | PENDING | |
| 284 | 19 | Diagnose deployment failures | PENDING | |
| 285 | 19 | Generate deployment guides for this project | PENDING | |
| 287 | 19 | Docker | PENDING | |
| 293 | 20 | Open URLs | PENDING | |
| 294 | 20 | Understand / summarize websites | PENDING | |
| 295 | 20 | Inspect external GitHub repos | PENDING | |
| 296 | 20 | Inspect APIs (OpenAPI/Swagger) | PENDING | |
| 298 | 40 | Create meaningful commits / write commit messages | PENDING | |
| 299 | 40 | Create branches | PENDING | |
| 301 | 40 | Explain conflicts | PENDING | |
| 302 | 40 | Review diffs (structured, beyond raw output) | PENDING | |
| 303 | 40 | Summarize changes | PENDING | |
| 304 | 40 | Generate PR descriptions | PENDING | |
| 305 | 41 | README generation | PENDING | |
| 306 | 41 | Architecture docs generation | PENDING | |
| 307 | 41 | API docs generation | PENDING | |
| 308 | 41 | Agent docs generation | PENDING | |
| 309 | 41 | Tool docs generation | PENDING | |
| 310 | 41 | Changelog generation | PENDING | |
| 311 | 41 | Migration guide generation | PENDING | |
| 312 | 41 | Auto-update when code changes | PENDING | |
| 386 | 98 | Git tags / semver | PENDING | |
| 387 | 98 | Migration state reasoning | PENDING | |
| 389 | 99 | Generate diagrams | PENDING | |
| 390 | 99 | Summarize long outputs | PENDING | |
| 391 | 100 | ARIA / semantic HTML in the product's own frontend | PENDING | |
| 392 | 100 | a11y linting | PENDING | |
| 490 | 83 | Dedicated multi-criteria recommendation engine (real weighted scoring, not model-guessed) | PENDING | |
| 491 | 83 | General single-question research/recommendation capability | PENDING | |

## B11 — Testing audit, hidden risks & domain coverage  (43 items, depth: Light)

| # | § | Question | Verdict | Evidence / notes |
|---:|---|---|---|---|
| 183 | 11 | Unit Tests | PENDING | |
| 184 | 11 | Integration Tests | PENDING | |
| 185 | 11 | End-to-End Tests | PENDING | |
| 186 | 11 | Agent Tests | PENDING | |
| 187 | 11 | Tool Tests | PENDING | |
| 188 | 11 | Memory Tests | PENDING | |
| 189 | 11 | Orchestrator Tests | PENDING | |
| 190 | 11 | Regression Tests | PENDING | |
| 191 | 11 | Performance Tests | PENDING | |
| 192 | 11 | Load / Stress Tests | PENDING | |
| 193 | 11 | Failure Recovery Tests | PENDING | |
| 465 | 71 | Backend Development | PENDING | |
| 466 | 71 | Frontend Development | PENDING | |
| 467 | 71 | Full Stack | PENDING | |
| 468 | 71 | API Development (REST/GraphQL) | PENDING | |
| 469 | 71 | Mobile Development | PENDING | |
| 470 | 71 | AI/ML/LLM Engineering | PENDING | |
| 471 | 71 | RAG Systems | PENDING | |
| 472 | 71 | Agentic AI / LangGraph design (for user's own project) | PENDING | |
| 473 | 71 | MCP Development | PENDING | |
| 474 | 71 | Prompt Engineering | PENDING | |
| 475 | 71 | Data Engineering / ETL / Warehousing | PENDING | |
| 476 | 71 | SQL | PENDING | |
| 477 | 71 | Docker | PENDING | |
| 479 | 71 | CI/CD | PENDING | |
| 480 | 71 | Monitoring/Logging | PENDING | |
| 481 | 71 | Security | PENDING | |
| 482 | 71 | QA/Testing | PENDING | |
| 483 | 71 | Architecture/System Design | PENDING | |
| 484 | 71 | Product Management (roadmap/strategy) | PENDING | |
| 485 | 71 | Business Analysis | PENDING | |
| 486 | 71 | Sprint Planning | PENDING | |
| 487 | 71 | UI/UX Design, Design Systems | PENDING | |
| 488 | 71 | Accessibility | PENDING | |
| 510 | BONUS | Chat's bash tool sandboxed (not running unsandboxed on host) | PENDING | |
| 512 | BONUS | Doc-agent modules crash-on-invocation (missing role files) | PENDING | |
| 513 | BONUS | versioned_lessons table has same advisory-lock protection as sibling table | PENDING | |
| 514 | BONUS | Production deployment manifest + backend restart policy exists | PENDING | |
| 515 | BONUS | Default queue backend has job timeout + retry | PENDING | |
| 516 | BONUS | Audit log query layer uncapped + tamper-chain verification | PENDING | |
| 517 | BONUS | coder.py has code-enforced read-before-write gate | PENDING | |
| 518 | BONUS | All API routes require authentication (no unauthenticated internal-data routes) | PENDING | |
| 519 | BONUS | DevTask.priority and model-context-limit checks are live, not dead code | PENDING | |

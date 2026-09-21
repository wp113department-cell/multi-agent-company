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
| B3–B11 | 333 | 0 | 0 | 0 | 0 | 0 |

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
| 208 | 13 | Ask permission | PENDING | |
| 209 | 13 | Wait indefinitely for a response | PENDING | |
| 210 | 13 | Present options (multi-choice) | PENDING | |
| 211 | 13 | Recommend choices (structured field) | PENDING | |
| 214 | 39 | Delete a file gated | PENDING | |
| 215 | 39 | Overwrite an existing file gated | PENDING | |
| 216 | 39 | git push (incl. force) gated | PENDING | |
| 217 | 39 | git reset --hard gated | PENDING | |
| 218 | 39 | Dangerous bash command gated | PENDING | |
| 219 | 39 | undo_changes gated | PENDING | |
| 220 | 39 | DB migration gated | PENDING | |
| 221 | 39 | seed_database gated | PENDING | |
| 222 | 39 | Dependency upgrades gated | PENDING | |
| 224 | 39 | 'Don't ask again this session' option | PENDING | |
| 225 | 103 | Interrupt any agent mid-run | PENDING | |
| 226 | 103 | Resume with injected input | PENDING | |
| 228 | 14 | Pause | PENDING | |
| 229 | 14 | Resume | PENDING | |
| 230 | 14 | Cancel (distinct terminal state) | PENDING | |
| 231 | 14 | Retry | PENDING | |
| 232 | 14 | Rollback (manual operator-invoked) | PENDING | |
| 233 | 14 | Checkpoints (Postgres-backed, all paths) | PENDING | |
| 237 | 38 | Docker crashes (sandbox) - fails closed correctly | PENDING | |
| 239 | 38 | Terminal/shell session closes - detected live | PENDING | |
| 240 | 38 | Internet disconnects - retry/backoff | PENDING | |
| 241 | 38 | LLM API fails (rate limit/500/timeout) | PENDING | |
| 242 | 97 | Backup exists and is automated/scheduled | PENDING | |
| 243 | 97 | Auto-restart on crash | PENDING | |
| 244 | 102 | Run 30+ min / hours without being killed | PENDING | |
| 245 | 102 | Progress reporting | PENDING | |
| 247 | 66 | Retries | PENDING | |
| 248 | 66 | Exponential backoff | PENDING | |
| 249 | 66 | Circuit breakers | PENDING | |
| 250 | 66 | Timeout handling (incl. DB statement timeout) | PENDING | |
| 251 | 66 | Idempotency | PENDING | |
| 252 | 66 | Transaction safety | PENDING | |
| 253 | 66 | Structured error reporting | PENDING | |

## B4 — Memory & knowledge systems  (33 items, depth: Deep)

| # | § | Question | Verdict | Evidence / notes |
|---:|---|---|---|---|
| 73 | 5 | Working Memory | PENDING | |
| 74 | 5 | Session Memory | PENDING | |
| 75 | 5 | Shared Memory | PENDING | |
| 76 | 5 | Project Memory | PENDING | |
| 77 | 5 | Long-Term Memory | PENDING | |
| 78 | 5 | Procedural Memory | PENDING | |
| 79 | 5 | Failure Memory | PENDING | |
| 80 | 5 | Knowledge Memory | PENDING | |
| 81 | 5 | Where memory is stored (real DB schema) | PENDING | |
| 82 | 5 | How memory is updated | PENDING | |
| 83 | 5 | How memory is retrieved | PENDING | |
| 84 | 5 | How memory is synchronized (race-safe) | PENDING | |
| 85 | 5 | Memory survives restart | PENDING | |
| 86 | 5 | Memory shared between agents | PENDING | |
| 87 | 120 | Working Memory scoped to task, no overflow | PENDING | |
| 89 | 120 | Long-term memory promotion gate (draft->published) | PENDING | |
| 91 | 120 | Memory Retrieval targeted, not full dump | PENDING | |
| 92 | 120 | Automatic Memory Cleanup | PENDING | |
| 93 | 120 | Memory Prioritization | PENDING | |
| 94 | 120 | Token Optimization | PENDING | |
| 95 | 120 | Context Window Management (aggregate cap) | PENDING | |
| 96 | 120 | Memory Aging/Lifecycle | PENDING | |
| 97 | 120 | Shared Memory Synchronization (lock safety) | PENDING | |
| 99 | 120 | Memory Analytics | PENDING | |
| 400 | 37 | Agent routing score updates from real outcomes over time | PENDING | |
| 401 | 74 | Preferences recorded and retrieved as first-class memory | PENDING | |
| 402 | 75 | Central store consulted before starting work | PENDING | |
| 403 | 75 | Covers proven patterns/failed approaches/architecture decisions/templates | PENDING | |
| 404 | 75 | Covers known bugs as a distinct type | PENDING | |
| 406 | 75 | Knowledge validation before promotion | PENDING | |
| 410 | 110 | Prompt evolution (versioning + rollback, human & automatic) | PENDING | |
| 412 | 114 | Per-repo knowledge isolation | PENDING | |
| 464 | 93 | Draft->published promotion gate with real approver | PENDING | |

## B5 — Context, cost, confidence, intent & truthfulness  (33 items, depth: Standard)

| # | § | Question | Verdict | Evidence / notes |
|---:|---|---|---|---|
| 334 | 25 | Ask clarification questions before acting | PENDING | |
| 335 | 25 | Refuse to guess when info insufficient | PENDING | |
| 338 | 26 | Frustration detection changes behavior | PENDING | |
| 339 | 26 | Repetition detection changes behavior | PENDING | |
| 342 | 26 | Remains professional | PENDING | |
| 345 | 27 | Remember previous answers on re-dispatch | PENDING | |
| 349 | 29 | Check for existing implementation before building (enforced, not advisory) | PENDING | |
| 350 | 30 | Repo search/read files/understand architecture required before writing (enforced) | PENDING | |
| 352 | 30 | Static quality checks (mypy/ruff) | PENDING | |
| 353 | 42 | Pre-execution cost/token estimate | PENDING | |
| 354 | 42 | Recommend cheaper approaches | PENDING | |
| 355 | 43 | Every important answer has a confidence estimate | PENDING | |
| 356 | 43 | Distinguish verified facts from assumptions | PENDING | |
| 357 | 43 | Explicitly say 'I don't know' | PENDING | |
| 358 | 44 | Explain why this approach / agents / tools chosen | PENDING | |
| 359 | 44 | Structured decision-log/rationale field in DB | PENDING | |
| 360 | 45 | Context persists across app restart | PENDING | |
| 362 | 52 | Condensation trigger | PENDING | |
| 363 | 52 | Compression method (real summarization, not truncation) | PENDING | |
| 364 | 52 | Applied to chat_agent conversations too | PENDING | |
| 366 | 65 | Check against model's real context limit | PENDING | |
| 367 | 65 | Warn user when approaching limits | PENDING | |
| 368 | 101 | Token usage estimate | PENDING | |
| 369 | 101 | API cost estimate | PENDING | |
| 370 | 101 | Execution time estimate | PENDING | |
| 371 | 101 | Storage impact estimate | PENDING | |
| 372 | 101 | Compute requirements estimate | PENDING | |
| 489 | 73 | Detects professional role and adapts terminology/depth | PENDING | |
| 492 | 84 | Communicates what it can't do (real, code-enforced limitation classification) | PENDING | |
| 501 | 54 | Refuse to invent test/execution results | PENDING | |
| 502 | 54 | Refuse to invent APIs/files/functions/classes (code-checked citations) | PENDING | |
| 504 | 54 | Say 'I cannot verify this' instead of guessing | PENDING | |
| 506 | 57 | Approving a clarification correctly resumes the owning agent with the answer | PENDING | |

## B6 — Agent scaffold, capability audit & skill coverage  (39 items, depth: Standard)

| # | § | Question | Verdict | Evidence / notes |
|---:|---|---|---|---|
| 101 | 6 | Identity/Role/Responsibilities | PENDING | |
| 102 | 6 | System prompt loaded from role file | PENDING | |
| 103 | 6 | Skills/Tool List | PENDING | |
| 104 | 6 | Memory wired per agent | PENDING | |
| 105 | 6 | Knowledge Base (repo context) | PENDING | |
| 107 | 6 | Reasoning Loop | PENDING | |
| 108 | 6 | Verification Loop | PENDING | |
| 109 | 6 | Self-Critique | PENDING | |
| 110 | 6 | Recovery System (retry+feedback) | PENDING | |
| 111 | 6 | Safety Layer | PENDING | |
| 112 | 6 | Learning Layer | PENDING | |
| 113 | 6 | Configuration (no hardcoding) | PENDING | |
| 114 | 6 | Observability/Logging | PENDING | |
| 115 | 6 | Metrics | PENDING | |
| 116 | 7 | Intelligent Understanding / Deep Instruction Analysis | PENDING | |
| 118 | 7 | Context Awareness | PENDING | |
| 119 | 7 | Long-Term Memory | PENDING | |
| 120 | 7 | Learn From Success | PENDING | |
| 121 | 7 | Learn From Failure | PENDING | |
| 122 | 7 | Detect User Satisfaction | PENDING | |
| 124 | 7 | Honest Error Handling | PENDING | |
| 125 | 7 | Credential Handling | PENDING | |
| 127 | 7 | Cross-Agent Collaboration / Shared Learning | PENDING | |
| 128 | 7 | Architecture Awareness | PENDING | |
| 131 | 7 | Self Review | PENDING | |
| 132 | 7 | Continuous Improvement | PENDING | |
| 133 | 7 | Production Quality (lint/test gates) | PENDING | |
| 134 | 72 | Requirement Analysis / Problem Decomposition | PENDING | |
| 135 | 72 | Planning | PENDING | |
| 136 | 72 | Code Reading/Writing | PENDING | |
| 137 | 72 | Code Review | PENDING | |
| 138 | 72 | Debugging / Root Cause Analysis | PENDING | |
| 139 | 72 | Testing / Verification | PENDING | |
| 140 | 72 | Security Awareness | PENDING | |
| 141 | 72 | Cost Awareness | PENDING | |
| 142 | 72 | Risk Assessment | PENDING | |
| 143 | 72 | Observability | PENDING | |
| 144 | 72 | Refactoring | PENDING | |
| 145 | 72 | Documentation | PENDING | |

## B7 — Security, governance, enterprise & frontend/API  (32 items, depth: Deep)

| # | § | Question | Verdict | Evidence / notes |
|---:|---|---|---|---|
| 173 | 9 | API connections | PENDING | |
| 174 | 9 | Streaming (SSE) | PENDING | |
| 176 | 9 | State management | PENDING | |
| 177 | 9 | Error handling | PENDING | |
| 178 | 9 | Reconnect logic | PENDING | |
| 179 | 9 | Frontend/backend synchronization | PENDING | |
| 180 | 9 | Authentication | PENDING | |
| 181 | 9 | Authorization (RBAC) | PENDING | |
| 182 | 9 | Broken/incomplete integration items | PENDING | |
| 313 | 21 | Credential protection | PENDING | |
| 314 | 21 | Secret management | PENDING | |
| 315 | 21 | Sandboxing | PENDING | |
| 316 | 21 | Dangerous command detection | PENDING | |
| 317 | 21 | Permission system | PENDING | |
| 318 | 21 | Prompt injection resistance | PENDING | |
| 319 | 21 | Data leakage prevention | PENDING | |
| 320 | 22 | Refuses malware/ransomware/credential-theft/phishing requests | PENDING | |
| 322 | 96 | Secret scanning | PENDING | |
| 323 | 96 | Encrypted credential storage | PENDING | |
| 324 | 96 | Audit logs (tamper-resistant + queryable) | PENDING | |
| 325 | 96 | Role-based permissions | PENDING | |
| 326 | 96 | Least-privilege access | PENDING | |
| 327 | 96 | Approval chains | PENDING | |
| 328 | 96 | Compliance readiness (GDPR/CCPA export & erase) | PENDING | |
| 330 | 85 | All agents automatically follow policy (structural guarantee) | PENDING | |
| 331 | 85 | Licensing policy enforcement | PENDING | |
| 375 | 48 | Multiple users (normalized users table) | PENDING | |
| 379 | 48 | Audit logging | PENDING | |
| 380 | 48 | Role-based access | PENDING | |
| 382 | 77 | Agent lifecycle (hire/retire/replace/promote) | PENDING | |
| 384 | 95 | Credentials scoped per-repo/project | PENDING | |
| 385 | 95 | Agents use the correct repo_path consistently | PENDING | |

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

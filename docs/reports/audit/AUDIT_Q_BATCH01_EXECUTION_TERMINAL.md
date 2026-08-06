# Bhaskar's Questions Audit — Batch 1: Repository Execution, Terminal Intelligence, Multi-Terminal, Coding Workflow, Multi-File Ops

Covers §1, §17, §18, §58, §59 of `Bhaskar's_questions.md`. Evidence-only, file:line cited. No guessing — checkpoints with no evidence are marked NO / NOT FOUND.

---

## §1 Repository Execution

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Clones repo into user-selected folder | **YES** | `backend/app/services/git_service.py:92-106` `git_clone()`, real `asyncio.create_subprocess_exec("git","clone",...)`. Called from `backend/app/api/console.py:157-170`. Tested: `test_git_service.py`. |
| Every operation stays inside that cloned repo | **PARTIAL** | Path scoping is real (`_validate_workspace()` git_service.py:46-59, `assert_in_workspace()` workspace_service.py:24-31, `check_path_in_worktree()` in policy/engine.py using `realpath` to defeat symlink escapes) — but enforcement is per-handler, not a single interceptor. Every write-capable handler sampled does call it, but the design depends on each new handler remembering to. |
| Always uses "the repository's terminal" | **NO** | No `Terminal`/`ShellSession` class exists anywhere in `backend/app` (zero grep matches). At least 4 independent subprocess call sites (`git_service.py`, `tools.py`, `chat_agent.py`, `worktree.py`) with no shared abstraction. |
| Terminal/session manager | **PARTIAL** | `backend/app/fleet/bg_process_registry.py` is a real PID-keyed JSON registry with a lock, wired at startup (`main.py:619-621`), tested. But two *separate*, non-unified in-memory dicts also track processes (`chat_agent.py:522`, `tools.py:7957`) — not one manager. |
| Multiple terminals simultaneously | **PARTIAL** | Multiple background PIDs can coexist (dict-keyed), but there's no session/terminal concept to run multiple *interactive* shells in parallel. |
| Windows terminal support | **PARTIAL** | Real but incomplete by the code's own admission: `tools.py:76-90` comments state most of ~11 venv-activation call sites were POSIX-only until a partial Stage-4 fix. `sys.platform=="win32"` branches exist for venv activation, stream reading, and signal mapping (SIGKILL→SIGTERM), but coverage is narrow (only 6 files reference `sys.platform`). |
| Linux/Ubuntu support | **YES** | Primary/default path. `git_service.py` uses list-args (no `shell=True`) for git; other tools use `subprocess.run(shell=True)` on POSIX. |
| Docker terminal handling | **YES** | Two real implementations: (1) `chat_agent.py:2077-2093` `docker logs`/`docker exec` with `shlex.quote`; (2) `backend/app/policy/sandbox.py` runs agent bash commands inside `docker run --rm` with cgroup limits, fails closed if Docker unreachable. Tested: `test_sandbox.py`, `test_bash_sandbox_wiring.py`. |
| Venv activation | **YES** | `_venv_activate_snippet()` tools.py:94-108, degrades safely if `.venv` missing. |
| Safe shell execution (injection prevention) | **YES — Production Ready** | `backend/app/policy/engine.py` (326 lines): denylist for `rm -rf`/`sudo`/`dd if=`/fork bombs/credential exfil, `strict=True` mode rejects shell metacharacters, `check_command_stays_in_boundary()` blocks embedded `cd` escapes. Docstring documents 10 real iterated bug fixes. Tested: `test_policy.py`, `test_policy_v2.py`, `test_audit05_security_fixes.py`. |
| Execution pipeline trace | **PARTIAL — critical finding** | See below. |

### Critical finding: the interactive chat's `bash` tool is NOT Docker-sandboxed

Two divergent execution paths exist and are not unified:

1. **One-shot task agents + LangGraph Coder agent** (`tools.py::make_chat_handlers`/`make_coder_handlers`, ~32 call sites: `evaluation_agent.py`, `test_coverage_agent.py`, `devex_agent.py`, `coder.py`, etc.) → `_run_bash_command()` (tools.py:30-72) → routes through `policy/sandbox.py::run_sandboxed()` when `Settings.bash_sandbox_enabled` is true. **Sandboxed.**
2. **The interactive `ChatAgent`** (`backend/app/agents/chat_agent.py`) — the class backing the actual `/api/chat` SSE endpoint the user talks to — has its own `bash` tool (chat_agent.py:1258-1268) that calls `_run_subprocess()` (chat_agent.py:318-354) directly: plain `subprocess.run(shell=True)` on the host. Grep confirms **zero** occurrences of `run_sandboxed`/`_run_bash_command` in `chat_agent.py`. **Not sandboxed** — protection is only the regex denylist (`policy/engine.py`) plus a human confirmation prompt for commands `_is_dangerous_command()` flags.

`sandbox.py`'s own module docstring (lines 16-27) claims sandboxing is wired into "chat_agent's bash," but that phrase refers to `tools.py::make_chat_handlers()`, a different code path from the `ChatAgent` class. **The primary surface the user actually interacts with day-to-day runs shell commands unsandboxed on the host.** This is a real security-relevant architecture gap, not a documentation nit — the docstring's own claim is false for the interactive path.

**Production Enhancement Plan:** Route `chat_agent.py::_run_subprocess()` through the same `policy/sandbox.py::run_sandboxed()` path used by `_run_bash_command()`, gated by the same `Settings.bash_sandbox_enabled` flag, so there is exactly one sandboxing decision point instead of two divergent ones. Add a test that specifically exercises `ChatAgent`'s tool-execution node (not just `tools.py` handlers) to assert sandboxing is applied — the evidence gathering found no such test today.

---

## §17 Terminal Intelligence

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Monitor streaming output | **PARTIAL** | Real for background processes (`_read_stream_nonblocking()`, chat_agent.py:182-217, POSIX `fcntl` non-blocking read / Windows thread-join). Foreground `bash` blocks until exit — no streaming. |
| Detect completion | **YES** | `proc.poll()` for background; natural blocking return for foreground. |
| Detect failure | **PARTIAL** | Exit-code based only (`returncode != 0`). No output-pattern-based failure detection outside the dedicated error parser below. |
| Detect hanging processes | **PARTIAL** | Foreground: `subprocess.TimeoutExpired` handling present everywhere sampled. Background (`run_background`): **no active hang/timeout detection** — a stuck background process is only reaped on next app restart via orphan sweep. |
| Wait for commands to finish | **YES** | Both explicit modes exist: `bash` (waits, with timeout) and `run_background`+`read_output`+`kill_process` (fire-and-forget). |
| Parse generic logs | **YES** | `analyze_error()` tools.py:9386-9450 — parses Python tracebacks, maps exception types to remediation suggestions. |
| Parse Docker logs | **YES** | `_summarize_docker_log_patterns()` tools.py:141-170, keyword sets for errors/warnings/crashes (e.g. OOMKilled, SIGSEGV, exit 137). Tested: `test_stage4_tier3_docker_logs_structured_parsing.py`. |
| Parse test output (pytest/etc.) | **NO** | Raw stdout/stderr capture with truncation only. No regex for structured pass/fail counts (e.g. pytest's "`X passed, Y failed`" summary line). Exit code is the only signal used. |
| Parse compiler/type-checker output | **NO** | Same — raw passthrough, no structured diagnostic extraction for mypy/tsc/ruff output. |

---

## §58 Multi-Terminal & Parallel Execution

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Concurrent shell-session registry | **PARTIAL** | `bg_process_registry.py` is real (JSON + lock) but is a PID registry, not a session manager; not unified with the two separate in-memory dicts. |
| Concurrent command execution (fan-out) | **NO** | Zero matches for `asyncio.gather`/`TaskGroup` anywhere in `backend/app`. |
| Background vs foreground distinction | **YES** | See §17. |
| Task dependency handling between terminal jobs | **NO — not found.** | No code expresses one background job depending on another's completion. |
| Terminal monitoring, recovery, cleanup | **PARTIAL** | Orphan sweep at startup (`sweep_orphaned_processes()`, SIGTERM, tested) — but nothing monitors or recovers a hung/crashed background process *during* a running session, only at next restart. |

### Critical finding: async task queue infrastructure exists but is dead code on the real dispatch path

`backend/app/pipeline/queue_adapter.py` (real `asyncio.Queue` + worker pool) and `backend/app/queue/rq_adapter.py` (real Redis/RQ with retries) both exist and are tested, but **`queue_adapter.py`'s own docstring admits they are not wired into real task dispatch**. Every actual task-launch call site in `backend/app/api/tasks.py` (run/restart/approve/pipeline_approve/push — 6 confirmed usages) uses FastAPI's `BackgroundTasks.add_task()` instead: fire-and-forget, no retry, does not survive a process restart. This means task-level concurrency, retries, and durability all rest on infrastructure that isn't actually in the live request path — a scalability and reliability gap, not a missing-feature gap (the correct code exists, unused).

**Production Enhancement Plan:** Either (a) wire `api/tasks.py`'s 6 dispatch points through `RQQueueAdapter` (already implements retries) and delete `queue_adapter.py` if Redis is the intended durable path, or (b) if `BackgroundTasks` is being kept deliberately for simplicity, delete the unused `queue_adapter.py`/`rq_adapter.py` and document why — carrying two unused, fully-built queue backends alongside the real dispatch path is dead code that will mislead future audits (as it did this one).

---

## §18 Coding Workflow

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Create/edit/delete files | **YES** | `edit_file` (targeted single-match replace, tools.py:4250-4269/1545-1565), `write_file` (full overwrite, tools.py:4271-4282), `delete_file` (tools.py:2050). |
| Compare files | **YES** | `git diff` handler (tools.py:4284-4297) + generic file-diff tool (chat_agent.py:1540-1552). |
| Synchronize files | **NO — not found** | No dedicated cross-file synchronization tool found beyond `rename_symbol`'s incidental multi-file rewrite. |
| Refactor projects | **PARTIAL** | `rename_symbol` (`repo_tools/ast_engine.py:289-328`) does repo-wide rename via `Path.rglob` + regex `\bold\b` substitution. Real and wired (`chat_agent.py:2192-2195`, `make_refactor_agent_handlers`). **Caveat: text/regex-based despite living in `ast_engine.py`, not true AST-aware rewriting** — will also match identifier text inside strings/comments. |
| Preserve formatting | **YES** | `edit_file` is a substring replace on exact text — untouched code is byte-identical. `format_file` delegates to real `ruff format`/`black`/`prettier`. |
| Preserve comments | **YES** | Same mechanism as above. |
| Avoid restricted files | **YES — Production Ready** | `policy/engine.py:78-109` `_matches_path_rule()` blocks `.env*`, `secrets/**`, `*.pem/*.key`, `.github/workflows/`, `.git/`. Enforced as real guard clauses inside handlers (`tools.py:4252`, `1517-1536`, `1269`), not just described in a prompt — matches CLAUDE.md's claim. Tested: `test_policy.py`, `test_policy_v2.py`, `test_audit05_security_fixes.py`. |
| Obey repository rules | **PARTIAL** | Same policy engine, but enforcement point is inside each handler rather than a single interceptor in front of all tool calls — architecturally fragile (a new handler that forgets the check silently bypasses policy). Every handler sampled did call it correctly today. |

---

## §59 Multi-File Operations

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Read hundreds of files safely | **PARTIAL** | `read_files` (tools.py:1265-1282) silently truncates to the first 20 paths per call — no pagination, no explicit warning surfaced to the caller that truncation occurred beyond the tool's static description. |
| Edit hundreds of files | **PARTIAL** | Only `rename_symbol` touches an unbounded number of files in one call (no cap, no batching, synchronous loop over every match) — opposite risk from `read_files`: no safety valve on a wide blast-radius write operation. |
| Rename/move/delete files | **YES** | Dedicated distinct tools: `rename_file`, `move_file` (tools.py:7052), `copy_file`, `delete_file` (tools.py:2050). |
| Preserve formatting/comments across multi-file edits | **YES** | Same substring-replace mechanism, applies per-file inside `rename_symbol`'s loop. |
| Preserve architecture consistency | **NO — not found** | A read-only `architecture_reviewer` agent exists (`agents/architecture_reviewer.py`, has `import_graph`/`circular_dep_detect`/`call_graph` tools) but is not wired to run automatically after `rename_symbol` or any batch edit — confirmed via grep, zero references to it from `manager.py` or `pipeline/*.py`. Multi-file edits are purely mechanical with no post-edit coherence check. |

---

## Summary — Batch 1 (38 checkpoints)

- **YES:** 16
- **PARTIAL:** 17
- **NO / NOT FOUND:** 5

**Two findings worth flagging above the rest:**
1. The interactive chat's `bash` tool bypasses Docker sandboxing that the codebase's own docstrings claim is universal — a real gap between claimed and actual security posture on the primary user-facing path.
2. Two fully-built async task queues (asyncio + Redis/RQ, both tested) sit unused while the real dispatch path uses fire-and-forget `BackgroundTasks` — durability/retry infrastructure exists but isn't in the live path.

Neither finding was visible from filenames or prompts alone — both required tracing actual call graphs, consistent with the master audit prompt's "never rely on filenames" instruction.

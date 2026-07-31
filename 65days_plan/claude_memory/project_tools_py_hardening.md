---
name: project-tools-py-hardening
description: "Multi-round security hardening state of multi-agent-company/backend/app/agents/tools.py — what's fixed, what's knowingly still open"
metadata:
  node_type: memory
  type: project
  originSessionId: fd497604-c3bc-454e-b85d-b38b4dea39fe
  modified: 2026-07-28T09:30:19.108Z
---

`multi-agent-company/backend/app/agents/tools.py` (~11,500 lines, ~200 agent tool handlers) went through a multi-round security-hardening pass, initially prompted by a Claude.ai review of the file. Only this one file was touched across all rounds — no rewrites, targeted diffs only, each verified against real execution (real subprocess calls, real Docker containers spun up and torn down, not mocked assertions).

**Why:** The file defines tool handlers for a fleet of AI coding agents (a "chat" agent with full repo access plus several scoped agents like Docker/QA/migration agents). Several handlers built `shell=True` commands via unescaped f-string interpolation of agent-controlled input, or ran privileged operations (Docker exec, container creation) with no policy checks — real prompt-injection-to-shell-execution and container-escape risk if any agent processes untrusted content (PR text, scraped pages).

**Closed and verified this session:**
- Shell injection via unescaped interpolation in `run_tests`, `run_linter`, `run_single_test`, `coverage_report`, `type_check`, `format_file`, `organize_imports`, and a duplicate `run_tests_h` in `make_fleet_apply_handlers` — fixed with `shlex.quote()` plus a new `_shell_metachar_reason()` helper for multi-token `flags` fields that can't be quoted as a whole.
- `run_background` had zero policy validation before `subprocess.Popen(shell=True)` — added `check_command()`.
- `read_env_var_h` leaked raw secret values — added `_mask_secret_value()` (masks by name pattern KEY/SECRET/TOKEN/etc. or value shape sk-/AKIA/gh*_ /generic 20+ char tokens).
- `docker_exec` (both the chat-agent copy and the Docker-agent copy) ran arbitrary commands in any named container with no check — added `check_command()` plus a new `_docker_container_risk_reason()` that runs `docker inspect` and denies `--privileged`, `--pid=host`, dangerous `CapAdd`, or sensitive host mounts (fails closed if inspection fails). Verified against real `--privileged` and `-v /:/host` test containers.
- Container-*creation* escalation: the chat agent's `docker_compose("up")` could launch a container built from a `docker-compose.yml` the same agent had just written via `write_file` (no restriction on compose file paths), bypassing the exec-time guard entirely. Fixed by gating `up` behind `session.request_confirmation()`, matching the existing convention already used by `run_migration`/`seed_database`/`undo_changes` in this file (hard-blocks if no interactive session). All three paths (no-session, deny, approve) verified against real execution.

**Knowingly still open, named explicitly rather than silently left (as of when this memory was
written — the 65-day gap-closure plan's Days 5, 8-9 in `../PLAN.md` directly extended some of this;
check `../answers.md` for current status of each before assuming any item below is still true):**
- `run_background`'s `cwd` parameter is still an unvalidated agent-controlled override (same class of gap `bash()`'s own `cwd` already got fixed for, per its own code comment — SEC-05-006).
- `_mask_secret_value()` won't catch `DATABASE_URL`-style connection strings with embedded `user:pass@` — only matches by variable-name pattern or bare-token value shape.
- Both `check_command`'s denylist (`app/policy/engine.py`) and the new `_docker_container_risk_reason()` guard are lists of known-bad shapes, not a formal/complete threat model — e.g. `--cap-add=SYS_PTRACE` alone or `--net=host` aren't in the Docker guard's list.
- The other ~190 tools in this file beyond the ones this pass specifically traced were never audited.
- No test suite exists for any of this, as far as this session found. (Note: the gap-closure plan's
  Days 8-9 added `backend/app/policy/sandbox.py` — a real Docker-based sandbox wired into 3 of ~15
  arbitrary-command bash handlers, with its own test suite `tests/test_sandbox.py` — a materially
  different and more real mechanism than the denylist-only approach this memory describes. Read
  `../answers.md`'s current Q21 entry rather than assuming this memory's "still open" list is
  unchanged.)

**How to apply:** If asked to continue hardening this file, don't re-litigate what's already fixed above — check `../answers.md` and `../IMPLEMENTATION_PROGRESS.md` first for what the gap-closure plan has since changed, then pick up from whatever of the "still open" list above remains genuinely open. See [[feedback-verify-empirically]] for the testing discipline this work established.

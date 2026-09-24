"""bash tool — the standalone, cleanly-separable variants.

tool_enhance.md productionization pass, tool #1 (2026-08-15). This is the
FIRST real step of the giant `app/agents/tools.py` (14,694 lines) being
gradually modularized — per tool_enhance.md §7's own instruction ("Do NOT
move everything blindly in one operation... gradually become a modular
system") and §8 ("you MUST update all affected consumers... Produce an
explicit migration report").

Real investigation before this move: "bash" is not one tool. 15 separately-
defined `{"name": "bash", ...}` specs exist across the codebase, each
scoped to a different agent role with its own command allowlist. Of those
15, only 5 are self-contained (a dedicated tool-spec + allowlist + handler-
factory triplet, not bundled inside a larger multi-tool `make_X_handlers()`
function that also builds unrelated tools for that same agent):
  - test_runner (make_test_runner_bash_handler)
  - load_test (make_load_test_bash_handler)
  - dependency_audit (make_dependency_audit_bash_handler)
  - infra_dry_run (make_infra_dry_run_bash_handler)
  - scoped/fleet (make_scoped_bash_handler + _FLEET_BASH_TOOL)

Those 5 are what moved here. The other 10 bash variants (coder, QA, devops,
CI/CD, refactor, dependency-agent, migration, AI-engineer, cleanup, chat)
remain in app/agents/tools.py — each is defined inline inside a larger
handler-factory function that also builds that same agent's non-bash tools
(e.g. devops's `bash` closure lives inside make_devops_handlers() alongside
submit_health_report). Extracting those cleanly requires restructuring
those functions' shared closure state, a bigger, separate, real piece of
work — tracked here explicitly, not silently deferred: see
bhaskar_next/tool_enhance_tracking.md's own note against those 10 variants.

TOOL PATH MIGRATION REPORT
---------------------------
Tool: bash (5 of 15 variants — test_runner, load_test, dependency_audit,
      infra_dry_run, scoped/fleet)
Old path: backend/app/agents/tools.py
New path: backend/app/tools/execution/bash.py

Affected agents: test_runner-capable agents (via make_test_runner_bash_
  handler), load_test_agent, dependency_security_agent, infra_agent,
  agent_debugger, quality_auditor (the last two via make_scoped_bash_
  handler + _FLEET_BASH_TOOL).
Affected modules: app/agents/tools.py (now re-exports every moved name —
  see the compatibility-shim import block near the top of that file).
Affected registries: none — app.fleet.tool_manifest.TOOL_MANIFEST is keyed
  by tool NAME ("bash"), not by source file/import path, so manifest
  entries needed no change.
Affected tests: none required changes — every existing test imports these
  names via `from app.agents.tools import ...`, which still works
  (compatibility shim). New tests for this module import directly from
  `app.tools.execution.bash` instead, proving the new path itself works.

Old references found: every one of the 5 moved names had real callers in
  app/agents/tools.py itself (tool-list constants) and in the agent files
  listed above (importing directly from app.agents.tools).
Updated references: none needed updating — the compatibility shim in
  app/agents/tools.py preserves every `from app.agents.tools import X`
  call site verbatim. This is a deliberate, tracked shim (tool_enhance.md
  §9): owner = this productionization pass; reason = avoid a repo-wide
  mechanical edit across every agent file that imports these names, for a
  move that doesn't change behavior; migration target = agent files import
  directly from app.tools.execution.bash instead, at a later, separate
  pass; removal condition = once every real caller has been individually
  verified importing from the new path (tracked per-caller, not bulk).
Remaining old references: intentional (see above) — app/agents/tools.py's
  own re-export.

Runtime verification: PASS (see tests/test_bash_tool_execution.py —
  real subprocess execution through each of these 5 handlers via BOTH
  import paths, proving the shim is transparent, not just present).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from app.config import get_settings
from app.policy.engine import check_allowlisted_command, check_command

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared sandboxed-execution primitive — gap-closure Day 9 (answers.md Q21).
# Real, current count of callers (verified by reading every one, not
# assumed): chat_agent's `bash`, coder's `bash`, make_scoped_bash_handler
# below, agent_ai_engineer's `ae_bash`, and cleanup_agent's `cu_bash` — the
# latter two still live in app/agents/tools.py (bundled handlers, not moved
# here) and import this function back from here. See
# app/policy/sandbox.py's module docstring for the rollout-scope reasoning
# (why the other ~10 already-allowlist-scoped bash handlers aren't wired to
# this yet).
# ---------------------------------------------------------------------------


def _run_bash_command(
    command: str,
    cwd: str,
    *,
    timeout: int,
    extra_env: dict[str, str] | None = None,
    image: str | None = None,
    network: str | None = None,
    read_only: bool = False,
    on_output: Callable[[str, str], None] | None = None,
) -> tuple[str, str, int, bool]:
    """Returns (stdout, stderr, returncode, timed_out) regardless of which
    path ran the command — each call site keeps its own existing output
    formatting unchanged, only the execution primitive underneath it moves.

    Routes through the real Docker sandbox (app.policy.sandbox.run_sandboxed)
    when Settings.bash_sandbox_enabled is True (the default). Falls back to
    direct host subprocess execution ONLY when an operator has explicitly
    set BASH_SANDBOX_ENABLED=false — never silently, and never merely
    because Docker itself is unreachable (that raises
    SandboxUnavailableError inside run_sandboxed, surfaced here as a
    [SANDBOX UNAVAILABLE] result instead of a quiet fallback).

    image/network (tool_enhance.md productionization pass, bash tool,
    follow-up sandboxing-coverage extension, 2026-08-15): both pass straight
    through to run_sandboxed()'s own already-existing override parameters —
    None (the default, every pre-existing caller) means "use
    Settings.bash_sandbox_image/bash_sandbox_network", unchanged. The
    toolchain-needing variants (test_runner/qa/refactor/etc.) pass a real
    toolchain image; the DB-touching ones (test_runner/qa/refactor/
    migration) additionally pass network="host" — see
    docs/tool_productionization/bash.md for the full reasoning (Postgres is
    deliberately bound to 127.0.0.1 only in docker-compose.yml, unreachable
    from a bridge-network container; host.docker.internal routing was
    verified to reach the bridge gateway but NOT the loopback-only
    Postgres — network=host was the verified-working fix).

    on_output (T2-B9/#12, 2026-09-24) — passed straight through to
    run_sandboxed()'s own new streaming parameter on the sandboxed path,
    and given the same real, incremental treatment on the host-fallback
    path below (a plain `subprocess.Popen` + reader-thread, mirroring
    `app.policy.sandbox._run_streaming`'s exact shape) — an operator who
    has explicitly opted OUT of sandboxing should not silently lose live
    output too. None (the default) is the exact original buffered
    behavior on both paths, unchanged.
    """
    settings = get_settings()
    if settings.bash_sandbox_enabled:
        from app.policy.sandbox import SandboxUnavailableError, run_sandboxed

        try:
            result = run_sandboxed(
                command,
                cwd,
                timeout=timeout,
                env=extra_env,
                image=image,
                network=network,
                read_only=read_only,
                on_output=on_output,
            )
            return result.stdout, result.stderr, result.returncode, result.timed_out
        except SandboxUnavailableError as exc:
            return "", f"[SANDBOX UNAVAILABLE] {exc}", -1, False

    env = {**os.environ, **extra_env} if extra_env else None
    if on_output is not None:
        return _run_host_streaming(
            command, cwd, timeout=timeout, env=env, on_output=on_output
        )
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
            env=env,
        )
        return proc.stdout, proc.stderr, proc.returncode, False
    except subprocess.TimeoutExpired:
        return "", f"Command timed out after {timeout}s", -1, True


def _run_host_streaming(
    command: str,
    cwd: str,
    *,
    timeout: int,
    env: dict[str, str] | None,
    on_output: Callable[[str, str], None],
) -> tuple[str, str, int, bool]:
    """Host-process counterpart to app.policy.sandbox._run_streaming — same
    real, line-buffered incremental-read shape, for the explicit
    BASH_SANDBOX_ENABLED=false opt-out path. See that function's own
    docstring for the one honest limitation (a command's own stdout
    buffering when not attached to a real tty)."""
    import threading

    proc = subprocess.Popen(
        command,
        shell=True,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _reader(stream: Any, stream_name: str, sink: list[str]) -> None:
        try:
            for line in iter(stream.readline, ""):
                sink.append(line)
                try:
                    on_output(stream_name, line)
                except Exception:
                    logger.debug(
                        "on_output callback raised for host bash execution "
                        "(non-fatal)",
                        exc_info=True,
                    )
        finally:
            stream.close()

    t_stdout = threading.Thread(
        target=_reader, args=(proc.stdout, "stdout", stdout_lines), daemon=True
    )
    t_stderr = threading.Thread(
        target=_reader, args=(proc.stderr, "stderr", stderr_lines), daemon=True
    )
    t_stdout.start()
    t_stderr.start()

    try:
        returncode = proc.wait(timeout=timeout)
        t_stdout.join(timeout=5)
        t_stderr.join(timeout=5)
        return "".join(stdout_lines), "".join(stderr_lines), returncode, False
    except subprocess.TimeoutExpired:
        proc.kill()
        t_stdout.join(timeout=5)
        t_stderr.join(timeout=5)
        return "", f"Command timed out after {timeout}s", -1, True


# ---------------------------------------------------------------------------
# Shared test-runner bash — MASTER_AGENT_v2.md Phase 2.1 (Executor tier).
# Same allowlist-then-denylist pattern make_qa_handlers uses, scoped tighter
# (test commands only, no build/lint) and reused by any agent whose job
# requires reproducing a failure or verifying a fix by actually running a
# test — not duplicated per agent.
# ---------------------------------------------------------------------------

TEST_RUNNER_ALLOWED_PREFIXES = (
    "pytest",
    "python -m pytest",
    "python3 -m pytest",
    "npm test",
    "npx jest",
    "npx vitest",
)

TEST_RUNNER_BASH_TOOL: dict[str, Any] = {
    "name": "bash",
    "description": (
        "Run a test command to reproduce a failure or verify a fix. Allowed: "
        "pytest, npm test, npx jest/vitest. No write operations, no deploy commands."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Test command to run"},
        },
        "required": ["command"],
    },
}


def make_test_runner_bash_handler(
    worktree_path: str,
) -> Callable[[dict[str, Any]], str]:
    """Scoped bash handler for agents that only need to run tests (reproduce
    a failure, or verify a fix). Never raises — a command outside the
    allowlist returns a [POLICY DENIED] string, matching every other
    scoped-bash handler's own contract."""
    venv_bin = str(Path(sys.executable).parent)
    env_with_venv = os.environ.copy()
    env_with_venv["PATH"] = venv_bin + ":" + env_with_venv.get("PATH", "")

    def bash(inp: dict[str, Any]) -> str:
        cmd = str(inp["command"])
        policy = check_allowlisted_command(cmd, TEST_RUNNER_ALLOWED_PREFIXES)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        settings = get_settings()
        timeout = settings.bash_tool_timeout_seconds.get("test_runner", 120)
        # env_with_venv (host PATH prepended with the venv's bin dir) only
        # matters for the explicit-opt-out host-fallback path — a sandboxed
        # container has its own toolchain already on PATH (see
        # docker/bash-sandbox/Dockerfile) and would treat a host path as
        # simply not found, harmless but pointless to pass.
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd,
            worktree_path,
            timeout=timeout,
            extra_env=None if settings.bash_sandbox_enabled else env_with_venv,
            image=settings.bash_sandbox_toolchain_image,
            network=settings.bash_tool_sandbox_network.get("test_runner"),
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        out = (stdout + stderr)[:6000]
        return out if out else "(no output)"

    return bash


# ---------------------------------------------------------------------------
# Scoped load-test bash — MASTER_AGENT_v2.md Phase 2.1 (Executor tier).
# k6/locust only. Real load tests run long; this tool's job is letting the
# agent execute a short smoke run of the script it just wrote to confirm it
# actually runs against the target (catches syntax errors, wrong URLs,
# schema mismatches) — not to run the full-scale load test unattended.
# ---------------------------------------------------------------------------

LOAD_TEST_ALLOWED_PREFIXES = (
    "k6 run",
    "locust",
)

LOAD_TEST_BASH_TOOL: dict[str, Any] = {
    "name": "bash",
    "description": (
        "Run a k6 or Locust load test script — use this for a short smoke run "
        "(low duration/VU flags) to confirm the script actually executes against "
        "the target before handing it off, not to run the full-scale load test. "
        "Allowed: k6 run, locust. No write operations, no deploy commands."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "k6/locust command to run"},
        },
        "required": ["command"],
    },
}


def make_load_test_bash_handler(repo_path: str) -> Callable[[dict[str, Any]], str]:
    """Scoped bash handler for load_test_agent — same allowlist-then-denylist
    pattern as make_test_runner_bash_handler, scoped to k6/locust instead of
    pytest/npm. A missing k6/locust binary is reported as command output
    (non-zero exit + stderr), not an exception — the agent can see and
    report that the tool isn't installed rather than the run crashing."""

    def bash(inp: dict[str, Any]) -> str:
        cmd = str(inp["command"])
        policy = check_allowlisted_command(cmd, LOAD_TEST_ALLOWED_PREFIXES)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        settings = get_settings()
        timeout = settings.bash_tool_timeout_seconds.get("load_test", 120)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd,
            repo_path,
            timeout=timeout,
            image=settings.bash_sandbox_toolchain_image,
            network=settings.bash_tool_sandbox_network.get("load_test"),
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        out = (stdout + stderr)[:6000]
        return out if out else "(no output)"

    return bash


# ---------------------------------------------------------------------------
# Scoped dependency-audit bash — gap-closure Day 7 (answers.md Q92).
# roles/dependency_security_agent.md has always claimed "using LIVE audit
# tooling only" / "never relies on training-data CVE recall", but the agent
# had no tool capable of actually running one — every prior CVE claim was
# necessarily the model's own (possibly stale, possibly invented) training
# knowledge with no live tool call behind it. Same allowlist-then-denylist
# pattern as make_test_runner_bash_handler/make_load_test_bash_handler,
# scoped to pip-audit/npm audit only.
# ---------------------------------------------------------------------------

DEPENDENCY_AUDIT_ALLOWED_PREFIXES = (
    "pip-audit",
    "pip_audit",
    "python -m pip_audit",
    "python3 -m pip_audit",
    "npm audit",
)

DEPENDENCY_AUDIT_BASH_TOOL: dict[str, Any] = {
    "name": "bash",
    "description": (
        "Run a live dependency-vulnerability audit. Allowed: pip-audit (Python, "
        "requirements.txt), npm audit (Node, package.json). Must be called at "
        "least once before reporting any CVE — a finding not backed by this "
        "run's real tool output is not a verified finding. No write operations."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "pip-audit/npm audit command to run",
            },
        },
        "required": ["command"],
    },
}


def make_dependency_audit_bash_handler(
    repo_path: str,
) -> Callable[[dict[str, Any]], str]:
    """Scoped bash handler for dependency_security_agent — the one real tool
    call its role prompt's "LIVE audit tooling only" promise depends on."""

    def bash(inp: dict[str, Any]) -> str:
        cmd = str(inp["command"])
        policy = check_allowlisted_command(cmd, DEPENDENCY_AUDIT_ALLOWED_PREFIXES)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        settings = get_settings()
        timeout = settings.bash_tool_timeout_seconds.get("dependency_audit", 120)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd,
            repo_path,
            timeout=timeout,
            image=settings.bash_sandbox_toolchain_image,
            network=settings.bash_tool_sandbox_network.get("dependency_audit"),
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        out = (stdout + stderr)[:6000]
        return out if out else "(no output — no known vulnerabilities found)"

    return bash


# ---------------------------------------------------------------------------
# Scoped infra dry-run bash — MASTER_AGENT_v2.md Phase 2.1 (Executor tier).
# Validate/lint/build only — no apply, no deploy, no push. This is the exact
# boundary the spec calls for: "must be able to apply and verify an infra
# change in a sandboxed/dry-run mode at minimum" — dry-run, not apply.
#
# terraform and kubectl are deliberately absent from this allowlist: both
# are already unconditionally blocked for every agent in the fleet by
# app/policy/engine.py's own _DENIED_COMMAND_PATTERNS (r"\bterraform\b",
# r"\bkubectl\b" — verified directly, no dry-run/plan carve-out exists
# there). That is a real, existing, fleet-wide security boundary this tool
# does not override — building a carve-out into the shared denylist is a
# separate, security-sensitive change that deserves its own review, not
# something to fold silently into per-agent tool provisioning. Scoped to
# what's actually real today: docker build (validates a Dockerfile builds),
# docker-compose config (validates compose file syntax/interpolation), helm
# template/lint (validates a chart renders/lints without installing it).
# ---------------------------------------------------------------------------

INFRA_DRY_RUN_ALLOWED_PREFIXES = (
    "docker build",
    "docker-compose config",
    "helm template",
    "helm lint",
)

INFRA_DRY_RUN_BASH_TOOL: dict[str, Any] = {
    "name": "bash",
    "description": (
        "Run an infrastructure validation command in dry-run/lint mode only. "
        "Allowed: docker build, docker-compose config, helm template, helm lint. "
        "terraform and kubectl are not available here — they are blocked fleet-wide "
        "by policy, with no dry-run exception. Never deploy, push, or otherwise "
        "change live infrastructure."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Dry-run/plan/validate command to run",
            },
        },
        "required": ["command"],
    },
}


def make_infra_dry_run_bash_handler(repo_path: str) -> Callable[[dict[str, Any]], str]:
    """Scoped bash handler for infra_agent — same allowlist-then-denylist
    pattern as the other scoped-bash handlers, restricted to plan/validate/
    lint commands. A missing terraform/docker/kubectl/helm binary is
    reported as command output, not an exception.

    tool_enhance.md productionization pass (bash tool, 2026-08-15) — the
    ONE remaining deliberately-unsandboxed variant, of the original 10.
    Every other previously-unsandboxed variant now routes through
    _run_bash_command with a real, verified toolchain image (see
    docs/tool_productionization/bash.md). This one does not, and the
    reason is categorically different from "we haven't gotten to it yet":
    `docker build`/`docker-compose config` need the Docker DAEMON itself,
    which a sandboxed container cannot provide without either Docker-in-
    Docker (a real, separate isolation/complexity increase) or mounting
    the host's docker.sock into the container (which grants root-equivalent
    host control — categorically worse than the "unsandboxed but tightly
    allowlisted, dry-run/validate-only" status quo this variant already
    has). Unlike the network=host tradeoff accepted for test_runner/qa/
    refactor/migration (a narrower, well-understood isolation reduction
    for tools whose commands are otherwise fully contained), sandboxing
    this variant correctly would require a materially different, riskier
    architecture decision — not made in this pass. Stays on raw host
    subprocess execution, protected by the same allowlist+denylist checks
    every variant has."""

    def bash(inp: dict[str, Any]) -> str:
        cmd = str(inp["command"])
        policy = check_allowlisted_command(cmd, INFRA_DRY_RUN_ALLOWED_PREFIXES)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        timeout = get_settings().bash_tool_timeout_seconds.get("infra_dry_run", 120)
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=timeout,
            )
            out = (result.stdout + result.stderr)[:6000]
            return out if out else "(no output)"
        except subprocess.TimeoutExpired:
            return f"[ERROR] Command timed out after {timeout}s"

    return bash


# ---------------------------------------------------------------------------
# Shared scoped-bash for fleet-governance agents (agent_debugger,
# quality_auditor) — denylist-only (check_command, no fixed prefix
# allowlist), since these agents' diagnostic needs are too varied for a
# fixed prefix list (git log/blame, ps, grep, ad-hoc lint/typecheck runs).
# ---------------------------------------------------------------------------

_FLEET_BASH_TOOL: dict[str, Any] = {
    "name": "bash",
    "description": "Run a diagnostic or check command (git log/blame/status, ps, grep, test/lint runners). Scoped by the same command-allowlist guardrail every bash-using agent uses — destructive/deploy commands are blocked regardless of role.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string", "description": "Command to run"}},
        "required": ["command"],
    },
}


def make_scoped_bash_handler(
    repo_path: str, *, read_only: bool = False
) -> Callable[[dict[str, Any]], str]:
    """Shared scoped-bash handler for fleet agents — check_command() guardrail,
    same pattern every other bash-using agent already follows."""

    def bash_h(inp: dict[str, Any]) -> str:
        cmd = str(inp["command"])
        policy = check_command(cmd)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        timeout = get_settings().bash_tool_timeout_seconds.get("scoped", 60)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd, repo_path, timeout=timeout, read_only=read_only
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        out = (stdout + stderr)[:4000]
        return out if out else "(no output)"

    return bash_h

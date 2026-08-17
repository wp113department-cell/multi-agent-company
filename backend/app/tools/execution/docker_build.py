"""docker_build tool — tool_enhance.md productionization pass, tool #18
(2026-08-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: docker_build
Old path: app/agents/tools.py (`_DOCKER_BUILD_TOOL` schema dict; the
    validation logic below did not exist anywhere before this pass)
New path: app/tools/execution/docker_build.py (this file) —
    `DOCKER_BUILD_TOOL`, `validate_docker_build_inputs`.
Affected agents: 2 per tool_inventory.json — `docker_agent` (via
    `dk_docker_build`) and every agent built on `make_chat_handlers()`
    that declares `docker_build`, plus `chat_agent`'s own interactive
    dispatch.
Affected modules: app/agents/tools.py (schema re-export;
    `dk_docker_build` and `docker_build_h` both now call the shared
    validator before building their command — their own, real,
    intentionally-different output formatting is otherwise untouched),
    app/agents/chat_agent.py (its real dispatch now calls the shared
    validator before building its command).
Affected registries: none — app/fleet/tool_manifest.py's "docker_build"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["docker_build"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_docker_build_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/docker_build.md.

Design note: unlike write_file/edit_file/run_tests (tools #12/#13/#16),
this pass shares only the VALIDATOR, not a full execution handler — the
3 real implementations have genuinely different, real output-formatting
behavior (`dk_docker_build`'s "Build succeeded/FAILED:\n..." wrapper vs.
`docker_build_h`'s raw output + `[exit N]` suffix vs. `chat_agent.py`'s
raw `_run_subprocess` passthrough) that isn't worth risking to unify for
a security fix, matching the same "validator, not full handler" pattern
established for `run_migration`/`seed_database`/`git_reset` in the
high-risk tier.
---------------------------------------------------------------------------

Real finding (severe — a proven, live host-file-exfiltration primitive):
ALL 3 implementations built their `docker build` command from
`context`/`dockerfile` (both LLM-controlled) with ZERO worktree-boundary
validation — the same class of bug already found and fixed for file
operations in tool #11, just never checked for this tool. Proved
directly: a real `docker build` with `context` set to an absolute path
completely outside the target repo (`/tmp/...`) succeeded, and a file
from that outside directory was extracted from the resulting image —
confirming a real, working arbitrary-host-file-read-and-exfiltrate chain
(any file the docker daemon's build context upload can read gets baked
into an image the LLM can then reference, run, or instruct the user to
push to a registry).
"""

from __future__ import annotations

from app.policy.engine import check_path_in_worktree

DOCKER_BUILD_TOOL = {
    "name": "docker_build",
    "description": "Build a Docker image from a Dockerfile. Runs `docker build -t <tag> <context>`.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tag": {"type": "string", "description": "Image tag, e.g. 'myapp:latest'"},
            "context": {
                "type": "string",
                "description": "Build context directory (default: repo root)",
            },
            "dockerfile": {
                "type": "string",
                "description": "Path to Dockerfile (optional, uses Docker default)",
            },
        },
        "required": ["tag"],
    },
}


def validate_docker_build_inputs(
    context: str, dockerfile: str | None, worktree_path: str
) -> str | None:
    """Returns a denial reason if `context` or `dockerfile` would resolve
    outside `worktree_path`, else None. Both default to "inside the repo"
    when omitted/`"."`, so only a real, non-default value is checked —
    matching every other validator in this initiative (fail-closed on the
    dangerous input, not on the common case)."""
    if context and context != ".":
        result = check_path_in_worktree(context, worktree_path)
        if not result.allowed:
            return f"context: {result.reason}"
    if dockerfile:
        result = check_path_in_worktree(dockerfile, worktree_path)
        if not result.allowed:
            return f"dockerfile: {result.reason}"
    return None

# Tool #18 — `docker_build` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three implementations:

1. `chat_agent.py`'s real interactive dispatch — `tag`/`context`/
   `dockerfile` build a `docker build` command; each individual arg was
   already `shlex.quote()`'d, so no shell-injection surface.
2. `make_docker_agent_handlers()`'s `dk_docker_build` — used by
   `docker_agent`, list-args `subprocess.run` (no `shell=True`), also no
   shell-injection surface.
3. `make_chat_handlers()`'s own `docker_build_h` — reachable by any agent
   built on the shared factory, same list-args shape.

## Problems found (real, empirically verified — severe: a proven,
live host-file exfiltration primitive)

**None of the 3 implementations validated `context` or `dockerfile`
stayed inside the repo.** `docker build -t <tag> -f <dockerfile>
<context>` uploads the entire `context` directory to the Docker daemon
as the build context, and any file referenced there (via `COPY`/`ADD` in
the Dockerfile) gets baked into the resulting image. Proved directly,
before writing any fix:

```python
result = await agent._execute_tool("docker_build", {
    "tag": "...",
    "context": "/tmp/td_docker_outside_context",  # absolute, outside the repo
})
```

with a Dockerfile at that path (`FROM scratch` + `COPY secret.txt
/leaked.txt`) — the build **succeeded**, and extracting `/leaked.txt`
from the resulting image returned the real, outside-repo file's content
verbatim. This is a real, working chain: any file the docker daemon's
build-context upload can read (bounded only by host filesystem
permissions, not by the repo boundary at all) can be baked into an image
the LLM can then run, inspect, or instruct the user to push to a
registry — a genuine exfiltration primitive, not a theoretical one.

This is the same root-cause class already found and fixed for file
operations in tool #11 (`root / rel` / an unvalidated path escaping the
intended worktree) — just never checked for this tool specifically.

## Changes made

- **`app/tools/execution/docker_build.py`** (new): `DOCKER_BUILD_TOOL`
  (schema, unchanged — single canonical copy, was already shared across
  2 tool lists) and `validate_docker_build_inputs(context, dockerfile,
  worktree_path)` — the shared chokepoint, using the same
  `check_path_in_worktree` mechanism established in tool #9. Only checks
  a real, non-default value (`context != "."`, `dockerfile` truthy),
  matching the fail-closed-on-the-dangerous-input pattern used
  throughout this initiative.
- **`app/agents/chat_agent.py`**, **`app/agents/tools.py`** (both
  `dk_docker_build` and `docker_build_h`): all 3 real call sites now call
  the shared validator before building their command. Each site's own,
  real, distinct output-formatting behavior (`dk_docker_build`'s "Build
  succeeded/FAILED:\n..." wrapper vs. `docker_build_h`'s raw output +
  `[exit N]` suffix vs. `chat_agent.py`'s raw passthrough) was
  deliberately left untouched — this pass shares only the validator, the
  same "validator, not full handler" pattern used for
  `run_migration`/`seed_database`/`git_reset` in the high-risk tier,
  since unifying 3 genuinely different output shapes wasn't worth the
  risk for a security fix.

## Tests (real, not mocked at the mechanism level — real `docker build`
execution, images cleaned up after each test; skipped if no `docker`
binary is available)

`tests/test_docker_build_hardening.py` (new, 11 tests):

- Schema shape check.
- Pure validator tests: default context/no dockerfile allowed, a real
  relative in-repo context/dockerfile allowed, an absolute
  outside-repo context rejected, a `../` traversal rejected, an absolute
  outside-repo dockerfile rejected.
- **The exact proven exploit, run for real against all 3 implementations
  and confirmed closed**: a real `docker build` attempt with an
  absolute, outside-repo context (containing the same
  `COPY secret.txt /leaked.txt` Dockerfile used to prove the bug) is
  rejected before `docker build` ever runs.
- Regression: a real, legitimate in-repo build (no `context`/
  `dockerfile` override) still succeeds, verified via `docker image
  inspect` that the image genuinely exists — not just that no error was
  returned.

## Regression

Targeted sweep (new test file + audit_q_batch07/day1/day2_agents/
executor_tier_bash/phase4 tests): **270 passed.** Full suite re-run after
this pass — see `tool_enhance_tracking.md`'s row for this tool for the
final count.

## Final verdict

**GREEN FLAG.**

A real, severe, proven exfiltration primitive closed with a shared,
already-established validation mechanism. No functionality lost: a real,
legitimate in-repo `docker build` was verified to still work end-to-end,
not just "no error returned."

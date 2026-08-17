# Tool #20 — `docker_exec` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three implementations:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_docker_agent_handlers()`'s `dk_docker_exec`.
3. `make_chat_handlers()`'s own `docker_exec`.

## Problems found (real, empirically verified — severe: chat_agent.py's
real dispatch had THREE gaps at once, none present in tools.py's own two
implementations of the same tool)

**1. Shell injection via `container`** (same bug class as tools
#8/#16/#18/#19): only `command` was `shlex.quote()`'d —

```python
f"docker exec {de_container} sh -c {_shlex.quote(de_command)} 2>&1"
```

— `de_container` was interpolated raw. Proved directly: a `container`
value of `"x; touch /tmp/PWNED...; echo "` created a real marker file on
the host.

**2. No container risk-inspection at all.** Both `dk_docker_exec` and
`make_chat_handlers`'s `docker_exec` already call
`_docker_container_risk_reason(container)` — a real check (`docker
inspect`) that rejects exec into a container running `--privileged`,
sharing the host PID namespace, holding dangerous added capabilities, or
bind-mounting a sensitive host path. `chat_agent.py`'s real,
**interactive** dispatch — the one actually reached by the main chat
agent — never had this wired in. A genuine host-escape surface: the live
agent could `docker exec` into a privileged or host-mounted container
with zero warning.

**3. No destructive-command check.** `make_chat_handlers`'s own
implementation already runs `command` through `check_command()` (the
centralized policy-engine denylist); `chat_agent.py`'s dispatch had no
command filtering of any kind.

All three gaps existed only in the interactive dispatch — both tools.py
implementations of this exact tool were already correct on every count.

## Changes made

- **`app/tools/execution/docker_exec.py`** (new): `DOCKER_EXEC_TOOL`
  (schema, unchanged) and `build_docker_exec_command(container, command)`
  — quotes both arguments (previously only `command` was), same
  per-argument-quoting approach already established for
  `docker_build`/`docker_compose` (tools #18/#19).
- **`app/agents/chat_agent.py`**: its real dispatch now runs `command`
  through `check_command()` and `container` through
  `_docker_container_risk_reason()` — both already-existing, already-
  proven functions, reused rather than reinvented — before building the
  command via the shared, safely-quoting builder.

**Deliberately left untouched**: both tools.py implementations — already
correct on every count that mattered here.

## Tests (real, not mocked at the mechanism level — real docker
execution; skipped if no `docker` binary; the "real container" test
skips if no container happens to be running)

`tests/test_docker_exec_hardening.py` (new, 7 tests):

- Schema shape check.
- Pure builder tests: a malicious container name and a malicious command
  both come back correctly quoted (round-tripped through `shlex.split`
  to confirm each survives as one literal token).
- **All three proven gaps, verified closed against the real dispatch**:
  shell injection via `container` rejected, a destructive command (`rm
  -rf /`) rejected, and — a genuinely useful side effect of the risk
  check — an uninspectable/nonexistent container fails closed (rejected,
  not silently allowed), which also independently closes the injection
  path even where quoting alone might not have been obvious.
- Regression: a real command executed inside a real running container
  (reuses whatever container happens to be running in the dev
  environment, e.g. `gridiron-postgres`) returns its real output.

## Regression

Targeted sweep (new test file + docker_build/docker_compose hardening +
audit_q_batch07/batch11 policy chokepoint tests/chat_tools/day2_agents/
phase4): **278 passed.** Full suite re-run after this pass — see
`tool_enhance_tracking.md`'s row for this tool for the final count.

## Final verdict

**GREEN FLAG.**

Three real gaps in the live, interactive dispatch — all already solved
correctly in sibling implementations of the same tool — closed by
reusing what already existed rather than writing anything new. No
functionality lost: a real command in a real container still executes
and returns real output.

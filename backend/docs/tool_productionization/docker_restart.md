# Tool #21 — `docker_restart` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three implementations:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_docker_agent_handlers()`'s `dk_docker_restart`.
3. `make_chat_handlers()`'s own `docker_restart_h`.

## Problems found (real, empirically verified — same bug class as tools
#8/#16/#18/#19/#20)

**Shell injection via `container`.** `chat_agent.py`'s real dispatch:

```python
drst_cmd = f"docker restart {drst_name} 2>&1"
```

— zero quoting. Proved directly: a `container` value of
`"x; touch /tmp/PWNED...; echo "` created a real marker file on the
host, completely outside the intended `docker restart` invocation.

**Both tools.py implementations were already safe** — list-args
`subprocess.run(["docker", "restart", container], ...)`, no `shell=True`,
so `container` never needed quoting there.

Unlike `docker_exec` (tool #20), this tool has no `command` field and
isn't a code-execution primitive, so `_docker_container_risk_reason`'s
exec-into-a-privileged-container concern doesn't carry over the same
way — restarting a container isn't itself a way to run arbitrary code
inside it.

## Changes made

- **`app/tools/execution/docker_restart.py`** (new): `DOCKER_RESTART_TOOL`
  (schema, unchanged) and `build_docker_restart_command(container)` —
  `shlex.quote()`'s the container name, same per-argument-quoting
  approach already established for `docker_build`/`docker_compose`/
  `docker_exec` (tools #18/#19/#20).
- **`app/agents/chat_agent.py`**: its real dispatch now calls the shared
  builder instead of the vulnerable inline interpolation.

**Deliberately left untouched**: both tools.py implementations — already
safe, no change needed.

## Tests (real, not mocked at the mechanism level — real docker
execution; skipped if no `docker` binary)

`tests/test_docker_restart_hardening.py` (new, 4 tests):

- Schema shape check.
- Pure builder test: a malicious container name comes back correctly
  quoted (round-tripped through `shlex.split`).
- **The proven exploit, verified closed**: shell injection via
  `container` rejected against the real dispatch (docker itself reports
  "No such container" for the full quoted payload — proof it was treated
  as one literal name, not executed).
- Regression: a real `docker restart` against a **disposable container
  this test creates and removes itself** (never touches real,
  already-running infrastructure — restarting a container is a real,
  disruptive action even when it recovers automatically, so the test
  doesn't risk the dev environment's own services). Verified via `docker
  inspect` that the container is genuinely running again afterward, not
  just that no error was returned.

## Regression

Targeted sweep (new test file + docker_exec/docker_compose/docker_build
hardening + audit_q_batch07/day1/day2_agents): **269 passed.** Full suite
re-run after this pass — see `tool_enhance_tracking.md`'s row for this
tool for the final count.

## Final verdict

**GREEN FLAG.**

A real, live shell-injection vulnerability closed by reusing the same
established pattern from three prior tools in the same session. No
functionality lost.

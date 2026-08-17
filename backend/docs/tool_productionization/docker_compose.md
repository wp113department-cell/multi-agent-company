# Tool #19 — `docker_compose` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three implementations:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_chat_handlers()`'s own `docker_compose`.
3. `make_docker_agent_handlers()`'s `dk_docker_compose` — narrower by
   design (only `ps`/`logs`/`config`/`images` allowed, no `services`
   field at all).

## Problems found (real, empirically verified — severe, same bug class
as tools #8/#16/#18's siblings)

**Shell injection in `chat_agent.py`'s real dispatch.** `services` (a
list of LLM-controlled strings) was joined with `" ".join(...)` and
interpolated directly into an f-string `shell=True` command with zero
quoting:

```python
dc_services = " ".join(str(s) for s in (inp.get("services") or []))
dc_cmd = f"docker compose {dc_action} {dc_services}"
```

Proved directly, before writing any fix: a `services` value of
`["; touch /tmp/PWNED_docker_compose.txt; echo "]` created a real marker
file on the host, completely outside the intended `docker compose`
invocation.

**`make_chat_handlers`'s own `docker_compose` was already safe** —
`dc_cmd.extend(dc_services)` appends each service as an individual list
element to a list-args `subprocess.run()` call (no `shell=True`), so no
string-interpolation injection surface exists there at all. No fix
needed.

**`dk_docker_compose` was never exposed to this bug** — it doesn't
accept a `services` field, and only allows a fixed allowlist of
read-only actions (`ps`/`logs`/`config`/`images`), also via list-args
`subprocess.run`.

## Changes made

- **`app/tools/execution/docker_compose.py`** (new): `DOCKER_COMPOSE_TOOL`
  (schema, unchanged) and `build_docker_compose_command(action, services,
  detach)` — builds the same command shape as before, but with every
  part — including each service name — individually `shlex.quote()`'d
  before being joined into the single string `chat_agent.py`'s shared
  `_run_subprocess` helper (used by dozens of other tools) expects. This
  follows the exact same per-argument-quoting pattern already established
  for `docker_build`'s `chat_agent.py` dispatch (tool #18), rather than
  switching this one call site to list-args (which would mean bypassing
  `_run_subprocess` entirely for just this tool).
- **`app/agents/chat_agent.py`**: its real dispatch now calls the shared
  builder instead of the vulnerable inline join/interpolation. The
  human-facing confirmation preview for `up` is unchanged (still a plain,
  readable string — display-only, never executed).

**Deliberately left untouched**: `make_chat_handlers`'s own
`docker_compose` and `dk_docker_compose` — both already safe, no fix
needed.

## Tests (real, not mocked at the mechanism level)

`tests/test_docker_compose_hardening.py` (new, 12 tests):

- Schema shape check.
- Pure command-builder tests: a malicious service name is quoted as a
  single literal token (verified via `shlex.split` round-tripping back to
  the exact payload string, proving it can't break out), `up`
  with/without `-d`, `logs`'s `--tail=50` flag, an unknown action
  producing a clean error, every real action variant (`down`/`restart`/
  `build`/`ps`/`pull`) quoting a malicious service correctly.
- **The exact proven exploit, verified closed against the real
  dispatch**: shell injection via `services` on a read action, and the
  same on `up` (also confirming the confirmation gate still fires and the
  payload is still neutralized after approval).
- Regression: `up` correctly declined when the user says no, a real
  `docker compose ps` against a real compose file reaches docker/compose
  itself rather than erroring on a broken command, an unknown action
  still errors cleanly.

## Regression

Targeted sweep (new test file + docker_build hardening +
audit_q_batch09/chat_tools/day2_agents/git_push hardening/pending_gaps):
**338 passed, 1 deselected.** Full suite re-run after this pass — see
`tool_enhance_tracking.md`'s row for this tool for the final count.

## Final verdict

**GREEN FLAG.**

A real, live shell-injection vulnerability closed by reusing an
already-established, already-proven-correct pattern (per-argument
`shlex.quote`) from a sibling tool fixed one turn earlier. No
functionality lost: `up`/`down`/`restart`/`build`/`ps`/`pull`/`logs` all
continue to work exactly as before for legitimate service names.

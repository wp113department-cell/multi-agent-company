---
name: feedback-verify-empirically
description: "Verify side-effecting test/fix behavior against real system state (docker ps, file checks, etc.) rather than assuming a test was safe or a fix worked"
metadata:
  node_type: memory
  type: feedback
  originSessionId: fd497604-c3bc-454e-b85d-b38b4dea39fe
  modified: 2026-07-28T09:29:59.668Z
---

When testing code that can have real side effects (spinning up containers, running subprocess commands, writing files), verify the actual system state afterward (e.g. `docker ps -a`, checking for created files/processes) instead of assuming the test environment was isolated or that the code behaved as expected.

**Why:** During a multi-round security-hardening pass on `multi-agent-company/backend/app/agents/tools.py`, a test of a `docker_compose("up")` confirmation-gate fix was run against the real project directory. Docker Compose auto-discovered the project's actual root `docker-compose.yml` (compose searches parent directories) and began pulling/starting the real stack as a side effect of the test. This was caught by running `docker ps -a` immediately after the test hung/backgrounded, rather than assuming a Python unit-style test against handler functions couldn't have real infra effects. The task was stopped via `TaskStop` and state was verified unchanged before re-testing safely in an isolated temp directory. The user explicitly called this out as valuable: "verify empirically rather than trust that a 'should be safe' test was safe."

**How to apply:** Before and after any test that calls real subprocess/Docker/file-system operations (not pure in-memory logic), check real state (`docker ps -a`, `git status`, file existence) rather than inferring safety from the test's apparent scope. If a test hangs or behaves unexpectedly, stop it and verify nothing was actually created/changed before concluding it's fine. This applies especially in this project given `multi-agent-company/backend/app/agents/tools.py` handlers wrap real `docker`, `git`, and filesystem operations — see [[project-tools-py-hardening]].

This discipline carried forward into the 65-day gap-closure plan (`../PLAN.md`): every regression
count cited in `../IMPLEMENTATION_PROGRESS.md` and `../answers.md` was obtained by actually running
the suite and reading real output, not estimated — including catching a background pytest process
that died silently mid-run during the Day 34 Gap Audit and had to be restarted and genuinely waited
on, rather than reporting a number from an incomplete run.

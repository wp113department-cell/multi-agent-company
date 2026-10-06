# Toolchain sandbox image — tool_enhance.md productionization pass, tool #1
# (bash), 2026-08-15.
#
# Real problem this solves: app.policy.sandbox's own docstring already
# documented that ~10 of the 15 bash-tool variants weren't Docker-sandboxed
# because they "need the target repo's own installed toolchain (its venv/
# node_modules), which the minimal default sandbox image [alpine:latest]
# does not have." Verified empirically before building this (not assumed):
#   - alpine:latest has no python, no git, no node at all.
#   - Bind-mounting the host's own .venv into a container does NOT work:
#     .venv/bin/python3 is a symlink to the HOST's absolute system
#     interpreter path (e.g. /usr/bin/python3), which does not exist inside
#     any container — venvs are not relocatable, self-contained Python
#     installations.
#   - Reference pattern (repos/open-hands): they solve this exactly the way
#     this Dockerfile does — a purpose-built "agent-server" image with a
#     real toolchain baked in (their own image is literally tagged
#     `...agent-server:1.29.0-python`), not host-venv mounting.
#
# Scope: installs the SAME pinned toolchain versions this project's own
# requirements-dev.txt/requirements.txt already specify (pytest, mypy,
# ruff, black, pip-audit, alembic — verified via `pip show` against the
# real host venv before pinning these), plus git. Covers 8 of the 10
# previously-unsandboxed bash variants (test_runner, load_test,
# dependency_audit, qa, devops, cicd, refactor, dependency_agent).
# Deliberately does NOT cover infra_dry_run (needs the Docker daemon
# itself — docker build/docker-compose config — a materially different,
# riskier architecture decision, Docker-in-Docker or docker.sock mounting,
# not made in this pass) or migration (alembic upgrade/downgrade need live
# network access to the real Postgres instance, which a bridge-network
# sandboxed container cannot reach at `localhost` the same way the host
# process can — see this pass's own tool report for the full reasoning).
#
# Build: docker build -t gridiron-bash-toolchain:latest -f docker/bash-sandbox/Dockerfile .
# (run from backend/ so requirements*.txt are in the build context)

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git make nodejs npm \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements-dev.txt \
    && rm -rf /tmp/requirements.txt /tmp/requirements-dev.txt

# run_sandboxed() always bind-mounts the caller's cwd at exactly /workspace
# (app.policy.sandbox's own docstring: "the ONLY host path made visible").
# The container's default user is root, but /workspace's files are owned
# by whatever host UID created them — git >= 2.35's own "dubious ownership"
# protection (a real security feature, not a bug) refuses to operate on a
# directory it doesn't own unless explicitly trusted. Real failure, caught
# by this pass's own tests (test_devops_bash_runs_real_git_through_the_
# sandbox / test_cicd_bash_runs_real_git_through_the_sandbox), not assumed.
# Safe here specifically because /workspace is always a fresh, ephemeral,
# single-purpose mount for exactly one sandboxed command — there is no
# other repository this blanket trust could apply to inside this image.
# Job sandbox (Sol A01/G1): every repository-code tool runs in this image now,
# with the worktree mounted at its host path — trust it wherever it is mounted.
RUN git config --global --add safe.directory '*' \
    && npm install -g pnpm@9 --no-audit --no-fund  # pnpm 10+ needs Node 22; Debian ships 20

WORKDIR /workspace

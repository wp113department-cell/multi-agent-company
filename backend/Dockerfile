FROM python:3.11-slim

WORKDIR /app

# System deps: git (agents shell out to it), build-essential (a couple of
# pinned wheels — e.g. tree-sitter — build from source on some platforms).
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 appuser
# Docker CLI only (no engine): in the Docker version the backend starts the
# code sandboxes on the computer's own Docker engine through the mounted
# socket (docker-compose.yml). Without a reachable engine every sandbox
# reports "unavailable" and never falls back to running code here.
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
# Task worktrees live on a named volume (docker-compose.yml) so sandbox
# containers can mount them; an empty volume takes this folder's owner.
RUN mkdir -p /tmp/gridiron-worktrees && chown appuser:appuser /tmp/gridiron-worktrees

# Repositories live on a folder mounted from the user's computer
# (/workspace); its files are owned by a different uid than appuser, which
# makes git refuse every command ("dubious ownership"). The mount is the
# user's own workspace, so trust it.
RUN git config --system --add safe.directory '*'

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

# docker-compose.yml overrides this per service (migrate/backend/worker);
# this default matches the Procfile's `web` process for a plain `docker run`.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

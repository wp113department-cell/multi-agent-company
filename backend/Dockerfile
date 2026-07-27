FROM python:3.11-slim

WORKDIR /app

# System deps: git (agents shell out to it), build-essential (a couple of
# pinned wheels — e.g. tree-sitter — build from source on some platforms).
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# docker-compose.yml overrides this per service (migrate/backend/worker);
# this default matches the Procfile's `web` process for a plain `docker run`.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

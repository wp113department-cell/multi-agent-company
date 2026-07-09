#!/usr/bin/env bash
# Gridiron Developer Department — one-command startup
# Usage: ./run.sh
# Starts: PostgreSQL (Docker), FastAPI backend on :8000, Next.js frontend on :3000

set -e

REPO="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$REPO/backend"
FRONTEND="$REPO/apps/web"

# ── Colours ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[gridiron]${NC} $*"; }
warn()  { echo -e "${YELLOW}[gridiron]${NC} $*"; }
error() { echo -e "${RED}[gridiron]${NC} $*" >&2; }

# ── Pre-flight checks ──────────────────────────────────────────────────────────
if [ ! -f "$BACKEND/.env" ]; then
  warn "No backend/.env found. Copying from .env.example …"
  cp "$BACKEND/.env.example" "$BACKEND/.env"
  error "Edit backend/.env and set your API key, then re-run."
  error "  → nano $BACKEND/.env"
  exit 1
fi

# Load env vars from backend/.env (skip comments and blank lines)
while IFS= read -r line || [ -n "$line" ]; do
  [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
  export "$line" 2>/dev/null || true
done < "$BACKEND/.env"

# ── 1. PostgreSQL ──────────────────────────────────────────────────────────────
info "Checking PostgreSQL (Docker) …"
if ! docker ps --format '{{.Names}}' | grep -q "^gridiron-postgres$"; then
  info "Starting gridiron-postgres container …"
  docker start gridiron-postgres 2>/dev/null || \
  docker run -d \
    --name gridiron-postgres \
    -e POSTGRES_USER=gridiron \
    -e POSTGRES_PASSWORD=gridiron_dev_only \
    -e POSTGRES_DB=gridiron_dev \
    -p 5432:5432 \
    pgvector/pgvector:pg16
  info "Waiting for Postgres to be ready …"
  sleep 5
fi
info "PostgreSQL: running on localhost:5432"

# ── 2. Alembic migrations ──────────────────────────────────────────────────────
info "Running database migrations …"
cd "$BACKEND"
.venv/bin/alembic upgrade head 2>&1 | grep -E "Running upgrade|already at|INFO" || true
cd "$REPO"

# ── 3. FastAPI backend ─────────────────────────────────────────────────────────
info "Starting FastAPI backend on http://localhost:8000 …"
cd "$BACKEND"
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
cd "$REPO"
sleep 2

# Quick health check
if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
  info "Backend: http://localhost:8000 ✓"
else
  warn "Backend may still be starting (check logs above)"
fi

# ── 4. Next.js frontend ────────────────────────────────────────────────────────
info "Starting Next.js frontend on http://localhost:3000 …"
cd "$FRONTEND"
if [ ! -d node_modules ]; then
  warn "node_modules missing — running npm install …"
  npm install
fi
# Force port 3000 — unset PORT so backend's PORT=8000 doesn't leak in
PORT=3000 npm run dev &
FRONTEND_PID=$!
cd "$REPO"

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info " Gridiron Developer Department is starting up"
info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info "  Dashboard (Mission Control): http://localhost:3000"
info "  API + Swagger docs:          http://localhost:8000/docs"
info "  API health:                  http://localhost:8000/health"
info ""
info "  Press Ctrl+C to stop all services"
info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Shutdown handler ───────────────────────────────────────────────────────────
cleanup() {
  echo ""
  info "Shutting down …"
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
  wait $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
  info "All services stopped. Postgres container left running."
}
trap cleanup INT TERM

wait $BACKEND_PID $FRONTEND_PID

#!/usr/bin/env bash
# Sol A41 (2026-10-16): run the real-stack browser journeys
# (apps/web/e2e-real/journeys.spec.ts) against a real FastAPI backend, real
# Postgres and the production Next build. Nothing is mocked; no paid AI call
# can happen (fake Anthropic key, blank Voyage/Groq/Firecrawl keys), and the
# live-AI journeys (live-ai.spec.ts) are never run here.
#
# Used by the `real-journeys` CI job and runnable locally:
#   DATABASE_URL=postgresql+asyncpg://…/a_throwaway_db  scripts/e2e_real_stack.sh
# The database must be a throwaway one: it is migrated and demo data is loaded.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${DATABASE_URL:?set DATABASE_URL to a throwaway database}"
PYTHON="${PYTHON:-python}"
WORK="${E2E_WORK_DIR:-$(mktemp -d)}"
API_PORT="${E2E_API_PORT:-8000}"
WEB_PORT="${E2E_WEB_PORT:-3100}"

export ANTHROPIC_API_KEY=sk-ant-test-not-a-real-key GROQ_API_KEY= VOYAGE_API_KEY= FIRECRAWL_API_KEY=
export USE_GROQ=false SENTRY_DSN= ALERT_WEBHOOK_URL= RATE_LIMIT_ENABLED=false QUEUE_BACKEND=asyncio
export JWT_AUTH_ENABLED=true RBAC_ENABLED=true ALLOW_LEGACY_ROLE_HEADER=false
export JWT_SECRET_KEY="${JWT_SECRET_KEY:-e2e-$(openssl rand -hex 24)}"
export DEFAULT_ADMIN_PASSWORD="${DEFAULT_ADMIN_PASSWORD:-e2e-admin-$(openssl rand -hex 8)}"
export ALLOWED_WORKSPACE_PARENT="$WORK" WORKTREES_DIR="$WORK/.worktrees" REPOS_DIR="$WORK/.repos"
export E2E_USER="${E2E_USER:-audit12}" E2E_PASS="${E2E_PASS:-e2e-$(openssl rand -hex 8)}"
# The backend seeds `admin` once with must_change_password=True: journey A5.
export E2E_FLAG_USER=admin E2E_FLAG_PASS="$DEFAULT_ADMIN_PASSWORD"
export E2E_API_URL="http://localhost:$API_PORT" E2E_BASE_URL="http://localhost:$WEB_PORT"
export NEXT_PUBLIC_API_URL="$E2E_API_URL"
mkdir -p "$WORK"

PIDS=()
cleanup() { for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

wait_for() {  # url, name
  for _ in $(seq 1 120); do curl -fs -o /dev/null "$1" && return 0; sleep 1; done
  echo "$2 did not start" >&2; return 1
}

cd "$ROOT/backend"
"$PYTHON" -m alembic upgrade head
"$PYTHON" -m scripts.seed_demo_data --workspace "$WORK/demo-projects"
"$PYTHON" - <<'EOF'
import asyncio, os
from app.auth.jwt import hash_password
from app.db.repository import create_user, get_user
from app.db.session import get_session_factory

async def main() -> None:
    async with get_session_factory()() as db:
        if await get_user(db, os.environ["E2E_USER"]) is None:
            await create_user(db, os.environ["E2E_USER"], hash_password(os.environ["E2E_PASS"]), role="approver")

asyncio.run(main())
EOF
"$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" > "$WORK/backend.log" 2>&1 &
PIDS+=($!)
wait_for "$E2E_API_URL/health" backend || { cat "$WORK/backend.log"; exit 1; }

cd "$ROOT/apps/web"
pnpm run build > "$WORK/web-build.log" 2>&1 || { tail -50 "$WORK/web-build.log"; exit 1; }
npx next start -p "$WEB_PORT" > "$WORK/web.log" 2>&1 &
PIDS+=($!)
wait_for "$E2E_BASE_URL/login" frontend || { cat "$WORK/web.log"; exit 1; }

status=0
npx playwright test -c playwright.real.config.ts e2e-real/journeys.spec.ts || status=$?
[ "$status" = 0 ] || tail -80 "$WORK/backend.log"
exit "$status"

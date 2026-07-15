web: cd backend && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: cd backend && rq worker gridiron-high gridiron-default --url ${REDIS_URL:-redis://localhost:6379/0} --with-scheduler

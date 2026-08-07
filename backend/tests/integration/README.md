# Integration Tests — Real Multi-Component, No LLM Key Required

Tests here exercise more than one real component together (e.g. the DB session
layer + ORM models + a full commit/refresh/delete round-trip) against the same
Postgres every other test in this suite already runs against. They need
nothing beyond the standard `DATABASE_URL` this repo's `tests/conftest.py`
already defaults and CI's `postgres` service already provides — so, unlike
`tests/pending/`, they run **by default**, with no extra env var.

| File | What it tests |
|---|---|
| `test_db_integration.py` | Full CRUD + state transitions against a real Postgres: tasks, logs, agent_runs, subtasks |

Tests that additionally need a real, billed LLM call (Manager Agent dispatch,
full pipeline E2E, etc.) belong in `tests/pending/` instead, gated behind
`RUN_PENDING_TESTS=1` — see that folder's README for the full list and how to
run them. The split is by *what the test actually needs*, not by how
"integration-y" it sounds: a DB-only test that isn't LLM-gated has no reason
to be skipped by default, and an empty `integration/` folder next to a
populated `pending/` one is actively misleading to anyone auditing coverage
by directory structure alone (AUDIT_Q_BATCH06 §11).

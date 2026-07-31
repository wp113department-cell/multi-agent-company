"""Test configuration — sets required env vars before any module calls get_settings().

The Settings validator requires either ANTHROPIC_API_KEY or (USE_GROQ=true + GROQ_API_KEY).
Unit tests never make real LLM calls, so we supply dummy keys here so the validator passes.
The _settings singleton is reset at session start so env vars take effect even if config
was imported before conftest ran.
"""

from __future__ import annotations

import os

# Set before any test module imports production code that may call get_settings().
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-placeholder-not-real")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://gridiron:gridiron_dev_only@localhost:5432/gridiron_dev",
)
os.environ.setdefault("TARGET_REPO_PATH", ".")

# Gap-closure (Audit 05 fix): SEC-05-012/013 added a real auth dependency
# (require_approver/require_authenticated) to every mutating endpoint across
# the whole API, closing a real production gap — but rbac_enabled defaults
# to True in production (unchanged), and the vast majority of this existing
# test suite drives those same endpoints through TestClient with no auth
# headers at all, since none of them were gated before this fix. Setting
# RBAC_ENABLED=false here is the same explicit, documented, test-only
# bypass this project's own RBAC design already treats as legitimate
# ("local dev" — see middleware/rbac.py's module docstring), scoped to the
# test environment only via this conftest.py, matching the existing
# ANTHROPIC_API_KEY/DATABASE_URL setdefault pattern above. Production's own
# default (rbac_enabled=True) is untouched — this line never runs outside
# pytest. RBAC's own real enforcement logic is covered directly by
# tests/test_rbac.py and tests/test_audit05_security_fixes.py, which
# override this via patch("app.middleware.rbac.get_settings") to set
# rbac_enabled=True explicitly for those specific cases.
os.environ.setdefault("RBAC_ENABLED", "false")

# The general unit suite mocks anthropic.Anthropic directly and expects
# run_agent_graph() to go through the real LangGraph node path. .env sets
# USE_GROQ=true for local manual/dev-server use — without this override the
# Groq bypass in base_graph.py would make real, unmocked network calls to
# Groq for every test, which either hang or slow-burn through rate-limit
# retries. tests/groq_compat.py explicitly sets/pops USE_GROQ=true around its
# own fixture, so the dedicated Groq integration tests are unaffected.
os.environ["USE_GROQ"] = "false"

import pytest  # noqa: E402 — must come after env vars are set


@pytest.fixture(autouse=True, scope="session")
def reset_settings_cache() -> None:
    """Force get_settings() to re-evaluate using the env vars set above."""
    import app.config as cfg

    cfg._settings = None


@pytest.fixture(autouse=True)
def reset_db_engine():  # type: ignore[no-untyped-def]
    """Gap-closure Day 10 (Gap Audit Protocol, first checkpoint) — real,
    reproducible, pre-existing hazard this audit surfaced, not invented:
    app.db.session.get_session_factory()/get_engine() cache a process-wide
    AsyncEngine singleton. Any test whose code path touches it (directly, or
    indirectly via `with TestClient(app) as client:` running app.main's real
    lifespan) binds that singleton to *that test's own* event loop. Because
    pytest-asyncio gives async tests (and asyncio.run()-based sync tests)
    their own event loop each, the NEXT test to touch get_session_factory()
    inherits a reference bound to an already-closed loop and fails with
    "RuntimeError: Event loop is closed" — reproduced live via bisection
    across three separate, unrelated test files before this fixture existed
    (see the per-file comments this replaced in test_audit_log_migration.py,
    test_credential_vault.py, test_memory_archived_filter.py — kept in place
    since this fixture doesn't retroactively explain history, it prevents
    recurrence). Resetting to None after every test — not disposing the old
    engine, matching this codebase's own established convention for this
    exact reset (test_retention_archive.py originally established it) — is
    a no-op for the vast majority of tests that never touch it at all, and
    guarantees whichever test runs next gets one freshly bound to its own
    event loop instead of inheriting a stale one."""
    yield
    import app.db.session as _sess

    _sess._engine = None
    _sess._session_factory = None


@pytest.fixture(autouse=True)
def reset_circuit_breakers():  # type: ignore[no-untyped-def]
    """Gap-closure Day 22 (Stage 1.3, answers.md) — get_anthropic_breaker()/
    get_groq_breaker() are module-level singletons shared across the whole
    process, by design (production wants one real breaker per provider,
    not one per call site). Several tests deliberately simulate LLM call
    failures to exercise error-handling paths; without this reset, those
    failures accumulate in the SAME shared breaker across unrelated test
    files, and once consecutive failures reach
    llm_circuit_breaker_failure_threshold (default 5) the breaker opens —
    silently turning a later, unrelated test's mocked LLM call into a
    CircuitBreakerOpenError instead of whatever it actually meant to test.
    Same reset-to-None-after-every-test convention as reset_db_engine
    above, applied to the same class of process-wide-singleton hazard."""
    yield
    import app.fleet.circuit_breaker as _cb

    _cb._anthropic_breaker = None
    _cb._groq_breaker = None

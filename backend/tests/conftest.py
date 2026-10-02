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
# tests that mock the DB verify tokens without a users row; the revocation tests opt in
os.environ.setdefault("JWT_REVALIDATE_AGAINST_DB", "false")

# T2-B5 (2026-09-22, GRIDIRON_PARTIAL #453/#455) flipped enable_security_
# architecture_gates's PRODUCTION default to True now that a real self-
# correction retry loop exists for it — but a large, pre-existing slice of
# this test suite calls run_manager()/run_epic_manager() end to end without
# mocking security_reviewer/architecture_reviewer/dependency_security_agent
# at all (they were never testing those gates, they predate this flag
# mattering to them). With the gates on by default, those tests would make
# real, unmocked Anthropic calls with this file's own dummy API key,
# tripping the circuit breaker and failing/timing out — a real regression
# caught live (tests/test_audit04_orchestration_fixes.py's own stated
# invariant, "No real Anthropic API calls anywhere," broke under the new
# default). Same fix shape as RBAC_ENABLED above: the test environment gets
# its own explicit, documented default (off) distinct from production's;
# any test that specifically wants to exercise the gates-enabled behavior
# (tests/test_batch16_quality_gates.py) already opts in per-test via
# patch.object(get_settings(), "enable_security_architecture_gates", True).
os.environ.setdefault("ENABLE_SECURITY_ARCHITECTURE_GATES", "false")

# The general unit suite mocks anthropic.Anthropic directly and expects
# run_agent_graph() to go through the real LangGraph node path. .env sets
# USE_GROQ=true for local manual/dev-server use — without this override the
# Groq bypass in base_graph.py would make real, unmocked network calls to
# Groq for every test, which either hang or slow-burn through rate-limit
# retries. tests/groq_compat.py explicitly sets/pops USE_GROQ=true around its
# own fixture, so the dedicated Groq integration tests are unaffected.
os.environ["USE_GROQ"] = "false"

# Same reasoning for embeddings (2026-09-29, when a real VOYAGE_API_KEY was
# added to .env): the unit suite assumes NO embedding key — with one, every
# test that touches memory would make real, paid Voyage calls and write real
# memory_embeddings / versioned_lessons rows into the shared dev database.
# An env var beats the .env file in pydantic-settings, so this blanks it for
# the normal suite. Only the opt-in live tests (RUN_PENDING_TESTS=1,
# tests/pending/) keep the real key.
if os.environ.get("RUN_PENDING_TESTS") != "1":
    os.environ["VOYAGE_API_KEY"] = ""
    # Production audit 09: the daily spend ledger lives in the real dev Redis;
    # unit tests keep an in-process counter so they never touch the real total.
    os.environ["SPEND_GUARD_REDIS"] = "false"

# COST_MODE defaults to "economy" in production (2026-09-29), which turns the
# optional reflection/critique/planner/lesson calls and the LLM quality gates
# off. The existing suite tests those features, so it runs under "quality";
# tests of the cost modes themselves set the mode explicitly.
os.environ.setdefault("COST_MODE", "quality")
# Same for PIPELINE_MODE: production default is now "auto" (smart router);
# the existing suite was written against "full". Router tests set "auto".
os.environ.setdefault("PIPELINE_MODE", "full")
# The owner's .env caps real spend at $1/day; the suite was written against
# the $25 default and must not depend on the local cap.
os.environ.setdefault("COST_BUDGET_DAILY_USD", "25")
# The owner's .env has a real SENTRY_DSN (2026-10-02). Test runs start the app
# (TestClient lifespan) and tear connections down abruptly, which sent test
# noise to the real Sentry project ("unexpected connection_lost() call").
# Tests never report to Sentry; tests that check Sentry wiring patch it.
os.environ["SENTRY_DSN"] = ""

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
def reset_concurrency_semaphores():  # type: ignore[no-untyped-def]
    """Batch 2 audit gap-closure (2026-08-10) — same process-wide-singleton
    hazard class as reset_db_engine/reset_circuit_breakers above, just never
    extended to this third module: app.pipeline.concurrency's _epic_sem/
    _agent_run_sem/_subtask_sems are lazily-created process-global
    singletons, and several tests (test_concurrency.py's
    TestSlotAcquisitionTimeout, in particular) call reset_for_testing() with
    a deliberately tiny cap (e.g. max_agent_runs=1) to exercise the timeout
    path, with no teardown to restore a normal cap afterward. Without this
    fixture, any test running later in the SAME pytest session — regardless
    of which file it's in — silently inherits that cap-of-1, making real
    concurrency (e.g. tests/test_subtask_fanout.py's fan-out tests)
    impossible to observe even though the code under test is correct.
    Reset to None (not to a specific reset_for_testing() value) so the next
    _get_*_sem() call rebuilds fresh from that test's own real settings,
    matching the module's own lazy-init pattern."""
    yield
    import app.pipeline.concurrency as _conc

    _conc._epic_sem = None
    _conc._agent_run_sem = None
    _conc._subtask_sems = {}


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


@pytest.fixture(autouse=True)
def _retrospectives_to_tmp(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production audit 2026-09-29: release_retrospective writes its reports to
    the REAL repo's docs/reports/retrospectives/ — every full test run left
    RETROSPECTIVE_<sha>.md files behind in the working tree. Redirect for all
    tests; the module's own default path is unchanged in production."""
    from app.fleet import release_retrospective

    monkeypatch.setattr(
        release_retrospective,
        "_REPORTS_DIR",
        tmp_path_factory.mktemp("retrospectives"),
    )

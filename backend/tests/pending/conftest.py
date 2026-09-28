"""Shared fixtures and skip markers for pending (API-key-required) tests.

To run these tests set RUN_PENDING_TESTS=1 alongside real API keys.
Supports Anthropic (sk-ant-...), Groq (gsk_...), and Gemini backends
(the latter two TEMPORARY, easily removable — see app/agents/
gemini_adapter.py's own docstring for the full removal list).

    # With Anthropic:
    RUN_PENDING_TESTS=1 \\
    ANTHROPIC_API_KEY=sk-ant-your-real-key \\
    DATABASE_URL=postgresql+asyncpg://gridiron:gridiron@localhost/gridiron_dev \\
    pytest tests/pending/ -v

    # With Groq (temporary dev mode):
    RUN_PENDING_TESTS=1 \\
    GROQ_PREFERRED=1 \\
    GROQ_API_KEY=gsk_your-groq-key \\
    DATABASE_URL=postgresql+asyncpg://gridiron:gridiron@localhost/gridiron_dev \\
    pytest tests/pending/ -v

    # With Gemini (temporary dev mode):
    RUN_PENDING_TESTS=1 \\
    GEMINI_PREFERRED=1 \\
    GEMINI_API_KEY=your-real-gemini-key \\
    DATABASE_URL=postgresql+asyncpg://gridiron:gridiron@localhost/gridiron_dev \\
    pytest tests/pending/ -v
"""

from __future__ import annotations

import os
import pytest

_RUN = os.environ.get("RUN_PENDING_TESTS") == "1"

_anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
_groq_key = os.environ.get("GROQ_API_KEY", "")
_gemini_key = os.environ.get("GEMINI_API_KEY", "")

# 2026-09-28 real bug found while actually running these for the first time
# with a real Groq key: the root tests/conftest.py unconditionally forces
# os.environ["USE_GROQ"] = "false" (a correct safety default for the general
# suite, so it never makes accidental real Groq calls) — but that module-level
# line runs BEFORE this file is even imported, permanently clobbering
# USE_GROQ for the whole test process. This meant _has_llm's own documented
# "or USE_GROQ=true GROQ_API_KEY=gsk_..." path (see this file's own module
# docstring and tests/pending/README.md) has never actually been reachable
# since that global default was added — this directory's own explicit
# RUN_PENDING_TESTS=1 opt-in already signals real-LLM intent, so Groq/Gemini
# availability here is judged purely from each key's own shape, not the
# globally-clobbered USE_GROQ/USE_GEMINI vars.
_has_llm = _RUN and (
    (len(_anthropic_key) > 30 and _anthropic_key.startswith("sk-ant-"))
    or (len(_groq_key) > 10 and _groq_key.startswith("gsk_"))
    or len(_gemini_key) > 10
)
# ANTHROPIC_FORCE_INVALID / a syntactically-valid-but-out-of-balance key
# can't be told apart from a genuinely working one by shape alone (a real
# 401/insufficient-balance error only shows up at call time) — so "prefer
# Groq"/"prefer Gemini" is decided by explicit opt-in (GROQ_PREFERRED=1 /
# GEMINI_PREFERRED=1), not by guessing whether the Anthropic key will
# actually work. Set one of these whenever you want this directory to
# route through that backend regardless of whatever Anthropic key happens
# to be present. Mutually exclusive by construction below (Groq checked
# first) — set only one.
_prefer_groq = _RUN and os.environ.get("GROQ_PREFERRED", "") == "1" and (
    len(_groq_key) > 10 and _groq_key.startswith("gsk_")
)
_prefer_gemini = (
    _RUN
    and not _prefer_groq
    and os.environ.get("GEMINI_PREFERRED", "") == "1"
    and len(_gemini_key) > 10
)

_has_voyage = _RUN and len(os.environ.get("VOYAGE_API_KEY", "")) > 10

_has_db = _RUN and "gridiron" in os.environ.get("DATABASE_URL", "")

# ---------------------------------------------------------------------------
# Engine reset — each async test gets its own event loop (pytest-asyncio
# function scope). The global SQLAlchemy engine is bound to the first loop
# and can't be reused across loops. Reset before every test so each test
# creates a fresh engine for its own loop.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_db_engine() -> None:
    """Reset SQLAlchemy engine/session globals before each test."""
    import app.db.session as _sess

    _sess._engine = None
    _sess._session_factory = None


@pytest.fixture(autouse=True)
def _auto_groq_when_no_anthropic_key():
    """2026-09-28 — when this directory's own real key is Groq, not
    Anthropic (see _prefer_groq above), transparently redirect every
    anthropic.Anthropic() call these tests make to Groq instead, reusing
    tests/groq_compat.py's own already-working shim (class-level patch, so
    it catches base_graph.py's planner_node/replan_node calls too — those
    call _call_anthropic() directly and are NOT covered by base_graph.py's
    own narrower "Groq bypass" block, which only short-circuits the main
    call_llm path and still requires settings.use_groq=True, itself
    unreachable here for the same USE_GROQ-clobbering reason _has_llm's
    fix above documents). A no-op whenever a real Anthropic key is used
    instead — every existing/future real-Anthropic run of this directory
    is completely unaffected.
    """
    if not _prefer_groq:
        yield
        return

    from unittest.mock import patch

    from tests.groq_compat import _make_groq_backed_anthropic

    fake_client = _make_groq_backed_anthropic(_groq_key)
    with patch("app.agents.base_graph.anthropic.Anthropic", return_value=fake_client):
        yield


@pytest.fixture(autouse=True)
def _auto_gemini_when_preferred():
    """2026-09-28 — TEMPORARY, easily removable (see app/agents/
    gemini_adapter.py's own docstring for the full removal list): same
    mechanism as _auto_groq_when_no_anthropic_key above, one level down
    the preference chain (see _prefer_gemini above), reusing tests/
    gemini_compat.py's own class-level anthropic.Anthropic patch. A no-op
    whenever Groq or a real Anthropic key is preferred instead.
    """
    if not _prefer_gemini:
        yield
        return

    from unittest.mock import patch

    from tests.gemini_compat import _make_gemini_backed_anthropic

    fake_client = _make_gemini_backed_anthropic(_gemini_key)
    with patch("app.agents.base_graph.anthropic.Anthropic", return_value=fake_client):
        yield


# ---------------------------------------------------------------------------
# Skip markers — each test file uses one of these
# ---------------------------------------------------------------------------

requires_anthropic = pytest.mark.skipif(
    not _has_llm,
    reason=(
        "Skipped — set RUN_PENDING_TESTS=1 and one of: "
        "ANTHROPIC_API_KEY=sk-ant-..., or GROQ_PREFERRED=1 GROQ_API_KEY=gsk_..., "
        "or GEMINI_PREFERRED=1 GEMINI_API_KEY=..."
    ),
)

requires_voyage = pytest.mark.skipif(
    not _has_voyage,
    reason="Skipped — set RUN_PENDING_TESTS=1 and a real VOYAGE_API_KEY to run",
)

requires_db = pytest.mark.skipif(
    not _has_db,
    reason="Skipped — set RUN_PENDING_TESTS=1 and a real DATABASE_URL to run",
)

requires_all = pytest.mark.skipif(
    not (_has_llm and _has_db),
    reason="Skipped — set RUN_PENDING_TESTS=1 + LLM key + DATABASE_URL to run",
)

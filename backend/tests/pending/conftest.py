"""Shared fixtures and skip markers for pending (API-key-required) tests.

To run these tests set RUN_PENDING_TESTS=1 alongside real API keys.
Supports both Anthropic (sk-ant-...) and Groq (gsk_...) backends.

    # With Anthropic:
    RUN_PENDING_TESTS=1 \\
    ANTHROPIC_API_KEY=sk-ant-your-real-key \\
    DATABASE_URL=postgresql+asyncpg://gridiron:gridiron@localhost/gridiron_dev \\
    pytest tests/pending/ -v

    # With Groq (temporary dev mode):
    RUN_PENDING_TESTS=1 \\
    USE_GROQ=true \\
    GROQ_API_KEY=gsk_your-groq-key \\
    DATABASE_URL=postgresql+asyncpg://gridiron:gridiron@localhost/gridiron_dev \\
    pytest tests/pending/ -v
"""
from __future__ import annotations

import os
import pytest

_RUN = os.environ.get("RUN_PENDING_TESTS") == "1"

_anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
_groq_key = os.environ.get("GROQ_API_KEY", "")
_use_groq = os.environ.get("USE_GROQ", "").lower() in ("1", "true", "yes")

# A real LLM key is available when EITHER Anthropic key OR Groq key+flag is present
_has_llm = _RUN and (
    (len(_anthropic_key) > 30 and _anthropic_key.startswith("sk-ant-"))
    or (_use_groq and len(_groq_key) > 10 and _groq_key.startswith("gsk_"))
)

_has_voyage = (
    _RUN
    and len(os.environ.get("VOYAGE_API_KEY", "")) > 10
)

_has_db = (
    _RUN
    and "gridiron" in os.environ.get("DATABASE_URL", "")
)

# ---------------------------------------------------------------------------
# Engine reset — each async test gets its own event loop (pytest-asyncio
# function scope). The global SQLAlchemy engine is bound to the first loop
# and can't be reused across loops. Reset before every test so each test
# creates a fresh engine for its own loop.
# ---------------------------------------------------------------------------

import pytest

@pytest.fixture(autouse=True)
def reset_db_engine() -> None:
    """Reset SQLAlchemy engine/session globals before each test."""
    import app.db.session as _sess
    _sess._engine = None
    _sess._session_factory = None


# ---------------------------------------------------------------------------
# Skip markers — each test file uses one of these
# ---------------------------------------------------------------------------

requires_anthropic = pytest.mark.skipif(
    not _has_llm,
    reason=(
        "Skipped — set RUN_PENDING_TESTS=1 and either "
        "ANTHROPIC_API_KEY=sk-ant-... or USE_GROQ=true GROQ_API_KEY=gsk_..."
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

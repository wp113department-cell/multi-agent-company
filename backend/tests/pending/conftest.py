"""Shared fixtures and skip markers for pending (API-key-required) tests.

To run these tests, set RUN_PENDING_TESTS=1 in your environment alongside
the real API keys. Without it ALL tests in this folder are skipped so the
main test suite stays green.

    RUN_PENDING_TESTS=1 \\
    ANTHROPIC_API_KEY=sk-ant-your-real-key \\
    DATABASE_URL=postgresql+asyncpg://gridiron:gridiron@localhost/gridiron_dev \\
    pytest tests/pending/ -v
"""
from __future__ import annotations

import os
import pytest

_RUN = os.environ.get("RUN_PENDING_TESTS") == "1"

_has_anthropic = (
    _RUN
    and len(os.environ.get("ANTHROPIC_API_KEY", "")) > 30
    and os.environ.get("ANTHROPIC_API_KEY", "").startswith("sk-ant-")
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
# Skip markers — each test file uses one of these
# ---------------------------------------------------------------------------

requires_anthropic = pytest.mark.skipif(
    not _has_anthropic,
    reason="Skipped — set RUN_PENDING_TESTS=1 and a real ANTHROPIC_API_KEY to run",
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
    not (_has_anthropic and _has_db),
    reason="Skipped — set RUN_PENDING_TESTS=1 + ANTHROPIC_API_KEY + DATABASE_URL to run",
)

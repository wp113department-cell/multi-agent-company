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
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://gridiron:gridiron_dev_only@localhost:5432/gridiron_dev")
os.environ.setdefault("TARGET_REPO_PATH", ".")

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

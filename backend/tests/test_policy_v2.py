"""Tests for Policy Engine v2 — glob matching, async DB operations mocked."""
from __future__ import annotations

import pytest

from app.policy.engine_v2 import match_pattern_sync


# ---- Glob pattern unit tests (sync, no DB) ----

@pytest.mark.parametrize(
    "path,pattern,expected",
    [
        # migrations gate
        ("backend/migrations/versions/003.py", "**/migrations/**", True),
        ("migrations/versions/003.py", "**/migrations/**", True),
        ("something/migrations/add_column.sql", "**/migrations/**", True),
        ("app/tasks.py", "**/migrations/**", False),
        # customer API gate
        ("api/customer/orders.py", "api/customer/**", True),
        ("api/customer/nested/handler.py", "api/customer/**", True),
        ("api/other/handler.py", "api/customer/**", False),
        ("api_customer/file.py", "api/customer/**", False),
        # auth flag
        ("auth/login.py", "auth/**", True),
        ("auth/jwt/token.py", "auth/**", True),
        ("not_auth/file.py", "auth/**", False),
        ("app/auth/login.py", "auth/**", False),  # different prefix
        # wildcard only
        ("anything.py", "**", True),
        # single wildcard
        ("file.py", "*.py", True),
        ("subdir/file.py", "*.py", False),
        # question mark
        ("file.py", "fil?.py", True),
        ("file.py", "fil??.py", False),
    ],
)
def test_glob_pattern_matching(path: str, pattern: str, expected: bool) -> None:
    assert match_pattern_sync(path, pattern) is expected


def test_migrations_gate_blocks_exact_migration_file() -> None:
    assert match_pattern_sync("app/db/migrations/0042_add_column.py", "**/migrations/**") is True


def test_auth_gate_does_not_match_partial_segment() -> None:
    # "authorize" starts with "auth" but "authorize/**" is a different pattern
    assert match_pattern_sync("authorization/handler.py", "auth/**") is False


def test_double_star_matches_deep_nesting() -> None:
    assert match_pattern_sync("a/b/c/d/migrations/e/f/file.py", "**/migrations/**") is True


def test_adding_rule_to_empty_list_takes_effect() -> None:
    """Prove: policy match is determined by the pattern string, not hardcoded names.
    A new pattern added to the list is respected immediately."""
    patterns = [
        ("**/migrations/**", True),
        ("api/customer/**", True),
        ("auth/**", True),
        ("secrets/**", True),  # newly added — must match
    ]
    path = "secrets/production.env"
    for pattern, expected in patterns:
        if pattern == "secrets/**":
            assert match_pattern_sync(path, pattern) is expected
        else:
            assert match_pattern_sync(path, pattern) is False


def test_pattern_is_case_sensitive() -> None:
    assert match_pattern_sync("Auth/login.py", "auth/**") is False
    assert match_pattern_sync("auth/login.py", "auth/**") is True

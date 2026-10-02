"""Qoder cross-check PROD-08-101 (2026-10-02): rate limits were keyed by the
TCP peer, and the Next.js frontend proxies every /api call, so every user
shared one bucket. Now: per user when logged in; otherwise the client IP from
X-Forwarded-For, trusted only from configured proxy peers.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.rate_limit import rate_limit_key


def _req(peer: str, headers: dict[str, str] | None = None, cookie: str | None = None):  # type: ignore[no-untyped-def]
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers={k.lower(): v for k, v in (headers or {}).items()},
        cookies={"gridiron_token": cookie} if cookie else {},
    )


@pytest.fixture()
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    if not get_settings().jwt_secret_key:
        monkeypatch.setattr(get_settings(), "jwt_secret_key", "k" * 64)


def test_two_logged_in_users_behind_the_proxy_get_separate_buckets(
    jwt_secret: None,
) -> None:
    from app.auth.jwt import create_access_token

    a = rate_limit_key(_req("127.0.0.1", cookie=create_access_token({"sub": "alice"})))
    b = rate_limit_key(_req("127.0.0.1", cookie=create_access_token({"sub": "bob"})))
    assert a == "user:alice" and b == "user:bob"


def test_anonymous_calls_via_the_proxy_use_the_forwarded_client_ip() -> None:
    k1 = rate_limit_key(_req("127.0.0.1", {"X-Forwarded-For": "203.0.113.7, 10.0.0.1"}))
    k2 = rate_limit_key(_req("127.0.0.1", {"X-Forwarded-For": "198.51.100.9"}))
    assert k1 == "ip:203.0.113.7" and k2 == "ip:198.51.100.9"


def test_forwarded_header_from_an_untrusted_peer_is_ignored() -> None:
    assert (
        rate_limit_key(_req("192.0.2.50", {"X-Forwarded-For": "1.2.3.4"}))
        == "ip:192.0.2.50"
    )


def test_forged_token_falls_back_to_ip(jwt_secret: None) -> None:
    assert rate_limit_key(_req("192.0.2.50", cookie="not-a-jwt")) == "ip:192.0.2.50"

"""SSRF guard on NAT64 / IPv4-mapped addresses (2026-09-30).

On a NAT64 network every public IPv4 site resolves into 64:ff9b::/96, which
ipaddress classes as reserved, so every external fetch was refused. The guard
now judges the embedded IPv4 — public passes, private/metadata still denied.
DNS is faked so the test doesn't depend on the machine's network.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from app.agents.tool_security import _ssrf_denial_reason


def _resolves_to(addr: str):  # type: ignore[no-untyped-def]
    return patch.object(
        socket, "getaddrinfo", return_value=[(socket.AF_INET6, 1, 6, "", (addr, 0))]
    )


@pytest.mark.parametrize(
    "addr",
    ["64:ff9b::22e3:ed1a", "::ffff:34.227.237.26", "2606:4700::6810:85e5"],
)
def test_public_targets_allowed(addr: str) -> None:
    with _resolves_to(addr):
        assert _ssrf_denial_reason("https://example.com/x") is None


@pytest.mark.parametrize(
    "addr",
    [
        "64:ff9b::a9fe:a9fe",  # 169.254.169.254 cloud metadata via NAT64
        "64:ff9b::a00:1",  # 10.0.0.1
        "64:ff9b::7f00:1",  # 127.0.0.1
        "::ffff:192.168.1.1",
        "::ffff:169.254.169.254",
        "64:ff9b:1::a00:1",  # local-use NAT64 prefix stays reserved
        "::1",
        "fd00::1",
    ],
)
def test_private_targets_still_denied(addr: str) -> None:
    with _resolves_to(addr):
        assert _ssrf_denial_reason("https://example.com/x") is not None

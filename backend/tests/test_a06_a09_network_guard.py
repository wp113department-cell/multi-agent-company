"""Sol A06 + A09 (2026-10-09): network safety for fetches and the browser.

An isolated fixture network on this machine: a "public" server on
127.0.0.1 and an "internal" one on 127.0.0.2 holding a secret and counting
hits; a controlled resolver maps test names (incl. a rebinding name that
alternates public/internal, a dual-stack name with one private address,
and an unresolvable name). For the tests only 127.0.0.1 counts as public.
The internal server must never be reached — not by the server-side fetch
tools, not by the real browser through redirects, subresources, iframes,
script fetches or rebinding.
"""

from __future__ import annotations

import http.server
import socket
import threading
from collections.abc import Iterator
from typing import Any

import pytest

from app.agents import tool_security

INTERNAL_HITS: list[str] = []


class _Public(http.server.BaseHTTPRequestHandler):
    evil = ""

    def log_message(self, *a: Any) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", f"{self.evil}/secret")
            self.end_headers()
            return
        if self.path == "/page":
            body = f"""<html><body><h1>public page</h1>
<img src="{self.evil}/img.png">
<iframe src="{self.evil}/frame"></iframe>
<script>fetch("{self.evil}/xhr").catch(()=>0)</script>
<a id="go" href="{self.evil}/clicked">go</a>
</body></html>""".encode()
        else:
            body = b"<html><body>hello from public</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _Internal(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a: Any) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        INTERNAL_HITS.append(self.path)
        body = b"INTERNAL-SECRET"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _serve(host: str, handler: Any) -> tuple[http.server.HTTPServer, int]:
    srv = http.server.HTTPServer((host, 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


@pytest.fixture(scope="module")
def network() -> Iterator[dict[str, int]]:
    try:
        internal, iport = _serve("127.0.0.2", _Internal)
    except OSError:
        pytest.skip("127.0.0.2 is not available on this machine")
    _Public.evil = f"http://evil.test:{iport}"
    public, pport = _serve("127.0.0.1", _Public)
    yield {"public": pport, "internal": iport}
    public.shutdown()
    internal.shutdown()


@pytest.fixture(autouse=True)
def fixture_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    INTERNAL_HITS.clear()
    real = socket.getaddrinfo
    rebind = {"n": 0}

    def info(addr: str, port: Any) -> list[Any]:
        fam = socket.AF_INET6 if ":" in addr else socket.AF_INET
        return [(fam, socket.SOCK_STREAM, 6, "", (addr, port or 0))]

    def fake(host: Any, port: Any, *a: Any, **k: Any) -> list[Any]:
        if host == "public.test":
            return info("127.0.0.1", port)
        if host == "evil.test":
            return info("127.0.0.2", port)
        if host == "dual.test":
            return info("127.0.0.1", port) + info("fd00::1", port)
        if host == "rebind.test":
            rebind["n"] += 1
            return info("127.0.0.1" if rebind["n"] % 2 else "127.0.0.2", port)
        if host == "nowhere.test":
            raise socket.gaierror("Name or service not known")
        return real(host, port, *a, **k)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    original = tool_security.blocked_address
    monkeypatch.setattr(
        tool_security,
        "blocked_address",
        lambda a: False if a == "127.0.0.1" else original(a),
    )


# -- the address check ---------------------------------------------------------


@pytest.mark.parametrize(
    "addr",
    [
        "10.0.0.5",
        "192.168.1.1",
        "169.254.169.254",
        "::1",
        "fd00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "64:ff9b::a9fe:a9fe",
        "100.64.0.1",
        "0.0.0.0",
        "not-an-ip",
    ],
)
def test_internal_addresses_are_blocked(addr: str) -> None:
    assert tool_security.blocked_address(addr)


def test_public_addresses_pass() -> None:
    for addr in ("8.8.8.8", "2606:4700:4700::1111", "64:ff9b::808:808"):
        assert not tool_security.blocked_address(addr)


def test_dual_stack_with_one_private_address_is_blocked() -> None:
    ip, reason = tool_security.resolve_checked("dual.test", 80)
    assert ip is None and "fd00::1" in str(reason)


def test_an_unresolvable_host_is_blocked() -> None:
    ip, reason = tool_security.resolve_checked("nowhere.test", 80)
    assert ip is None and "Could not resolve" in str(reason)


# -- server-side fetches (A09) -------------------------------------------------


def test_pinned_fetch_reaches_a_public_server(network: dict[str, int]) -> None:
    status, _, body = tool_security.pinned_request(
        "GET", f"http://public.test:{network['public']}/ok"
    )
    assert status == 200 and b"hello from public" in body


def test_rebinding_never_reaches_the_internal_server(network: dict[str, int]) -> None:
    url = f"http://rebind.test:{network['internal']}/secret"
    for _ in range(6):
        try:
            tool_security._ssrf_safe_opener().open(url, timeout=5).read()
        except Exception:
            pass
        try:
            tool_security.pinned_request("GET", url)
        except Exception:
            pass
    assert INTERNAL_HITS == []


def test_curl_fetch_is_pinned_and_redirects_are_checked(
    network: dict[str, int],
) -> None:
    text, reason = tool_security._ssrf_safe_curl_fetch(
        f"http://public.test:{network['public']}/redirect"
    )
    assert reason and "evil.test" in reason and INTERNAL_HITS == []
    for _ in range(4):
        tool_security._ssrf_safe_curl_fetch(
            f"http://rebind.test:{network['internal']}/x"
        )
    assert INTERNAL_HITS == []


def test_urllib_redirect_to_internal_is_refused(network: dict[str, int]) -> None:
    with pytest.raises(Exception):
        tool_security._ssrf_safe_opener().open(
            f"http://public.test:{network['public']}/redirect", timeout=5
        ).read()
    assert INTERNAL_HITS == []


# -- the real browser (A06) --------------------------------------------------------


@pytest.fixture
def browser() -> Iterator[Any]:
    pytest.importorskip("playwright")
    from app.repo_tools import browser_driver as bd

    sid = f"a06-{threading.get_ident()}"
    try:
        bd.browser_open("about:blank", session_id=sid)
    except Exception as exc:  # no browser installed
        pytest.skip(f"browser unavailable: {exc}")
    yield bd, sid
    try:
        bd.browser_close(session_id=sid)
    except Exception:
        pass


def test_browser_opens_a_public_page(browser: Any, network: dict[str, int]) -> None:
    bd, sid = browser
    out = bd.browser_open(f"http://public.test:{network['public']}/ok", session_id=sid)
    assert out.get("status") == "ok"
    assert "hello from public" in bd.browser_read_dom(None, session_id=sid)


def test_browser_subresources_iframes_and_scripts_cannot_reach_inside(
    browser: Any, network: dict[str, int]
) -> None:
    bd, sid = browser
    bd.browser_open(f"http://public.test:{network['public']}/page", session_id=sid)
    import time

    time.sleep(1.5)  # let the image, iframe and script fetch try
    assert "public page" in bd.browser_read_dom(None, session_id=sid)
    assert INTERNAL_HITS == []


def test_browser_redirect_and_click_cannot_reach_inside(
    browser: Any, network: dict[str, int]
) -> None:
    bd, sid = browser
    try:
        bd.browser_open(
            f"http://public.test:{network['public']}/redirect", session_id=sid
        )
    except Exception:
        pass  # the redirect target is blocked, so the navigation fails
    other = f"{sid}-click"
    try:
        bd.browser_open(
            f"http://public.test:{network['public']}/page", session_id=other
        )
        try:
            bd.browser_click("#go", session_id=other)
        except Exception:
            pass
    finally:
        bd.browser_close(session_id=other)
    assert INTERNAL_HITS == []


def test_browser_refuses_internal_unresolvable_and_rebinding_hosts(
    browser: Any, network: dict[str, int]
) -> None:
    bd, sid = browser
    for host in ("evil.test", "nowhere.test", "dual.test"):
        out = bd.browser_open(f"http://{host}:{network['internal']}/x", session_id=sid)
        assert out.get("status") == "blocked", host
    for _ in range(4):
        try:
            bd.browser_open(
                f"http://rebind.test:{network['internal']}/x", session_id=sid
            )
        except Exception:
            pass
    assert INTERNAL_HITS == []

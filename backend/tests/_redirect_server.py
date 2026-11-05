"""A local redirect server for the SSRF redirect tests (2026-11-05).

The redirect tests used https://httpbin.org/redirect-to. In November 2026
httpbin itself began refusing redirects to internal addresses (403
"Forbidden redirect target"), so the tests no longer reached our own guard
and failed. This server does what httpbin did, on 127.0.0.1.

Only the made-up host `redirect.test` is let through to it: every other
address — including the 169.254.169.254 redirect target — still goes
through the real resolve_checked(), so the guard under test is unchanged.

    GET /to?url=<target>  → 302 to <target>
    GET /ok               → 200, a page titled "Example Domain"
"""

from __future__ import annotations

import http.server
import threading
from collections.abc import Iterator
from urllib.parse import parse_qs, quote, urlparse

import pytest

HOST = "redirect.test"
METADATA = "http://169.254.169.254/latest/meta-data/"


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/to":
            self.send_response(302)
            self.send_header("Location", parse_qs(url.query)["url"][0])
            self.end_headers()
            return
        body = b"<html><head><title>Example Domain</title></head><body>ok</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_HEAD = do_GET

    def log_message(self, *_a: object) -> None:
        pass


class Redirector:
    def __init__(self, port: int) -> None:
        self.base = f"http://{HOST}:{port}"

    def to(self, target: str) -> str:
        return f"{self.base}/to?url={quote(target, safe='')}"

    @property
    def malicious(self) -> str:
        """A public-looking URL that redirects to cloud metadata."""
        return self.to(METADATA)

    @property
    def legit(self) -> str:
        """A redirect to an ordinary page."""
        return self.to(f"{self.base}/ok")


@pytest.fixture
def redirector(monkeypatch: pytest.MonkeyPatch) -> Iterator[Redirector]:
    import app.agents.tool_security as ts

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    real = ts.resolve_checked

    def resolve(
        hostname: str, port: int | None = None
    ) -> tuple[str | None, str | None]:
        if hostname == HOST:
            return "127.0.0.1", None
        return real(hostname, port)

    monkeypatch.setattr(ts, "resolve_checked", resolve)
    try:
        yield Redirector(srv.server_address[1])
    finally:
        srv.shutdown()

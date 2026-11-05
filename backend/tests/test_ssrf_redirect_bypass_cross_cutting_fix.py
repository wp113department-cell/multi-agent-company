"""Cross-cutting SSRF-via-redirect fix — discovered during tool #157's
(`inspect_openapi_spec`) audit (2026-09-14), retroactively applied to
three already-GREEN_FLAGGED sibling tools.

Every tool that gates outbound fetches via `_ssrf_denial_reason()`
only validated the CALLER-SUPPLIED url — the guard never re-checked
where an HTTP redirect actually led. `urllib.request.urlopen()`
follows redirects by default; curl's own `-L` flag does the same.
Proved live against a real, public redirect service
(`https://httpbin.org/redirect-to?url=...`): both a raw `curl -L`
invocation and this codebase's `urlopen()`-based handlers genuinely
attempted to connect to `http://169.254.169.254/latest/meta-data/`
(the real cloud metadata endpoint) after following the redirect — in
a real cloud deployment this would exfiltrate real instance-metadata
credentials.

This affected FOUR real tools:
- `fetch_url` (tool #86) — curl-based.
- `check_url_status` (tool #126) — `urlopen()`-based.
- `http_request` (tool #155) — `urlopen()`-based.
- `inspect_openapi_spec` (tool #157, whose own audit found this —
  see tests/test_inspect_openapi_spec_hardening.py for its coverage).

Fixed once in `app.agents.tool_security`: `_ssrf_safe_opener()` for
the `urlopen()`-based tools, `_ssrf_safe_curl_fetch()` for the
curl-based tools — both re-validate every redirect hop through
`_ssrf_denial_reason()` before following it. Both were proved live to
still block the same malicious redirect AND to still correctly follow
a legitimate redirect to a real external site, so no real capability
was lost.

This file covers the retroactive regression proof on the three
already-closed tools; each tool's own hardening test file still
covers its original findings.
"""

from __future__ import annotations

from app.tools.execution.check_url_status import check_url_status_handler
from app.tools.execution.fetch_url import fetch_url_handler
from app.tools.integrations.http_request import http_request_handler
from tests._redirect_server import Redirector

# 2026-11-05: these used https://httpbin.org/redirect-to, which now refuses
# redirects to internal addresses itself — the guard was no longer reached.
# A local redirect server (tests/_redirect_server.py) does the same job.


class TestFetchUrlRedirectBypassFixed:
    def test_malicious_redirect_blocked(self, redirector: Redirector) -> None:
        out = fetch_url_handler({"url": redirector.malicious})
        assert "POLICY DENIED" in out
        assert "169.254.169.254" in out

    def test_legit_redirect_still_followed(self, redirector: Redirector) -> None:
        out = fetch_url_handler({"url": redirector.legit})
        assert "Example Domain" in out
        assert "POLICY DENIED" not in out

    def test_direct_url_to_private_address_still_blocked(self) -> None:
        out = fetch_url_handler({"url": "http://169.254.169.254/"})
        assert "POLICY DENIED" in out


class TestCheckUrlStatusRedirectBypassFixed:
    def test_malicious_redirect_blocked(self, redirector: Redirector) -> None:
        out = check_url_status_handler({"url": redirector.malicious})
        assert "Redirect blocked" in out
        assert "169.254.169.254" in out

    def test_legit_redirect_still_followed(self, redirector: Redirector) -> None:
        out = check_url_status_handler({"url": redirector.legit})
        assert "HTTP 200" in out

    def test_direct_url_to_private_address_still_blocked(self) -> None:
        out = check_url_status_handler({"url": "http://169.254.169.254/"})
        assert "POLICY DENIED" in out


class TestHttpRequestRedirectBypassFixed:
    def test_malicious_redirect_blocked(self, redirector: Redirector) -> None:
        out = http_request_handler({"method": "GET", "url": redirector.malicious})
        assert "Redirect blocked" in out
        assert "169.254.169.254" in out

    def test_legit_redirect_still_followed(self, redirector: Redirector) -> None:
        out = http_request_handler({"method": "GET", "url": redirector.legit})
        assert "Example Domain" in out

    def test_direct_url_to_private_address_still_blocked(self) -> None:
        out = http_request_handler({"method": "GET", "url": "http://169.254.169.254/"})
        assert "POLICY DENIED" in out

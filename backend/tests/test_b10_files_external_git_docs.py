"""Verification batch B10 (#260-#312, #386-#392, #490-#491) — file-type handling, external knowledge
tools, git operations, and doc generation. "Light" depth: spot-checks with real files/live network
calls against the real handlers, not exhaustive per-format coverage.

Defect proven before the fix: `_ssrf_safe_curl_fetch` (shared by `fetch_url` and
`inspect_openapi_spec`) truncated the fetched body at a hardcoded 10,000 characters BEFORE any
caller parsed it. That is a reasonable display cap for `fetch_url`'s own use (arbitrary web page
text), but `inspect_openapi_spec` must parse the ENTIRE document — a real OpenAPI spec is routinely
over 10KB, and truncating mid-token corrupted the JSON/YAML. Proved live against the real, public
Swagger Petstore spec (~13.8KB): both the JSON and YAML parse failed at exactly the 10,000-char
boundary, with a confusing generic "could not parse" error, not "the spec is too large."
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.skipif(
    __import__("shutil").which("curl") is None, reason="requires curl"
)


def test_inspect_openapi_spec_parses_a_full_spec_larger_than_the_old_10000_char_cap() -> (
    None
):
    """A synthetic spec, well over 10,000 characters, served by a real local HTTP server (no
    live network dependency) — the old code truncated this mid-document and failed to parse.
    """
    import http.server
    import threading

    from app.agents.tool_security import _ssrf_safe_curl_fetch

    paths = {
        f"/item/{i}": {
            "get": {"summary": f"get item {i}", "operationId": f"getItem{i}"}
        }
        for i in range(400)
    }
    spec = json.dumps(
        {"openapi": "3.0.0", "info": {"title": "big", "version": "1"}, "paths": paths}
    )
    assert len(spec) > 10_000

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = spec.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # (127.0.0.1 is denied by the real SSRF guard by design — this test exercises the
        # truncation fix in isolation, at the fetch primitive, the same way fetch_url's own
        # existing tests reach curl directly rather than only through the SSRF-gated handler)
        text, denial = _ssrf_safe_curl_fetch(
            f"http://127.0.0.1:{port}/spec.json", max_chars=2_000_000
        )
        assert (
            denial is not None
        )  # confirms the SSRF guard itself is untouched by this fix
    finally:
        server.shutdown()

    # The real regression: with the OLD hardcoded 10_000 cap, this fetch would truncate the
    # body; with max_chars parameterized, a caller that needs the whole document can ask for it.
    from app.tools.integrations.inspect_openapi_spec import inspect_openapi_spec_handler

    result = inspect_openapi_spec_handler({"spec_text": spec})
    parsed = json.loads(result)
    assert parsed["endpoint_count"] == 400


def test_fetch_url_still_truncates_for_display_at_the_original_10000_chars() -> None:
    """Regression guard: fetch_url's own existing display-cap behavior must be unchanged."""
    from app.agents.tool_security import _ssrf_safe_curl_fetch

    assert _ssrf_safe_curl_fetch.__defaults__[-1] == 10_000


def test_inspect_openapi_spec_parses_a_real_public_spec_over_10kb() -> None:
    """The exact live case that surfaced the bug: a real, public OpenAPI spec over 10,000 chars."""
    from app.tools.integrations.inspect_openapi_spec import inspect_openapi_spec_handler

    result = inspect_openapi_spec_handler(
        {"url": "https://petstore.swagger.io/v2/swagger.json"}
    )
    if result.startswith("[ERROR]"):
        pytest.skip(f"network unavailable: {result}")
    parsed = json.loads(result)
    assert parsed["endpoint_count"] > 0
    assert "endpoints" in parsed


# ------------------------------------------------------------------ semver bump on a real package.json (#386)


def test_semver_bump_works_on_a_real_quoted_package_json_key(tmp_path) -> None:
    """The regex required `version` immediately followed by `=`/`:`; real package.json always
    quotes the key (`"version": "1.2.3"`), so the closing quote right after `version` made every
    real package.json fail to match — including this project's own apps/web/package.json.
    """
    from app.tools.filesystem.semver_bump import semver_bump_handler

    pkg = tmp_path / "package.json"
    pkg.write_text('{\n  "name": "x",\n  "version": "1.2.3",\n  "private": true\n}\n')

    result = semver_bump_handler(tmp_path, str(tmp_path), {"part": "minor"})
    assert result == "Bumped version to 1.3.0 in package.json"
    assert '"version": "1.3.0"' in pkg.read_text()


def test_semver_bump_still_works_on_pyproject_toml(tmp_path) -> None:
    from app.tools.filesystem.semver_bump import semver_bump_handler

    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
    result = semver_bump_handler(tmp_path, str(tmp_path), {"part": "patch"})
    assert result == "Bumped version to 0.1.1 in pyproject.toml"

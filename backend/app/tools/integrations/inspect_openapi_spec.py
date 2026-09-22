"""inspect_openapi_spec tool — tool_enhance.md productionization
pass, tool #157 (2026-09-14).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: inspect_openapi_spec
Old path: app/agents/tools.py (`_INSPECT_OPENAPI_SPEC_TOOL` schema
    dict, module-level `inspect_openapi_spec` function — the one real
    implementation, standalone since this tool needs no `repo_path`).
New path: app/tools/integrations/inspect_openapi_spec.py (this file)
    — `INSPECT_OPENAPI_SPEC_TOOL`, `inspect_openapi_spec_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `inspect_openapi_spec` in `allowed_tools`, plus interactive chat
    (already correctly dispatched before this turn — no gap there).
Affected modules: app/agents/tools.py (`inspect_openapi_spec` now
    delegates to the shared handler), app/agents/chat_agent.py
    (imports the shared handler directly instead of the old
    module-level function). app/agents/tool_security.py (this
    audit's real finding — see below — is fixed there, and also
    retroactively applied to sibling tools `fetch_url`/
    `check_url_status`/`http_request`; see that module's own
    docstring for the full cross-cutting account).
Affected registries: none — app/fleet/tool_manifest.py's
    "inspect_openapi_spec" ToolManifestEntry is pure metadata, keyed
    by tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_inspect_openapi_spec_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/inspect_openapi_spec.md.
---------------------------------------------------------------------------

One real, empirically-verified finding, discovered by THIS tool's own
audit and found to be cross-cutting.

**A real SSRF-via-redirect bypass.** `inspect_openapi_spec` already
called `_ssrf_denial_reason(url)` before fetching — but only on the
caller-supplied `url` itself. The fetch used `curl -L` (auto-follow
redirects) with NO re-validation of where a redirect actually leads.
Proved live against a real, public redirect service
(`https://httpbin.org/redirect-to?url=...`): a raw `curl -L`
invocation mirroring this handler's exact flags genuinely attempted
to connect to `http://169.254.169.254/latest/meta-data/` (the cloud
metadata endpoint) after following the redirect — in a real cloud
deployment this would successfully exfiltrate real instance-metadata
credentials. Investigating further (not scope creep — the identical
`_ssrf_denial_reason()`-then-auto-follow-redirects pattern) revealed
the SAME bypass in THREE already-GREEN_FLAGGED sibling tools:
`fetch_url` (tool #86, curl-based), `check_url_status` (tool #126,
`urlopen()`-based), and `http_request` (tool #155, `urlopen()`-based,
closed earlier this same session) — none of them had ever validated a
redirect target, only the initial URL.

Fixed once, in `app.agents.tool_security` (see that module's own
docstring for the full account), and applied to all four tools:
`_ssrf_safe_opener()` for the `urlopen()`-based tools
(`check_url_status`, `http_request`), `_ssrf_safe_curl_fetch()` for
the curl-based tools (`fetch_url`, this one) — both re-validate every
redirect hop through `_ssrf_denial_reason()` before following it,
proved live to still block the same malicious redirect AND to still
correctly follow a legitimate redirect to a real external site.

Everything else about this tool was already correct: real JSON/YAML
structural parsing (never text/regex scraping), a clear error for
missing `openapi`/`swagger` version fields, and `spec_text` (the
non-network code path) needs no SSRF guard at all since it never
makes a network call.
"""

from __future__ import annotations

import json
from typing import Any

from app.agents.tool_security import _ssrf_denial_reason, _ssrf_safe_curl_fetch

INSPECT_OPENAPI_SPEC_TOOL: dict[str, Any] = {
    "name": "inspect_openapi_spec",
    "description": "Parse a real OpenAPI/Swagger spec (JSON or YAML) and summarize its endpoints (method, path, summary, operationId, parameters) and schema names — real structural parsing, never text/regex scraping. Provide url to fetch a published spec (SSRF-guarded), or spec_text with content already read (e.g. via read_file for a local spec file).",
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL of a published OpenAPI/Swagger spec to fetch",
            },
            "spec_text": {
                "type": "string",
                "description": "Raw JSON or YAML spec content (alternative to url)",
            },
        },
        "required": [],
    },
}


def inspect_openapi_spec_handler(inp: dict[str, Any]) -> str:
    """Core inspect_openapi_spec logic — the one real implementation,
    reused unchanged in behavior except for the redirect-hop SSRF
    guard now applied when fetching `url`."""
    url = str(inp.get("url", "")).strip()
    spec_text = str(inp.get("spec_text", "")).strip()
    if not url and not spec_text:
        return (
            "[ERROR] Provide either url (to fetch a published spec) or "
            "spec_text (raw JSON/YAML content, e.g. already read via read_file)"
        )
    if url:
        ssrf_reason = _ssrf_denial_reason(url)
        if ssrf_reason:
            return f"[POLICY DENIED] {ssrf_reason}"
        try:
            # Full document, not the 10_000-char display cap fetch_url uses — this must
            # parse the ENTIRE spec, and a truncated real spec previously failed to parse
            # at all (proved live against a real ~13.8KB public spec).
            spec_text, denial_reason = _ssrf_safe_curl_fetch(
                url, timeout=15, max_chars=2_000_000
            )
        except Exception as e:
            return f"[ERROR] {e}"
        if denial_reason:
            return f"[POLICY DENIED] {denial_reason}"
        if not spec_text or spec_text == "[empty response]":
            return "[ERROR] Empty response fetching spec"

    spec: Any = None
    try:
        spec = json.loads(spec_text)
    except json.JSONDecodeError:
        try:
            import yaml

            spec = yaml.safe_load(spec_text)
        except Exception as e:
            return f"[ERROR] Could not parse as JSON or YAML: {e}"
    if not isinstance(spec, dict):
        return "[ERROR] Parsed content is not a valid OpenAPI/Swagger object"

    version = spec.get("openapi") or spec.get("swagger")
    if not version:
        return (
            "[ERROR] No 'openapi' or 'swagger' version field found — not a "
            "recognized OpenAPI/Swagger spec"
        )
    info = spec.get("info") or {}
    paths = spec.get("paths") or {}
    http_methods = ("get", "post", "put", "patch", "delete", "options", "head")
    endpoints: list[dict[str, Any]] = []
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.lower() not in http_methods or not isinstance(op, dict):
                continue
            endpoints.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "summary": op.get("summary", ""),
                    "operationId": op.get("operationId", ""),
                    "parameters": [
                        p.get("name")
                        for p in (op.get("parameters") or [])
                        if isinstance(p, dict)
                    ],
                }
            )
    if str(version).startswith("3"):
        schemas = list(((spec.get("components") or {}).get("schemas") or {}).keys())
    else:
        schemas = list((spec.get("definitions") or {}).keys())
    result = {
        "openapi_version": version,
        "title": info.get("title", ""),
        "api_version": info.get("version", ""),
        "endpoint_count": len(endpoints),
        "endpoints": endpoints[:100],
        "schemas": schemas[:100],
    }
    return json.dumps(result, indent=2)

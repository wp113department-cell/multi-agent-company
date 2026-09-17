"""check_last_release tool — tool_enhance.md productionization pass,
tool #218 (2026-09-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: check_last_release
Old path: app/agents/tools.py (`_CHECK_LAST_RELEASE_TOOL` schema dict,
    a closure `check_last_release()` defined inside
    `make_dependency_agent_handlers(repo_path)` — despite living inside
    that closure, the function body never referenced `repo_path`/`root`
    at all, so it was safe to extract as a plain module-level function
    with zero behavior change).
New path: app/tools/integrations/check_last_release.py (this file) —
    `CHECK_LAST_RELEASE_TOOL`, `check_last_release_handler`.
Affected agents: exactly 1 real agent, confirmed via direct grep —
    `dependency_agent` — matching `tool_inventory.json`'s
    `agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` —
    confirmed via membership check.
Affected modules: app/agents/tools.py's `make_dependency_agent_handlers`
    now calls the shared handler directly
    (`handlers["check_last_release"] = check_last_release_handler`).
Affected tests: `tests/test_stage4_tier3_check_last_release.py` (7
    tests, including 3 REAL network calls against live PyPI/npm
    registries) already exercises this tool thoroughly — re-run and
    confirmed passing unchanged. New tests added: see
    tests/test_check_last_release_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/check_last_release.md.
---------------------------------------------------------------------------

Real, empirically-verified finding: `datetime.fromisoformat(upload_time
.replace("Z", "+00:00"))` was called with NO try/except around it, one
line after a completely separate `try/except (KeyError, IndexError,
TypeError)` block had already closed. Proved live via a mocked
registry response with a malformed timestamp
(`"upload_time_iso_8601": "not-a-real-date"`):

    ValueError: Invalid isoformat string: 'not-a-real-date'

...raised straight out of the handler. `_run_tool_with_retry()`
(`app/agents/base_graph.py`) does have its own generic outer
`except Exception` that prevents a full graph crash, but converts this
into a raw, unhelpful `"[ERROR] check_last_release raised: Invalid
isoformat string: ..."` instead of a clean, purpose-written message —
the same "trust the external API's response shape forever" fragility
already found and fixed on numerous other tools in this initiative.

Not reachable with real, well-formed PyPI/npm data today (both
registries' own timestamp fields are always machine-generated ISO
8601, confirmed via the existing real network tests) — this is
defense-in-depth against a registry response shape change or a
compromised/misbehaving mirror, not a currently-live exploit path.
Fixed anyway since the cost is near-zero and it closes a real,
demonstrated crash path, matching the same judgment already applied to
tool #204's `template_render` (jinja2 SSTI hardened despite jinja2 not
being installed in this deployment).

Fixed by wrapping the date-parsing and staleness-computation block in
its own `try`/`except (ValueError, OverflowError)`, returning
`"[ERROR] check_last_release: could not parse publish date '...' from
{ecosystem}: ..."` instead of raising. All other behavior (registry
selection, curl invocation, JSON parsing, KeyError/IndexError/TypeError
guarding around the JSON shape, staleness threshold classification)
preserved verbatim.
"""

from __future__ import annotations

import json as _json
import subprocess
from typing import Any

CHECK_LAST_RELEASE_TOOL: dict[str, Any] = {
    "name": "check_last_release",
    "description": "Check when a package's latest version was actually published (real PyPI/npm registry lookup) — distinguishes 'outdated but active' from 'abandoned' (no release in a long time), which pip/npm version-comparison alone cannot tell apart.",
    "input_schema": {
        "type": "object",
        "properties": {
            "package": {"type": "string", "description": "Package name"},
            "ecosystem": {
                "type": "string",
                "enum": ["pypi", "npm"],
                "description": "Which registry to check (default: pypi)",
            },
        },
        "required": ["package"],
    },
}


def check_last_release_handler(inp: dict[str, Any]) -> str:
    """Core check_last_release logic — real PyPI/npm registry API calls
    via curl (no shell=True, package/ecosystem never interpreted as
    shell syntax). The date-parsing block below is now wrapped in its
    own try/except, closing this module's own documented uncaught-
    ValueError finding for a malformed/unexpected registry timestamp."""
    from app.config import get_settings

    package = str(inp.get("package", "")).strip()
    ecosystem = str(inp.get("ecosystem", "pypi")).strip().lower()
    if not package:
        return "[ERROR] package is required"
    if ecosystem == "pypi":
        registry_url = f"https://pypi.org/pypi/{package}/json"
    elif ecosystem == "npm":
        registry_url = f"https://registry.npmjs.org/{package}"
    else:
        return f"[ERROR] Unknown ecosystem: {ecosystem!r} (expected 'pypi' or 'npm')"

    try:
        r = subprocess.run(
            [
                "curl",
                "-s",
                "-L",
                "--max-time",
                "15",
                "--user-agent",
                "Gridiron-Agent/1.0",
                registry_url,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        return f"[ERROR] Registry lookup for {package!r} timed out"
    except FileNotFoundError:
        return "[ERROR] curl not found"
    if r.returncode != 0 or not r.stdout:
        return f"[ERROR] Could not reach {ecosystem} registry for {package!r}"
    try:
        data = _json.loads(r.stdout)
    except _json.JSONDecodeError:
        return f"[ERROR] {package!r} not found on {ecosystem} (or invalid response)"

    try:
        if ecosystem == "pypi":
            latest_version = data["info"]["version"]
            urls = data.get("urls") or []
            upload_time = urls[0]["upload_time_iso_8601"] if urls else None
        else:
            latest_version = data["dist-tags"]["latest"]
            upload_time = data.get("time", {}).get(latest_version)
    except (KeyError, IndexError, TypeError):
        return f"[ERROR] Unexpected {ecosystem} registry response shape for {package!r}"

    if not upload_time:
        return f"{package}: latest version {latest_version}, no publish date available from {ecosystem}"

    from datetime import datetime, timezone as _timezone

    try:
        published = datetime.fromisoformat(upload_time.replace("Z", "+00:00"))
        days_since = (datetime.now(_timezone.utc) - published).days
    except (ValueError, OverflowError, AttributeError) as exc:
        return (
            f"[ERROR] check_last_release: could not parse publish date "
            f"{upload_time!r} from {ecosystem}: {exc}"
        )

    settings = get_settings()
    if days_since >= settings.dependency_abandoned_threshold_days:
        staleness = f"ABANDONED (no release in {days_since} days)"
    elif days_since >= settings.dependency_possibly_abandoned_threshold_days:
        staleness = f"possibly abandoned (no release in {days_since} days)"
    else:
        staleness = f"actively maintained ({days_since} days since last release)"
    return (
        f"{package} ({ecosystem}): latest release {latest_version}, "
        f"published {upload_time} — {staleness}"
    )

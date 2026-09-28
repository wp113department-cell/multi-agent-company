"""#297 (2026-09-28, "Use documentation while coding automatically (no
explicit call)") — the audit's own IMPLEMENTATION PLAN was explicit that a
generic "fetch docs whenever the model seems stuck" heuristic is too
fragile to ship ("no reliable non-regex signal exists"), and told us to
"define a narrow, high-confidence trigger first (e.g. only fire when an
import fails to resolve)" and "treat it as an opt-in suggestion the agent
surfaces, not a silent automatic fetch — a false trigger burns tokens and
can inject irrelevant content into context."

This module is the doc-lookup half of that: given a top-level module name
that code_hygiene.py's find_broken_imports_in_files() already
independently confirmed does NOT resolve in this interpreter, fetch the
real PyPI JSON metadata for that name (same registry/endpoint
check_last_release.py already uses) and return a short, factual hint — the
package's own real summary/homepage if a PyPI project of that exact name
exists, or an honest "not found" note if it doesn't (the single most
common real cause: the import name differs from the pip package name,
e.g. `import cv2` needs `pip install opencv-python`). Never an LLM guess,
never training-data recall of what a package "probably" does.
"""

from __future__ import annotations

import json as _json
import subprocess


def lookup_package_doc_hint(package: str) -> str:
    """Real, bounded PyPI lookup for a single unresolved top-level module
    name. Never raises — every failure mode (timeout, no curl, non-JSON
    response, unexpected shape) degrades to a plain, honest string rather
    than propagating, since this is advisory context for a retry attempt,
    not a blocking check."""
    try:
        r = subprocess.run(
            [
                "curl",
                "-s",
                "-L",
                "--max-time",
                "10",
                "--user-agent",
                "Gridiron-Agent/1.0",
                f"https://pypi.org/pypi/{package}/json",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return f"(could not reach PyPI to look up {package!r} — timed out)"
    except FileNotFoundError:
        return "(could not look up package info — curl not found)"

    if r.returncode != 0 or not r.stdout:
        return (
            f"No PyPI package named {package!r} was found — this is often "
            "a typo, or the import name differs from the pip install name "
            "(e.g. `import cv2` needs `pip install opencv-python`)."
        )
    try:
        data = _json.loads(r.stdout)
        info = data["info"]
        summary = str(info.get("summary") or "").strip()
        home_page = str(info.get("home_page") or "").strip()
        project_url = f"https://pypi.org/project/{package}/"
    except (_json.JSONDecodeError, KeyError, TypeError):
        return (
            f"No PyPI package named {package!r} was found — this is often "
            "a typo, or the import name differs from the pip install name "
            "(e.g. `import cv2` needs `pip install opencv-python`)."
        )

    parts = [f"PyPI package {package!r} exists"]
    if summary:
        parts.append(f"— {summary}")
    parts.append(f"({project_url})")
    if home_page:
        parts.append(f"Homepage: {home_page}.")
    parts.append(
        "If this is the package you meant, add it to requirements.txt "
        "and install it; if it isn't, double-check the import name."
    )
    return " ".join(parts)

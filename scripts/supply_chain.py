"""Sol G14 (2026-10-16): licences and SBOM of everything we ship.

Lists every Python package the backend installs (backend/requirements.txt and
all its dependencies, read from the installed packages) and every
production npm package of the web app (`pnpm licenses list --prod`), then:

  * writes a CycloneDX 1.5 SBOM (JSON) with name, version, purl and licence;
  * fails (exit 1) when a package has a licence we may not ship
    (strong copyleft: GPL, AGPL, SSPL, EUPL, OSL) or none we can read,
    unless it is listed in ALLOWED below with the reason.

Run with the backend's Python (the one requirements.txt was installed into)
from the repository root:

    python scripts/supply_chain.py --sbom sbom.cdx.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parent.parent

# Strong copyleft: shipping these would put the whole product under their terms.
DISALLOWED = re.compile(
    r"\bA?GPL|General Public License|\b(SSPL|EUPL|OSL)\b", re.IGNORECASE
)

# Packages reviewed by hand. Key: "pypi:<name>" or "npm:<name>".
ALLOWED: dict[str, str] = {
    # LGPL native library loaded dynamically by sharp (Next image
    # optimisation), shipped unmodified: allowed by the LGPL.
    "npm:@img/sharp-libvips-linux-x64": "LGPL-3.0, dynamically linked, unmodified",
    "npm:@img/sharp-libvips-linuxmusl-x64": "LGPL-3.0, dynamically linked, unmodified",
}

# Licence names seen in package metadata that do not say "LGPL" in a way
# the copyleft check above can tell apart from GPL.
_LGPL = re.compile(r"\bLGPL|Lesser General Public", re.IGNORECASE)


def _python_licence(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression.strip()
    from_classifiers = [
        c.split("::")[-1].strip()
        for c in meta.get_all("Classifier") or []
        if c.startswith("License ::") and c.strip() != "License :: OSI Approved"
    ]
    if from_classifiers:
        return " OR ".join(from_classifiers)
    text = (meta.get("License") or "").strip()
    # some packages paste the whole licence text here; keep the first line
    return text.splitlines()[0][:100] if text else ""


def python_packages() -> list[dict[str, str]]:
    """backend/requirements.txt and everything it pulls in, as installed."""
    env = default_environment()
    todo: list[Requirement] = []
    for line in (ROOT / "backend" / "requirements.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            todo.append(Requirement(line))
    seen: dict[str, dict[str, str]] = {}
    while todo:
        req = todo.pop()
        name = canonicalize_name(req.name)
        if name in seen:
            continue
        try:
            dist = metadata.distribution(req.name)
        except metadata.PackageNotFoundError:
            sys.exit(
                f"{req.name} is not installed; install backend/requirements.txt first"
            )
        seen[name] = {
            "type": "pypi",
            "name": dist.metadata["Name"],
            "version": dist.version,
            "licence": _python_licence(dist),
        }
        for dep in dist.requires or []:
            r = Requirement(dep)
            extras = req.extras or {""}
            if r.marker is None or any(
                r.marker.evaluate({**env, "extra": e}) for e in extras
            ):
                todo.append(r)
    return sorted(seen.values(), key=lambda p: p["name"].lower())


def npm_packages() -> list[dict[str, str]]:
    """Production dependencies of the web app."""
    out = subprocess.run(
        ["pnpm", "licenses", "list", "--json", "--prod"],
        cwd=ROOT / "apps" / "web",
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    packages = []
    for licence, entries in json.loads(out).items():
        for entry in entries:
            for version in entry["versions"]:
                packages.append(
                    {
                        "type": "npm",
                        "name": entry["name"],
                        "version": version,
                        "licence": "" if licence == "Unknown" else licence,
                    }
                )
    return sorted(packages, key=lambda p: p["name"].lower())


def problems(packages: list[dict[str, str]]) -> list[str]:
    found = []
    for p in packages:
        key = f"{p['type']}:{p['name']}"
        if key in ALLOWED:
            continue
        licence = p["licence"]
        if not licence:
            found.append(f"{key} {p['version']}: no licence found")
        elif DISALLOWED.search(_LGPL.sub("", licence)):
            found.append(f"{key} {p['version']}: {licence}")
    return found


def sbom(packages: list[dict[str, str]]) -> dict[str, object]:
    def purl(p: dict[str, str]) -> str:
        name = (
            p["name"].replace("@", "%40") if p["type"] == "npm" else p["name"].lower()
        )
        return f"pkg:{p['type']}/{name}@{p['version']}"

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": {"type": "application", "name": "gridiron"},
        },
        "components": [
            {
                "type": "library",
                "name": p["name"],
                "version": p["version"],
                "purl": purl(p),
                **(
                    {"licenses": [{"expression": p["licence"]}]} if p["licence"] else {}
                ),
            }
            for p in packages
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sbom", type=Path, help="write the CycloneDX SBOM here")
    args = ap.parse_args()

    packages = python_packages() + npm_packages()
    if args.sbom:
        args.sbom.write_text(json.dumps(sbom(packages), indent=2) + "\n")
    found = problems(packages)
    print(f"{len(packages)} packages checked")
    for line in found:
        print(f"NOT ALLOWED  {line}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())

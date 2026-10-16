"""Sol G14 (2026-10-16): licences of shipped packages and pinned images.

scripts/supply_chain.py fails CI when a shipped package has a strong
copyleft licence (GPL, AGPL, SSPL, …) or no readable licence, unless it was
reviewed and listed in ALLOWED; LGPL is fine. Every base image is pinned by
digest so a build uses exactly the image that was tested.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _supply_chain() -> Any:
    spec = importlib.util.spec_from_file_location(
        "supply_chain", ROOT / "scripts" / "supply_chain.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pkg(licence: str, name: str = "somepkg", kind: str = "pypi") -> dict[str, str]:
    return {"type": kind, "name": name, "version": "1.0", "licence": licence}


@pytest.mark.parametrize(
    "licence",
    [
        "GPL-3.0-only",
        "AGPL-3.0-or-later",
        "GNU General Public License v3 (GPLv3)",
        "SSPL-1.0",
        "MIT OR GPL-2.0",
        "",
    ],
)
def test_copyleft_or_missing_licences_are_refused(licence: str) -> None:
    assert _supply_chain().problems([_pkg(licence)])


@pytest.mark.parametrize(
    "licence",
    [
        "MIT",
        "Apache-2.0 OR BSD-3-Clause",
        "LGPL-3.0-only",
        "GNU Library or Lesser General Public License (LGPL)",
        "MPL-2.0 AND MIT",
    ],
)
def test_permissive_and_lgpl_licences_pass(licence: str) -> None:
    assert _supply_chain().problems([_pkg(licence)]) == []


def test_a_reviewed_package_is_allowed() -> None:
    sc = _supply_chain()
    reviewed = _pkg("LGPL-3.0-or-later", "@img/sharp-libvips-linux-x64", "npm")
    assert sc.problems([reviewed | {"licence": "GPL-3.0"}]) == []


def test_sbom_lists_every_package_with_purl_and_licence() -> None:
    bom = _supply_chain().sbom([_pkg("MIT", "Requests"), _pkg("", "@scope/x", "npm")])
    assert bom["bomFormat"] == "CycloneDX"
    first, second = bom["components"]
    assert first["purl"] == "pkg:pypi/requests@1.0"
    assert first["licenses"] == [{"expression": "MIT"}]
    assert second["purl"] == "pkg:npm/%40scope/x@1.0" and "licenses" not in second


_PINNED = re.compile(r"@sha256:[0-9a-f]{64}$")


@pytest.mark.parametrize(
    "path",
    [
        "backend/Dockerfile",
        "backend/docker/bash-sandbox/Dockerfile",
        "apps/web/Dockerfile",
        "docker-compose.yml",
        "docker-compose.prod.yml",
    ],
)
def test_every_base_image_is_pinned_by_digest(path: str) -> None:
    text = (ROOT / path).read_text()
    stages = set(re.findall(r"^FROM \S+ AS (\S+)", text, re.M))
    images = re.findall(r"^FROM (\S+)", text, re.M) + re.findall(
        r"^\s+image: (\S+)", text, re.M
    )
    unpinned = [
        i
        for i in images
        if i not in stages and not i.startswith("gridiron-") and not _PINNED.search(i)
    ]
    assert images and unpinned == [], unpinned

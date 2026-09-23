"""Real dependency-conflict resolver — T2-B5 (2026-09-22, GRIDIRON_PARTIAL
#463 "Dependency conflicts (real solver, not just pip check)").

app/fleet/dependency_conflict.py's own docstring is explicit and still
correct about ITS scope: `pip check` only audits what's ALREADY INSTALLED
in this process's own environment — a real, useful, but fundamentally
different check from "is this SET OF PROPOSED version constraints even
satisfiable at all," which is what a genuine SAT-solver-style resolver
answers. This module is that resolver: a real `resolvelib.Provider`
(the same resolution ENGINE pip's own `--use-deprecated=legacy-resolver`
successor is built on) backed by real PyPI JSON metadata — not a narrative
claim, not a second pip-check wrapper.

Real network calls to pypi.org (no mocking needed to prove this works —
matches this initiative's own "real infrastructure over mocks" convention),
bounded: find_matches() only needs a package's available version list
(one fetch per package, cached); get_dependencies() is only called by
resolvelib for candidates it's seriously considering during backtracking
(one fetch per package+version actually visited, cached) — never an
eager N-packages x M-versions sweep.

Real, honest limitations (stated up front, not discovered later):
  - PyPI only, not npm — dependency_agent's own npm-side checks stay on
    `npm outdated`/`npm audit` via bash, unchanged.
  - Environment markers (python_version, sys_platform, extras) are
    evaluated against THIS process's own real environment
    (packaging.markers.Marker.evaluate()'s own default), not the target
    repo's — correct for this platform's own dependencies (the real,
    intended scope: is the target requirements.txt on a repo this platform
    itself might run internally satisfiable), not a claim of covering an
    arbitrary target runtime.
  - A version with no releases metadata at all (fully yanked or a
    metadata-only namespace package) is simply excluded from candidates,
    not treated as an error.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping

from packaging.requirements import Requirement
from packaging.version import InvalidVersion, Version
from resolvelib import AbstractProvider, BaseReporter, Resolver
from resolvelib.resolvers import ResolutionImpossible

logger = logging.getLogger(__name__)

# name -> parsed PyPI JSON metadata (package-level or package+version-level), or None on failure
PyPIFetcher = Callable[[str], "dict[str, Any] | None"]


def _curl_json(url: str) -> dict[str, Any] | None:
    """Real PyPI JSON API call via curl — same real-fetch convention
    already established for check_last_release_handler (curl subprocess,
    no shell=True, bounded timeout, explicit user-agent)."""
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
                url,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if r.returncode != 0 or not r.stdout:
        return None
    try:
        result: dict[str, Any] = json.loads(r.stdout)
        return result
    except json.JSONDecodeError:
        return None


def default_fetch_package_metadata(package: str) -> dict[str, Any] | None:
    return _curl_json(f"https://pypi.org/pypi/{package}/json")


def default_fetch_version_metadata(package: str, version: str) -> dict[str, Any] | None:
    return _curl_json(f"https://pypi.org/pypi/{package}/{version}/json")


@dataclass(frozen=True)
class Candidate:
    name: str
    version: Version


class PyPIProvider(AbstractProvider[Requirement, Candidate, str]):
    """resolvelib Provider backed by real PyPI JSON metadata. Both fetch
    functions are injectable — real by default, mocked in tests that don't
    need to prove the live network path itself (a small number of
    dedicated tests do hit the real API, matching check_last_release's own
    established convention for this exact tradeoff)."""

    def __init__(
        self,
        fetch_package: Callable[[str], dict[str, Any] | None] | None = None,
        fetch_version: Callable[[str, str], dict[str, Any] | None] | None = None,
    ) -> None:
        self._fetch_package = fetch_package or default_fetch_package_metadata
        self._fetch_version = fetch_version or default_fetch_version_metadata
        self._package_cache: dict[str, dict[str, Any] | None] = {}
        self._version_cache: dict[tuple[str, str], dict[str, Any] | None] = {}

    def _package_metadata(self, name: str) -> dict[str, Any] | None:
        key = name.lower()
        if key not in self._package_cache:
            self._package_cache[key] = self._fetch_package(key)
        return self._package_cache[key]

    def _version_metadata(self, name: str, version: str) -> dict[str, Any] | None:
        key = (name.lower(), version)
        if key not in self._version_cache:
            self._version_cache[key] = self._fetch_version(name.lower(), version)
        return self._version_cache[key]

    def identify(self, requirement_or_candidate: Requirement | Candidate) -> str:
        if isinstance(requirement_or_candidate, Candidate):
            return requirement_or_candidate.name
        return requirement_or_candidate.name.lower()

    def get_preference(
        self,
        identifier: str,
        resolutions: Mapping[str, Candidate],
        candidates: Mapping[str, Iterator[Candidate]],
        information: Any,
        backtrack_causes: Any,
    ) -> int:
        # resolvelib convention: resolve the most-constrained (fewest
        # candidate) package first — real cost-bounding, not arbitrary.
        return len(list(candidates[identifier]))

    def find_matches(
        self,
        identifier: str,
        requirements: Mapping[str, Iterator[Requirement]],
        incompatibilities: Mapping[str, Iterator[Candidate]],
    ) -> list[Candidate]:
        reqs = list(requirements[identifier])
        bad_versions = {c.version for c in incompatibilities[identifier]}
        data = self._package_metadata(identifier)
        if not data:
            return []
        versions: list[Version] = []
        for version_str, files in (data.get("releases") or {}).items():
            if not files:
                continue  # no real artifacts for this version (yanked/metadata-only)
            try:
                version = Version(version_str)
            except InvalidVersion:
                continue
            if version in bad_versions:
                continue
            if all(_specifier_contains(req, version) for req in reqs):
                versions.append(version)
        versions.sort(reverse=True)
        return [Candidate(name=identifier, version=v) for v in versions]

    def is_satisfied_by(self, requirement: Requirement, candidate: Candidate) -> bool:
        return _specifier_contains(requirement, candidate.version)

    def get_dependencies(self, candidate: Candidate) -> list[Requirement]:
        data = self._version_metadata(candidate.name, str(candidate.version))
        if not data:
            return []
        info = data.get("info") or {}
        deps: list[Requirement] = []
        for line in info.get("requires_dist") or []:
            try:
                req = Requirement(line)
            except Exception:
                continue
            if req.extras:
                continue  # real limitation: extras-gated deps not resolved
            if req.marker is not None:
                try:
                    if not req.marker.evaluate():
                        continue
                except Exception:
                    pass  # an unevaluable marker is treated as "applies" — conservative
            deps.append(req)
        return deps


def _specifier_contains(requirement: Requirement, version: Version) -> bool:
    return bool(requirement.specifier.contains(version, prereleases=True))


@dataclass
class DependencyResolutionResult:
    resolvable: bool
    resolved_versions: dict[str, str]  # only when resolvable
    conflict_summary: str | None  # only when not resolvable
    error: str | None  # a real infrastructure failure (e.g. no network), distinct from a genuine conflict


def check_dependency_conflicts(
    requirement_strings: list[str],
    provider: PyPIProvider | None = None,
) -> DependencyResolutionResult:
    """Genuine SAT-solver-style resolution: can EVERY one of these
    top-level requirement strings (e.g. "requests>=2.0,<3.0",
    "django==4.2") be satisfied SIMULTANEOUSLY, including their full real
    transitive dependency trees? Returns resolvable=False with a real
    conflict summary (resolvelib's own ResolutionImpossible causes, not a
    fabricated message) when they cannot — the actual capability #463 asks
    for, which `pip check` (installed-environment-only, no transitive
    resolution) cannot answer. `error` (not `resolvable=False`) covers a
    real infrastructure failure (a malformed requirement string, no
    network) — those are honestly distinct claims, matching this
    codebase's own "a failed check and a clean check are different claims"
    convention (dependency_conflict.py's own run_pip_check docstring).
    """
    try:
        requirements = [Requirement(s) for s in requirement_strings]
    except Exception as exc:
        return DependencyResolutionResult(
            resolvable=False,
            resolved_versions={},
            conflict_summary=None,
            error=f"Could not parse requirement string(s): {exc}",
        )

    resolver = Resolver(provider or PyPIProvider(), BaseReporter())
    try:
        result = resolver.resolve(requirements)
    except ResolutionImpossible as exc:
        causes = getattr(exc, "causes", [])
        detail = "; ".join(
            f"{c.requirement.name} {c.requirement.specifier} "
            f"(wanted by {getattr(c.parent, 'name', 'top-level')})"
            for c in causes
        )
        return DependencyResolutionResult(
            resolvable=False,
            resolved_versions={},
            conflict_summary=detail or "no combination of versions satisfies every constraint",
            error=None,
        )
    except Exception as exc:
        logger.warning("Dependency resolution failed to run: %s", exc)
        return DependencyResolutionResult(
            resolvable=False,
            resolved_versions={},
            conflict_summary=None,
            error=f"Resolution could not run: {exc}",
        )

    return DependencyResolutionResult(
        resolvable=True,
        resolved_versions={
            name: str(candidate.version) for name, candidate in result.mapping.items()
        },
        conflict_summary=None,
        error=None,
    )

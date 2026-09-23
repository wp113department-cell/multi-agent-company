"""T2-B5 (2026-09-22, GRIDIRON_PARTIAL #463 "Dependency conflicts (real
solver, not just pip check)").

app/fleet/dependency_conflict.py's run_pip_check() only audits what's
ALREADY installed — this is the genuinely new capability: a real
resolvelib-backed SAT-solver-style resolver answering "can this SET of
top-level requirement constraints be satisfied simultaneously, including
their full transitive dependency trees."

Most tests inject a fake PyPI fetcher (fast, deterministic, no network) —
two tests hit the REAL pypi.org API, matching
tests/test_stage4_tier3_check_last_release.py's own established precedent
for this exact tradeoff (a small number of real-network tests, not every
test).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.fleet.dependency_resolver import PyPIProvider, check_dependency_conflicts


def _fake_package_metadata(releases: dict[str, Any]) -> dict[str, Any]:
    return {"releases": {v: [{"filename": f"pkg-{v}.tar.gz"}] for v in releases}}


def _fake_version_metadata(requires_dist: list[str]) -> dict[str, Any]:
    return {"info": {"requires_dist": requires_dist}}


def _make_fake_world(
    packages: dict[str, list[str]],  # name -> list of real version strings
    deps: dict[tuple[str, str], list[str]],  # (name, version) -> requires_dist lines
) -> PyPIProvider:
    def fetch_package(name: str) -> dict[str, Any] | None:
        versions = packages.get(name)
        if versions is None:
            return None
        return _fake_package_metadata({v: True for v in versions})

    def fetch_version(name: str, version: str) -> dict[str, Any] | None:
        return _fake_version_metadata(deps.get((name, version), []))

    return PyPIProvider(fetch_package=fetch_package, fetch_version=fetch_version)


# ---------------------------------------------------------------------------
# Fake-world unit tests — fast, deterministic, no network
# ---------------------------------------------------------------------------


def test_resolvable_when_a_consistent_version_set_exists() -> None:
    provider = _make_fake_world(
        packages={"a": ["1.0.0", "2.0.0"], "b": ["1.0.0", "1.5.0"]},
        deps={("a", "2.0.0"): ["b>=1.5.0"], ("a", "1.0.0"): []},
    )
    result = check_dependency_conflicts(["a>=2.0.0"], provider=provider)
    assert result.error is None
    assert result.resolvable is True
    assert result.resolved_versions["a"] == "2.0.0"
    assert result.resolved_versions["b"] == "1.5.0"


def test_unresolvable_real_conflict_is_reported_not_a_crash() -> None:
    """The actual capability #463 asks for: two top-level constraints that
    are individually valid but jointly unsatisfiable across the transitive
    graph — pip check (installed-env-only) cannot see this at all since
    nothing here is installed; this resolver can."""
    provider = _make_fake_world(
        packages={"a": ["1.0.0"], "b": ["1.0.0", "2.0.0"]},
        deps={("a", "1.0.0"): ["b<2.0.0"]},
    )
    result = check_dependency_conflicts(["a==1.0.0", "b>=2.0.0"], provider=provider)
    assert result.error is None
    assert result.resolvable is False
    assert result.conflict_summary is not None
    assert "b" in result.conflict_summary


def test_unknown_package_is_a_real_conflict_not_silently_resolved() -> None:
    provider = _make_fake_world(packages={}, deps={})
    result = check_dependency_conflicts(["totally-unknown-package>=1.0"], provider=provider)
    assert result.error is None
    assert result.resolvable is False


def test_malformed_requirement_string_is_a_real_error_not_a_fabricated_conflict() -> None:
    """A parse failure and a genuine version conflict are different claims
    — matches dependency_conflict.py's own 'a failed check and a clean
    check are different claims' convention."""
    result = check_dependency_conflicts(["not a valid requirement !!!"])
    assert result.error is not None
    assert result.resolvable is False
    assert result.conflict_summary is None


def test_extras_gated_dependencies_are_skipped_not_crashed_on() -> None:
    provider = _make_fake_world(
        packages={"a": ["1.0.0"], "b": ["1.0.0"]},
        deps={("a", "1.0.0"): ["b[extra]>=1.0.0; extra == 'dev'"]},
    )
    result = check_dependency_conflicts(["a==1.0.0"], provider=provider)
    assert result.error is None
    assert result.resolvable is True
    assert "b" not in result.resolved_versions  # extras-gated dep intentionally not pulled in


def test_no_metadata_available_excludes_candidates_gracefully() -> None:
    """A real infrastructure gap (network down, package genuinely missing)
    must surface as unresolvable, never crash the resolver."""
    provider = PyPIProvider(fetch_package=lambda name: None)
    result = check_dependency_conflicts(["some-package>=1.0"], provider=provider)
    assert result.error is None
    assert result.resolvable is False


# ---------------------------------------------------------------------------
# Real network tests — a small, deliberate number, matching
# check_last_release's own established convention for this tradeoff.
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_real_pypi_resolves_a_genuinely_satisfiable_real_package() -> None:
    """requests has no famously-impossible-to-resolve constraint set — a
    real, live proof the whole pipeline (real curl fetch, real JSON parse,
    real resolvelib backtracking) works end to end against the actual
    PyPI API, not just the fake world above."""
    result = check_dependency_conflicts(["requests>=2.0.0,<3.0.0"])
    assert result.error is None, result.error
    assert result.resolvable is True
    assert "requests" in result.resolved_versions


@pytest.mark.slow
def test_real_pypi_reports_a_genuinely_impossible_version_range() -> None:
    """A version range with no published release can ever satisfy — a
    real, live proof the resolver correctly reports unresolvable rather
    than silently picking something close."""
    result = check_dependency_conflicts(["requests>=999.0.0,<1000.0.0"])
    assert result.error is None, result.error
    assert result.resolvable is False

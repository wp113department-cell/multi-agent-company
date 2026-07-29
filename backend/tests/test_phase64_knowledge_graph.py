"""Tests for MASTER_AGENT_v2.md Phase 6.4 — repo knowledge graph extensions:
class/inheritance graph (app/repo_tools/cross_file_graph.py::build_class_graph)
and package/module-level dependency graph
(app/repo_tools/scanner.py::build_package_graph).

Fixture mirrors tests/test_cross_file_graph.py's demo_repo pattern, extended
with a real cross-file class inheritance edge and a real cross-package
import edge (two separate directories), matching the spec's own DoD:
"tests against a small known-fixture repo... with real inheritance and
cross-package imports."
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.repo_tools.cross_file_graph import build_class_graph
from app.repo_tools.scanner import (
    build_call_graph,
    build_package_graph,
    index_repository,
)


@pytest.fixture
def demo_repo(tmp_path: Path) -> Path:
    pkg_a = tmp_path / "pkg_a"
    pkg_b = tmp_path / "pkg_b"
    pkg_a.mkdir()
    pkg_b.mkdir()

    (pkg_a / "animals.py").write_text(
        "class Animal:\n"
        "    def speak(self):\n"
        "        return '...'\n\n"
        "class Named:\n"
        "    pass\n"
    )
    (pkg_b / "dogs.py").write_text(
        "from pkg_a.animals import Animal, Named\n\n"
        "class Dog(Animal):\n"
        "    def speak(self):\n"
        "        return 'Woof'\n\n"
        "class ServiceDog(Dog, Named):\n"
        "    pass\n"
    )
    # Same-package file — its import of animals.py must NOT create a
    # cross-package edge counted separately from pkg_b's (it's in pkg_a).
    (pkg_a / "zoo.py").write_text("from pkg_a.animals import Animal\n")
    # A class whose base isn't defined anywhere indexed (stdlib) — must
    # resolve to no inheritance edge, not an error.
    (tmp_path / "errors.py").write_text("class CustomError(Exception):\n    pass\n")
    return tmp_path


class TestBuildClassGraph:
    def test_resolves_cross_file_inheritance_edge(self, demo_repo: Path) -> None:
        idx = index_repository(str(demo_repo))
        edges = build_class_graph(idx)

        match = [
            e
            for e in edges
            if e.subclass_symbol == "Dog" and e.superclass_symbol == "Animal"
        ]
        assert match, f"expected Dog -> Animal edge, got {edges}"
        edge = match[0]
        assert (
            edge.subclass_file == "pkg_b\\dogs.py"
            or edge.subclass_file == "pkg_b/dogs.py"
        )
        assert edge.superclass_file.endswith("animals.py")

    def test_resolves_multiple_inheritance_edges(self, demo_repo: Path) -> None:
        idx = index_repository(str(demo_repo))
        edges = build_class_graph(idx)

        superclasses = {
            e.superclass_symbol for e in edges if e.subclass_symbol == "ServiceDog"
        }
        assert superclasses == {"Dog", "Named"}

    def test_unresolved_stdlib_base_produces_no_edge(self, demo_repo: Path) -> None:
        idx = index_repository(str(demo_repo))
        edges = build_class_graph(idx)
        assert not any(e.subclass_symbol == "CustomError" for e in edges)

    def test_class_without_bases_produces_no_edge(self, demo_repo: Path) -> None:
        idx = index_repository(str(demo_repo))
        edges = build_class_graph(idx)
        assert not any(e.subclass_symbol == "Animal" for e in edges)

    def test_no_self_inheritance_edge(self, demo_repo: Path) -> None:
        idx = index_repository(str(demo_repo))
        edges = build_class_graph(idx)
        for e in edges:
            assert not (
                e.subclass_file == e.superclass_file
                and e.subclass_symbol == e.superclass_symbol
            )


class TestBuildPackageGraph:
    def test_cross_package_import_produces_a_package_edge(
        self, demo_repo: Path
    ) -> None:
        idx = index_repository(str(demo_repo))
        import_edges = build_call_graph(idx)
        package_edges = build_package_graph(import_edges)

        match = [
            e
            for e in package_edges
            if e.caller_package == "pkg_b" and e.callee_package == "pkg_a"
        ]
        assert match, f"expected pkg_b -> pkg_a package edge, got {package_edges}"

    def test_same_package_import_is_excluded(self, demo_repo: Path) -> None:
        """pkg_a/zoo.py imports pkg_a/animals.py — same package, must not
        appear as a cross-package edge."""
        idx = index_repository(str(demo_repo))
        import_edges = build_call_graph(idx)
        package_edges = build_package_graph(import_edges)
        for e in package_edges:
            assert e.caller_package != e.callee_package

    def test_weight_counts_real_file_level_edges(self, demo_repo: Path) -> None:
        idx = index_repository(str(demo_repo))
        import_edges = build_call_graph(idx)
        package_edges = build_package_graph(import_edges)
        edge = next(
            e
            for e in package_edges
            if e.caller_package == "pkg_b" and e.callee_package == "pkg_a"
        )
        assert edge.weight == 1

    def test_root_level_file_has_dot_package(self, tmp_path: Path) -> None:
        (tmp_path / "root_a.py").write_text("import root_b\n")
        (tmp_path / "root_b.py").write_text("def f():\n    return 1\n")
        idx = index_repository(str(tmp_path))
        import_edges = build_call_graph(idx)
        package_edges = build_package_graph(import_edges)
        # both files are at repo root ("." package) — same package, excluded
        assert package_edges == []

    def test_empty_import_edges_returns_empty_graph(self) -> None:
        assert build_package_graph({}) == []


class TestKnowledgeGraphEndpoints:
    """Endpoint-level tests — prove GET /api/repo/class-graph and
    GET /api/repo/package-graph are really wired to build_class_graph()/
    build_package_graph(), not just unit-tested in isolation (same
    patch-and-hit convention as test_architecture_mapper.py's
    TestArchitectureEndpoint)."""

    def test_class_graph_endpoint_returns_real_inheritance_edges(
        self, demo_repo: Path
    ) -> None:
        from fastapi.testclient import TestClient

        import app.api.repo as repo_module
        from app.main import app

        with patch.object(
            repo_module, "get_active_repo_path", return_value=str(demo_repo)
        ), patch.object(repo_module, "_cached_index", None):
            with TestClient(app) as client:
                resp = client.get("/api/repo/class-graph")

        assert resp.status_code == 200, resp.text
        edges = resp.json()["edges"]
        assert any(
            e["subclassSymbol"] == "Dog" and e["superclassSymbol"] == "Animal"
            for e in edges
        )

    def test_package_graph_endpoint_returns_real_cross_package_edges(
        self, demo_repo: Path
    ) -> None:
        from fastapi.testclient import TestClient

        import app.api.repo as repo_module
        from app.main import app

        with patch.object(
            repo_module, "get_active_repo_path", return_value=str(demo_repo)
        ), patch.object(repo_module, "_cached_index", None):
            with TestClient(app) as client:
                resp = client.get("/api/repo/package-graph")

        assert resp.status_code == 200, resp.text
        edges = resp.json()["edges"]
        assert any(
            e["callerPackage"] == "pkg_b" and e["calleePackage"] == "pkg_a"
            for e in edges
        )

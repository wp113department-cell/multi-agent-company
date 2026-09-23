"""T2-B5 (2026-09-22, GRIDIRON_PARTIAL #396 "Broken imports / unused files
/ duplicate functions detection").

Task 1's own verification found dead code, unused imports, and circular
imports already real — but no detector for broken/unresolvable imports,
unused files, or duplicate/cloned functions. These are real AST-based
detectors, tested against real files on disk (tmp_path), not mocked.
"""

from __future__ import annotations

from pathlib import Path

from app.repo_tools.code_hygiene import (
    find_broken_imports,
    find_duplicate_functions,
    find_unused_files,
)


def _write(tmp_path: Path, rel: str, content: str) -> None:
    fp = tmp_path / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# find_broken_imports
# ---------------------------------------------------------------------------


def test_none_for_empty_or_missing_directory(tmp_path: Path) -> None:
    assert find_broken_imports(str(tmp_path / "does-not-exist")) is None
    assert find_broken_imports(str(tmp_path)) is None  # no .py files yet


def test_detects_a_genuinely_unresolvable_import(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "import totally_fake_module_xyz_never_real\n")
    result = find_broken_imports(str(tmp_path))
    assert result is not None
    assert len(result) == 1
    assert result[0].module == "totally_fake_module_xyz_never_real"
    assert result[0].file == "a.py"


def test_stdlib_and_installed_packages_are_not_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "import os\nimport sys\nimport json\nfrom pathlib import Path\n")
    assert find_broken_imports(str(tmp_path)) == []


def test_import_error_guarded_optional_dependency_is_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.py",
        "try:\n    import totally_fake_optional_dep_xyz\nexcept ImportError:\n    totally_fake_optional_dep_xyz = None\n",
    )
    assert find_broken_imports(str(tmp_path)) == []


def test_bare_except_also_guards_an_optional_import(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.py",
        "try:\n    import totally_fake_optional_dep_xyz\nexcept Exception:\n    pass\n",
    )
    assert find_broken_imports(str(tmp_path)) == []


def test_real_local_first_party_package_resolves(tmp_path: Path) -> None:
    """A package that lives INSIDE the scanned tree itself (not on the real
    sys.path) must resolve — the tree root is prepended to sys.path for
    the duration of the scan."""
    _write(tmp_path, "mypkg/__init__.py", "")
    _write(tmp_path, "mypkg/helper.py", "def f(): return 1\n")
    _write(tmp_path, "user.py", "import mypkg\nfrom mypkg import helper\n")
    assert find_broken_imports(str(tmp_path)) == []


def test_resolvable_relative_import_is_not_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/a.py", "from . import b\nfrom .c import thing\n")
    _write(tmp_path, "pkg/b.py", "")
    _write(tmp_path, "pkg/c.py", "def thing(): pass\n")
    assert find_broken_imports(str(tmp_path)) == []


def test_unresolvable_relative_import_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/a.py", "from .nonexistent_module import thing\n")
    result = find_broken_imports(str(tmp_path))
    assert result is not None
    assert any(b.module == ".nonexistent_module" for b in result)


# ---------------------------------------------------------------------------
# find_unused_files
# ---------------------------------------------------------------------------


def test_unused_none_for_empty_or_missing_directory(tmp_path: Path) -> None:
    assert find_unused_files(str(tmp_path / "does-not-exist")) is None
    assert find_unused_files(str(tmp_path)) is None


def test_a_file_referenced_via_relative_import_is_not_unused(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/a.py", "from . import b\nfrom .c import thing\n")
    _write(tmp_path, "pkg/b.py", "def bar(): pass\n")
    _write(tmp_path, "pkg/c.py", "def thing(): pass\n")
    unused = find_unused_files(str(tmp_path))
    assert unused is not None
    assert "pkg/b.py" not in unused
    assert "pkg/c.py" not in unused


def test_a_genuinely_orphaned_file_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/used.py", "def f(): pass\n")
    _write(tmp_path, "pkg/orphan.py", "def never_called(): pass\n")
    _write(tmp_path, "pkg/importer.py", "from . import used\n")
    unused = find_unused_files(str(tmp_path))
    assert unused is not None
    assert "pkg/orphan.py" in unused


def test_init_py_is_never_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/orphan.py", "def f(): pass\n")
    unused = find_unused_files(str(tmp_path))
    assert unused is not None
    assert "pkg/__init__.py" not in unused


def test_conventional_entry_points_are_never_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "main.py", "print('hi')\n")
    _write(tmp_path, "conftest.py", "\n")
    _write(tmp_path, "test_something.py", "def test_x(): assert True\n")
    unused = find_unused_files(str(tmp_path))
    assert unused is not None
    assert unused == []


def test_absolute_first_party_import_is_not_unused(tmp_path: Path) -> None:
    _write(tmp_path, "mypkg/__init__.py", "")
    _write(tmp_path, "mypkg/helper.py", "def f(): pass\n")
    _write(tmp_path, "user.py", "from mypkg import helper\n")
    unused = find_unused_files(str(tmp_path))
    assert unused is not None
    assert "mypkg/helper.py" not in unused


# ---------------------------------------------------------------------------
# find_duplicate_functions
# ---------------------------------------------------------------------------


def test_duplicates_none_for_empty_or_missing_directory(tmp_path: Path) -> None:
    assert find_duplicate_functions(str(tmp_path / "does-not-exist")) is None
    assert find_duplicate_functions(str(tmp_path)) is None


def test_a_real_structural_clone_across_files_is_detected(tmp_path: Path) -> None:
    """Renamed variables, renamed function, same file — same shape as the
    real copy-paste-and-rename pattern this detector exists to catch."""
    _write(
        tmp_path,
        "a.py",
        "def foo(x, y):\n    total = x + y\n    print(total)\n    return total\n",
    )
    _write(
        tmp_path,
        "b.py",
        "def bar(a, b):\n    result = a + b\n    print(result)\n    return result\n",
    )
    groups = find_duplicate_functions(str(tmp_path))
    assert groups is not None
    assert len(groups) == 1
    locs = groups[0].locations
    assert any("a.py" in loc and "foo" in loc for loc in locs)
    assert any("b.py" in loc and "bar" in loc for loc in locs)


def test_structurally_different_functions_are_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.py",
        "def foo(x, y):\n    total = x + y\n    print(total)\n    return total\n",
    )
    _write(
        tmp_path,
        "b.py",
        "def baz(items):\n    for i in items:\n        print(i)\n    return len(items)\n",
    )
    assert find_duplicate_functions(str(tmp_path)) == []


def test_trivial_short_functions_are_not_flagged_as_noise(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "def f():\n    pass\n")
    _write(tmp_path, "b.py", "def g():\n    pass\n")
    assert find_duplicate_functions(str(tmp_path)) == []


def test_a_single_occurrence_is_never_a_duplicate_group(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.py",
        "def unique_fn(x, y):\n    total = x + y\n    print(total)\n    return total\n",
    )
    assert find_duplicate_functions(str(tmp_path)) == []

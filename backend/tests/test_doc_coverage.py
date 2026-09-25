"""#457 (2026-09-25, "Documentation checks (mandatory pre-completion
gate)") — real, direct tests of doc_coverage.py's AST scan, independent of
its manager.py gate wiring (covered separately in
test_batch16_quality_gates.py::TestDocumentationGate).
"""

from __future__ import annotations

from app.repo_tools.doc_coverage import check_subtask_doc_coverage


def test_undocumented_public_function_is_flagged(tmp_path) -> None:
    (tmp_path / "mod.py").write_text("def public_fn():\n    pass\n")
    report = check_subtask_doc_coverage(str(tmp_path), ["mod.py"])
    assert report.undocumented_count == 1
    assert "public_fn" in report.undocumented[0]


def test_documented_function_is_not_flagged(tmp_path) -> None:
    (tmp_path / "mod.py").write_text(
        'def public_fn():\n    """Does a thing."""\n    pass\n'
    )
    report = check_subtask_doc_coverage(str(tmp_path), ["mod.py"])
    assert report.undocumented_count == 0


def test_private_function_is_not_flagged(tmp_path) -> None:
    (tmp_path / "mod.py").write_text("def _helper():\n    pass\n")
    report = check_subtask_doc_coverage(str(tmp_path), ["mod.py"])
    assert report.undocumented_count == 0


def test_undocumented_class_is_flagged(tmp_path) -> None:
    (tmp_path / "mod.py").write_text("class PublicThing:\n    pass\n")
    report = check_subtask_doc_coverage(str(tmp_path), ["mod.py"])
    assert report.undocumented_count == 1
    assert "PublicThing" in report.undocumented[0]


def test_non_python_files_are_skipped(tmp_path) -> None:
    (tmp_path / "notes.md").write_text("# undocumented, but not python\n")
    report = check_subtask_doc_coverage(str(tmp_path), ["notes.md"])
    assert report.undocumented_count == 0


def test_missing_file_is_skipped_not_raised(tmp_path) -> None:
    report = check_subtask_doc_coverage(str(tmp_path), ["does_not_exist.py"])
    assert report.undocumented_count == 0


def test_unparseable_file_is_skipped_not_raised(tmp_path) -> None:
    (tmp_path / "broken.py").write_text("def totally( invalid syntax\n")
    report = check_subtask_doc_coverage(str(tmp_path), ["broken.py"])
    assert report.undocumented_count == 0


def test_only_scans_the_given_changed_files_not_the_whole_worktree(tmp_path) -> None:
    (tmp_path / "touched.py").write_text("def touched_fn():\n    pass\n")
    (tmp_path / "untouched.py").write_text("def untouched_fn():\n    pass\n")
    report = check_subtask_doc_coverage(str(tmp_path), ["touched.py"])
    assert report.undocumented_count == 1
    assert "touched_fn" in report.undocumented[0]
    assert "untouched_fn" not in report.undocumented[0]


def test_nested_function_is_not_flagged(tmp_path) -> None:
    """Only top-level symbols are in scope — same documented boundary as
    reliability_review.py's own nested-function limitation."""
    (tmp_path / "mod.py").write_text(
        "def outer():\n    def inner():\n        pass\n    return inner\n"
    )
    report = check_subtask_doc_coverage(str(tmp_path), ["mod.py"])
    assert report.undocumented_count == 1
    assert "outer" in report.undocumented[0]
    assert "inner" not in report.undocumented[0]

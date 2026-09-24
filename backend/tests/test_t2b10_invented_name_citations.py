"""T2-B10 (2026-09-24, GRIDIRON_PARTIAL #502 "Refuse to invent APIs/files/
functions/classes (code-checked citations)" — Task 1's own re-verification
of this item, DOWNGRADED: "only path:line citations are checked ...
invented functions/classes/APIs are not checked at all.").

app.agents.tool_security.verify_file_line_citations() now ALSO checks a
`` `name()` in path:line `` -style claim against a real AST parse of the
cited file — this is the genuinely new check the audit's own finding named
as completely missing before this. Still deliberately non-blocking (flags
via `unverified_names`, same as the pre-existing file:line check's own
posture) — see that function's own docstring for why.
"""

from __future__ import annotations

from pathlib import Path

from app.agents.tool_security import verify_file_line_citations


class TestInventedFunctionClassCitations:
    def test_a_real_function_citation_is_not_flagged(self, tmp_path: Path) -> None:
        (tmp_path / "real.py").write_text("def real_function():\n    pass\n")
        report = verify_file_line_citations(
            str(tmp_path), {"summary": "see `real_function()` in real.py:1"}
        )
        assert report["unverified_names"] == []

    def test_a_real_class_citation_is_not_flagged(self, tmp_path: Path) -> None:
        (tmp_path / "real.py").write_text("class RealClass:\n    pass\n")
        report = verify_file_line_citations(
            str(tmp_path), {"summary": "see `RealClass` in real.py:1"}
        )
        assert report["unverified_names"] == []

    def test_an_invented_function_name_is_flagged(self, tmp_path: Path) -> None:
        (tmp_path / "real.py").write_text("def real_function():\n    pass\n")
        report = verify_file_line_citations(
            str(tmp_path),
            {"summary": "the fix uses `made_up_function()` in real.py:1"},
        )
        assert len(report["unverified_names"]) == 1
        assert "made_up_function" in report["unverified_names"][0]
        assert "real.py" in report["unverified_names"][0]

    def test_a_bad_file_line_citation_does_not_also_get_a_duplicate_name_finding(
        self, tmp_path: Path
    ) -> None:
        # The file:line citation itself is already bad (file doesn't
        # exist) — that's reported once via `unverified`; the name check
        # must not pile on a second, redundant finding for a citation
        # that's already known bad.
        report = verify_file_line_citations(
            str(tmp_path), {"summary": "see `some_function()` in ghost.py:1"}
        )
        assert len(report["unverified"]) == 1
        assert report["unverified_names"] == []

    def test_a_name_with_no_nearby_citation_is_never_checked(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "real.py").write_text("def real_function():\n    pass\n")
        # `totally_unrelated_name` appears nowhere near any file:line
        # citation in this string — must not be paired with real.py:1,
        # which is describing something else entirely far away in the text.
        far_text = "`totally_unrelated_name`" + " padding " * 40 + "see real.py:1"
        report = verify_file_line_citations(str(tmp_path), {"summary": far_text})
        assert report["unverified_names"] == []

    def test_non_python_file_citations_are_never_name_checked(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "notes.md").write_text("some notes\nmore notes\n")
        report = verify_file_line_citations(
            str(tmp_path), {"summary": "see `whatever_name` in notes.md:1"}
        )
        assert report["unverified_names"] == []

    def test_multiple_invented_names_are_all_reported(self, tmp_path: Path) -> None:
        (tmp_path / "real.py").write_text("def real_function():\n    pass\n")
        report = verify_file_line_citations(
            str(tmp_path),
            {
                "summary": "uses `fake_one()` in real.py:1",
                "detail": "also uses `fake_two()` in real.py:1",
            },
        )
        names_str = " ".join(report["unverified_names"])
        assert "fake_one" in names_str
        assert "fake_two" in names_str

    def test_unparseable_python_file_never_produces_a_false_finding(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "broken.py").write_text("def f(:\n    this is not valid python\n")
        report = verify_file_line_citations(
            str(tmp_path), {"summary": "see `anything()` in broken.py:1"}
        )
        assert report["unverified_names"] == []

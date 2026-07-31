"""Gap-closure Stage 1.7 (answers.md) — proves is_structural_file_change()
correctly identifies (and doesn't over/under-match) structural-file diffs,
the real decision that drives whether CI triggers tech_debt_agent
(scripts/ci_tech_debt_scan.py).
"""

from __future__ import annotations

from app.fleet.structural_diff import is_structural_file_change


def test_true_for_an_exact_structural_file_match() -> None:
    assert is_structural_file_change(["backend/app/db/models.py"]) is True
    assert is_structural_file_change(["backend/app/agents/base_graph.py"]) is True
    assert is_structural_file_change(["backend/app/config.py"]) is True


def test_true_for_a_file_under_the_migrations_directory() -> None:
    assert (
        is_structural_file_change(["backend/migrations/versions/0042_add_thing.py"])
        is True
    )


def test_true_when_only_one_of_several_changed_files_is_structural() -> None:
    changed = [
        "apps/web/app/tasks/page.tsx",
        "backend/app/agents/chat_agent.py",
        "README.md",
    ]
    assert is_structural_file_change(changed) is True


def test_false_for_routine_feature_files() -> None:
    changed = [
        "backend/app/agents/localization_agent.py",
        "apps/web/app/settings/page.tsx",
        "backend/tests/test_localization_agent.py",
    ]
    assert is_structural_file_change(changed) is False


def test_false_for_empty_diff() -> None:
    assert is_structural_file_change([]) is False


def test_does_not_over_match_a_similarly_named_non_structural_file() -> None:
    # A real file living in the same directory as a structural one, but not
    # itself the structural file — must not match on a directory prefix
    # that isn't one of the explicit "/"-suffixed directory patterns.
    assert is_structural_file_change(["backend/app/db/repository.py"]) is False
    assert (
        is_structural_file_change(["backend/app/agents/base_graph_helpers.py"]) is False
    )

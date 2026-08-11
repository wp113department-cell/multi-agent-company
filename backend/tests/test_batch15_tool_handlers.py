"""Tests for the tool-handler wiring half of AUDIT_Q_BATCH15 §74/§113/§75/§105/§112:
record_preference (new tool) and known_issues_write (existing tool, now also
writing to searchable bug memory alongside its unchanged flat-file append).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

from app.agents.tools import make_chat_handlers, make_record_preference_handler


def _issues_path_for(repo_path: str) -> Path:
    slug = hashlib.md5(repo_path.encode()).hexdigest()[:8]
    return Path(__file__).parent.parent / "app" / "memory" / f"{slug}_known_issues.md"


def test_record_preference_handler_calls_embed_preference_sync() -> None:
    handler = make_record_preference_handler(task_id="chat-test-1")

    with patch(
        "app.memory.store.embed_preference_sync", return_value=True
    ) as mock_embed:
        result = handler({"preference": "always use f-strings", "scope": "style"})

    assert result == "Recorded."
    mock_embed.assert_called_once_with(
        task_id="chat-test-1", preference="always use f-strings", scope="style"
    )


def test_record_preference_handler_requires_preference_text() -> None:
    handler = make_record_preference_handler(task_id="chat-test-2")
    result = handler({"preference": "  "})
    assert result.startswith("[ERROR]")


def test_record_preference_handler_defaults_scope_to_general() -> None:
    handler = make_record_preference_handler(task_id="chat-test-3")
    with patch(
        "app.memory.store.embed_preference_sync", return_value=True
    ) as mock_embed:
        handler({"preference": "no comments unless non-obvious"})
    assert mock_embed.call_args.kwargs["scope"] == "general"


def test_known_issues_write_still_appends_to_flat_file_unchanged() -> None:
    repo_path = "/tmp/td-batch15-known-issues-repo"
    handlers = make_chat_handlers(repo_path)
    issues_path = _issues_path_for(repo_path)
    try:
        with patch("app.memory.store.embed_bug_sync", return_value=True):
            result = handlers["known_issues_write"](
                {"issue": "flaky CI on migration tests", "severity": "high"}
            )
        assert "Known issue appended" in result
        assert issues_path.exists()
        content = issues_path.read_text(encoding="utf-8")
        assert "flaky CI on migration tests" in content
        assert "[HIGH]" in content
    finally:
        if issues_path.exists():
            issues_path.unlink()


def test_known_issues_write_also_embeds_into_searchable_bug_memory() -> None:
    repo_path = "/tmp/td-batch15-known-issues-repo-2"
    handlers = make_chat_handlers(repo_path)
    issues_path = _issues_path_for(repo_path)
    try:
        with patch("app.memory.store.embed_bug_sync", return_value=True) as mock_embed:
            handlers["known_issues_write"](
                {"issue": "race condition in pool", "severity": "critical"}
            )
        assert mock_embed.called
        kwargs = mock_embed.call_args.kwargs
        assert kwargs["issue"] == "race condition in pool"
        assert kwargs["severity"] == "critical"
        assert kwargs["task_id"].startswith("known-issue-")
    finally:
        if issues_path.exists():
            issues_path.unlink()


def test_known_issues_write_succeeds_even_if_bug_embedding_fails() -> None:
    """Best-effort contract: a broken memory backend must not turn a
    successful flat-file known-issue write into an [ERROR]."""
    repo_path = "/tmp/td-batch15-known-issues-repo-3"
    handlers = make_chat_handlers(repo_path)
    issues_path = _issues_path_for(repo_path)
    try:
        with patch(
            "app.memory.store.embed_bug_sync", side_effect=RuntimeError("db down")
        ):
            result = handlers["known_issues_write"](
                {"issue": "some issue", "severity": "low"}
            )
        assert "Known issue appended" in result
    finally:
        if issues_path.exists():
            issues_path.unlink()

"""AUDIT_Q_BATCH11 §85 "All agents automatically follow policy (structural
guarantee)" — proves base_graph.py's execute_tools() chokepoint
(_policy_check) now covers every write_repo/write_remote/execute-permission
tool in TOOL_MANIFEST, not just the original hand-picked 5
(write_file/edit_file/delete_file/apply_patch/bash).

Before this fix, ~45 other write-capable tools (copy_file, rename_file,
docker_exec, ...) relied entirely on their own per-handler check inside
app/agents/tools.py — real everywhere sampled, but with no structural
guarantee a future handler couldn't skip it. This proves the central
chokepoint itself now denies a protected-path/dangerous-command attempt for
tools well outside the original 5, driven by TOOL_MANIFEST's permission
tags — so a brand new tool is covered automatically by the permission it
declares, without needing a name added here.
"""

from __future__ import annotations

from app.agents.base_graph import _policy_check
from app.fleet.tool_manifest import TOOL_MANIFEST


class TestBroadenedPathCoverage:
    def test_copy_file_protected_destination_denied(self) -> None:
        result = _policy_check(
            "copy_file", {"from_path": "config.py", "to_path": ".env"}
        )
        assert result is not None

    def test_copy_file_safe_paths_allowed(self) -> None:
        result = _policy_check(
            "copy_file", {"from_path": "src/a.py", "to_path": "src/b.py"}
        )
        assert result is None

    def test_rename_file_protected_target_denied(self) -> None:
        result = _policy_check(
            "rename_file", {"from_path": "notes.txt", "to_path": "id_rsa"}
        )
        assert result is not None

    def test_write_file_via_manifest_permission_still_covered(self) -> None:
        # Not in the original hardcoded 3-name set for this branch anymore
        # (write_file/edit_file/delete_file) — now reached via the
        # write_repo permission path too; proves both routes agree.
        result = _policy_check("write_file", {"path": "secrets/prod.key"})
        assert result is not None

    def test_move_file_protected_destination_denied(self) -> None:
        result = _policy_check(
            "move_file", {"source": "a.txt", "dest": ".env.production"}
        )
        assert result is not None

    def test_zip_files_protected_output_denied(self) -> None:
        result = _policy_check("zip_files", {"source": "src/", "output": ".git/config"})
        assert result is not None

    def test_list_valued_path_field_is_checked_per_element(self) -> None:
        """A path field holding a list (e.g. a future multi-file tool) must
        be checked element-by-element, not skipped because the value isn't
        a bare string."""
        result = _policy_check("write_file", {"path": ["src/main.py", ".env"]})
        assert result is not None

    def test_content_field_is_never_scanned_as_a_path(self) -> None:
        """A file whose CONTENT happens to mention a protected filename must
        not be denied — only field names that are actually path fields are
        scanned (see _policy_check's module comment for the false-positive
        reasoning)."""
        result = _policy_check(
            "write_file",
            {
                "path": "docs/security_notes.md",
                "content": "Remember to rotate ~/.ssh/id_rsa regularly.",
            },
        )
        assert result is None


class TestBroadenedCommandCoverage:
    def test_docker_exec_dangerous_command_denied(self) -> None:
        result = _policy_check(
            "docker_exec", {"container": "web", "command": "rm -rf /"}
        )
        assert result is not None

    def test_docker_exec_safe_command_allowed(self) -> None:
        result = _policy_check("docker_exec", {"container": "web", "command": "ls -la"})
        assert result is None


class TestManifestDrivenCoverage:
    def test_every_write_repo_or_write_remote_tool_gets_a_path_check_attempted(
        self,
    ) -> None:
        """Structural proof, not a spot-check: for every tool manifest entry
        carrying write_repo/write_remote, a protected-path value under any
        of the tool's own declared path-like fields must be denied. This
        would have failed before this fix for all but write_file/edit_file/
        delete_file/apply_patch."""
        from app.agents.tools import CHAT_TOOLS

        schema_by_name = {t["name"]: t["input_schema"] for t in CHAT_TOOLS}
        path_field_names = {
            "path",
            "paths",
            "from_path",
            "to_path",
            "source",
            "dest",
            "destination",
            "output",
            "archive",
            "directory",
        }

        checked_any = False
        for name, entry in TOOL_MANIFEST.items():
            if not ({"write_repo", "write_remote"} & set(entry.permissions)):
                continue
            schema = schema_by_name.get(name)
            if schema is None:
                continue
            props = schema.get("properties", {})
            matching_fields = [f for f in props if f in path_field_names]
            if not matching_fields:
                continue  # e.g. decision_log_append — no path-shaped field at all
            field = matching_fields[0]
            checked_any = True
            result = _policy_check(name, {field: ".env"})
            assert result is not None, (
                f"{name!r}'s {field!r} field accepted a protected path "
                "unchecked by the central chokepoint"
            )
        assert checked_any, "test setup found zero eligible tools — investigate"

"""AUDIT_Q_BATCH11 §85 "Central governance system beyond the security-
focused policy engine" — proves app/policy/governance.py's real,
evidence-grounded framework-approval rule (Node.js backend frameworks are
disallowed inside backend/, per this project's own README.md-documented
architecture) is both correct in isolation and actually wired into the
same _policy_check chokepoint every write tool call already goes through
(base_graph.py's execute_tools node, and — via the same _policy_check
function, imported not duplicated — ChatAgent's own _execute_tool_node).
"""

from __future__ import annotations

import json

from app.agents.base_graph import _policy_check
from app.policy.governance import check_backend_framework_governance


class TestCheckBackendFrameworkGovernance:
    def test_express_in_backend_package_json_denied(self) -> None:
        result = check_backend_framework_governance(
            "package.json", json.dumps({"dependencies": {"express": "^4.18.0"}})
        )
        assert result.allowed is False
        assert "express" in result.reason

    def test_fastify_in_dev_dependencies_denied(self) -> None:
        result = check_backend_framework_governance(
            "package.json", json.dumps({"devDependencies": {"fastify": "^4.0.0"}})
        )
        assert result.allowed is False

    def test_nested_backend_package_json_denied(self) -> None:
        result = check_backend_framework_governance(
            "services/api/package.json",
            json.dumps({"dependencies": {"koa": "^2.0.0"}}),
        )
        assert result.allowed is False

    def test_apps_web_package_json_is_always_allowed(self) -> None:
        """The one real, README-documented Node.js/TypeScript surface —
        express as a frontend dep would be unusual but is not this rule's
        concern (frontend framework choice isn't a backend-architecture
        violation)."""
        result = check_backend_framework_governance(
            "apps/web/package.json",
            json.dumps({"dependencies": {"express": "^4.18.0", "next": "^14.0.0"}}),
        )
        assert result.allowed is True

    def test_safe_backend_package_json_allowed(self) -> None:
        result = check_backend_framework_governance(
            "package.json", json.dumps({"dependencies": {"left-pad": "^1.0.0"}})
        )
        assert result.allowed is True

    def test_non_package_json_file_always_allowed(self) -> None:
        result = check_backend_framework_governance("src/main.py", "x = 1")
        assert result.allowed is True

    def test_the_one_real_existing_js_file_is_unaffected(self) -> None:
        """tests/load/gridiron_load_test.js is a real, legitimate existing
        file (a k6 load-test script) — this rule only fires on
        package.json writes, never on this file."""
        result = check_backend_framework_governance(
            "tests/load/gridiron_load_test.js", "export default function () {}"
        )
        assert result.allowed is True

    def test_malformed_json_content_does_not_crash_or_false_deny(self) -> None:
        result = check_backend_framework_governance("package.json", "{not valid json")
        assert result.allowed is True

    def test_empty_content_is_allowed_not_denied(self) -> None:
        """An empty/placeholder write must not be denied just because the
        path is package.json — nothing to inspect yet."""
        result = check_backend_framework_governance("package.json", "")
        assert result.allowed is True


class TestGovernanceWiredIntoPolicyCheckChokepoint:
    def test_write_file_backend_package_json_with_express_is_denied(self) -> None:
        result = _policy_check(
            "write_file",
            {
                "path": "package.json",
                "content": json.dumps({"dependencies": {"express": "^4.18.0"}}),
            },
        )
        assert result is not None
        assert "express" in result

    def test_write_file_frontend_package_json_with_express_is_allowed(self) -> None:
        result = _policy_check(
            "write_file",
            {
                "path": "apps/web/package.json",
                "content": json.dumps({"dependencies": {"express": "^4.18.0"}}),
            },
        )
        assert result is None

    def test_write_file_ordinary_python_source_is_allowed(self) -> None:
        result = _policy_check(
            "write_file", {"path": "app/services/new_service.py", "content": "x = 1"}
        )
        assert result is None

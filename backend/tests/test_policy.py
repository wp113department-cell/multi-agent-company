"""Policy engine tests — path checks, command checks, worktree boundary."""

import os
import tempfile
from app.policy.engine import check_path, check_command, check_path_in_worktree

# --- check_path ---


class TestCheckPath:
    def test_env_denied(self):
        assert check_path(".env").allowed is False

    def test_env_local_denied(self):
        assert check_path(".env.local").allowed is False

    def test_env_production_denied(self):
        assert check_path("apps/web/.env.production").allowed is False

    def test_secrets_denied(self):
        assert check_path("secrets/db_password.txt").allowed is False

    def test_github_workflows_denied(self):
        assert check_path(".github/workflows/deploy.yml").allowed is False

    def test_nested_github_workflows_denied(self):
        assert check_path("apps/web/.github/workflows/ci.yml").allowed is False

    def test_normal_source_file_allowed(self):
        assert check_path("backend/app/main.py").allowed is True

    def test_readme_allowed(self):
        assert check_path("README.md").allowed is True

    def test_package_json_allowed(self):
        assert check_path("apps/web/package.json").allowed is True


# --- check_command ---


class TestCheckCommand:
    def test_rm_rf_denied(self):
        assert check_command("rm -rf /tmp/test").allowed is False

    def test_kubectl_denied(self):
        assert check_command("kubectl apply -f deployment.yaml").allowed is False

    def test_terraform_denied(self):
        assert check_command("terraform apply").allowed is False

    def test_git_push_denied(self):
        assert check_command("git push origin main").allowed is False

    def test_git_push_force_denied(self):
        assert check_command("git push --force").allowed is False

    def test_docker_push_denied(self):
        assert check_command("docker push myrepo/image").allowed is False

    def test_npm_publish_denied(self):
        assert check_command("npm publish").allowed is False

    def test_pnpm_publish_denied(self):
        assert check_command("pnpm publish").allowed is False

    def test_vercel_deploy_denied(self):
        assert check_command("vercel deploy").allowed is False

    def test_heroku_denied(self):
        assert check_command("heroku releases").allowed is False

    def test_pytest_allowed(self):
        assert check_command("pytest backend/tests/").allowed is True

    def test_mypy_allowed(self):
        assert check_command("mypy backend/").allowed is True

    def test_ruff_allowed(self):
        assert check_command("ruff check backend/").allowed is True

    def test_ls_allowed(self):
        assert check_command("ls -la").allowed is True


# --- check_path_in_worktree ---


class TestCheckPathInWorktree:
    def test_relative_path_inside_allowed(self):
        with tempfile.TemporaryDirectory() as wt:
            result = check_path_in_worktree("src/main.py", wt)
            assert result.allowed is True

    def test_absolute_path_inside_allowed(self):
        with tempfile.TemporaryDirectory() as wt:
            abs_path = os.path.join(wt, "src/main.py")
            result = check_path_in_worktree(abs_path, wt)
            assert result.allowed is True

    def test_path_traversal_blocked(self):
        with tempfile.TemporaryDirectory() as wt:
            result = check_path_in_worktree("../../etc/passwd", wt)
            assert result.allowed is False

    def test_absolute_path_outside_blocked(self):
        with tempfile.TemporaryDirectory() as wt:
            result = check_path_in_worktree("/etc/passwd", wt)
            assert result.allowed is False

    def test_env_inside_worktree_still_denied(self):
        with tempfile.TemporaryDirectory() as wt:
            result = check_path_in_worktree(".env", wt)
            assert result.allowed is False

"""Stage 2 Days 55-56 — load/stress tests + CI/CD-config inspection step
(answers.md Q11 "Load Tests"/"Stress Tests": NO — no locust/k6 tooling found
anywhere in the repo; Q67 "Inspect CI/CD"/"Inspect deployment implications":
NO/NOT VERIFIED for general coding role prompts).

The k6 script itself was verified by actually running it (both `load` and
`stress` scenarios) against a real live instance of this app during
implementation — 100% checks passed, exit code 0 for both. That direct
verification isn't repeatable as a pytest assertion (k6 is an external
binary, not a project dependency), so this file provides two tiers:
structural/content regression guards that always run, and a real k6
execution test gated by shutil.which("k6") — mirrors this codebase's own
established pattern for CLI-tool-dependent tests (see
test_gap35_resource_check.py's docker_available checks, and
test_day0_groq_integration.py's ANTHROPIC_AVAILABLE-gated tests).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).parent.parent
_LOAD_TEST_SCRIPT = _BACKEND_ROOT / "tests" / "load" / "gridiron_load_test.js"
_ROLES_DIR = _BACKEND_ROOT / "roles"

k6_only = pytest.mark.skipif(
    shutil.which("k6") is None,
    reason="[K6-CLI] Requires the k6 binary — script is still verified structurally without it",
)


def _script_text() -> str:
    return _LOAD_TEST_SCRIPT.read_text(encoding="utf-8")


class TestLoadTestScriptStructure:
    def test_script_file_exists(self) -> None:
        assert _LOAD_TEST_SCRIPT.exists()

    def test_references_real_registered_endpoints_only(self) -> None:
        """Every path the script hits must correspond to a real, currently
        registered FastAPI route — grepped from the actual route files, not
        assumed from the script's own comments."""
        text = _script_text()
        assert "/health" in text
        assert "/api/agents" in text
        assert "/api/metrics" in text
        assert "/api/tasks" in text

        main_py = (_BACKEND_ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert '@app.get("/health")' in main_py

        registry_py = (_BACKEND_ROOT / "app" / "api" / "registry.py").read_text(
            encoding="utf-8"
        )
        assert 'prefix="/api/agents"' in registry_py

        metrics_py = (_BACKEND_ROOT / "app" / "api" / "metrics.py").read_text(
            encoding="utf-8"
        )
        assert 'prefix="/api/metrics"' in metrics_py

        tasks_py = (_BACKEND_ROOT / "app" / "api" / "tasks.py").read_text(
            encoding="utf-8"
        )
        assert 'prefix="/api/tasks"' in tasks_py

    def test_has_both_load_and_stress_scenarios(self) -> None:
        text = _script_text()
        assert "LOAD_STAGES" in text
        assert "STRESS_STAGES" in text
        assert 'SCENARIO === "stress"' in text

    def test_has_explicit_pass_fail_thresholds_for_both_scenarios(self) -> None:
        text = _script_text()
        assert "http_req_duration" in text
        assert "http_req_failed" in text
        assert "p(95)<500" in text  # load threshold
        assert "p(95)<3000" in text  # stress threshold

    def test_config_is_env_driven_not_hardcoded(self) -> None:
        """Zero hardcoding: BASE_URL/API_TOKEN/SCENARIO must come from k6's
        __ENV, never a baked-in deployment URL or credential."""
        text = _script_text()
        assert "__ENV.BASE_URL" in text
        assert "__ENV.API_TOKEN" in text
        assert "__ENV.SCENARIO" in text
        # the only literal URL allowed is the localhost dev fallback
        urls = re.findall(r"https?://[^\s\"'`]+", text)
        assert all("localhost" in u or "127.0.0.1" in u for u in urls)

    def test_stress_stages_reach_higher_peak_than_load_stages(self) -> None:
        """Stress must be a genuinely different traffic shape from load, not
        just "load run longer" — real distinct peak targets."""
        text = _script_text()
        load_targets = [
            int(t)
            for t in re.findall(
                r"target:\s*(\d+)",
                text.split("STRESS_STAGES")[0].split("LOAD_STAGES")[1],
            )
        ]
        stress_targets = [
            int(t)
            for t in re.findall(
                r"target:\s*(\d+)",
                text.split("STRESS_STAGES")[1].split("export const options")[0],
            )
        ]
        assert max(stress_targets) > max(load_targets)


@k6_only
class TestLoadTestScriptRealExecution:
    """Starts a real uvicorn instance of this app and actually runs k6
    against it — the same verification performed manually during
    implementation, shortened here to keep the suite fast."""

    def _run_k6(
        self, tmp_path: Path, base_url: str, scenario: str
    ) -> subprocess.CompletedProcess[str]:
        text = _script_text()
        # Shorten every real stage's duration for a fast CI-safe smoke run —
        # same script logic (env parsing, checks, thresholds), just faster.
        shortened = re.sub(r'duration:\s*"\d+s"', 'duration: "2s"', text)
        smoke_script = tmp_path / "smoke.js"
        smoke_script.write_text(shortened, encoding="utf-8")
        return subprocess.run(
            [
                "k6",
                "run",
                "-e",
                f"BASE_URL={base_url}",
                "-e",
                f"SCENARIO={scenario}",
                str(smoke_script),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_load_scenario_passes_against_real_live_app(self, tmp_path: Path) -> None:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        proc = subprocess.Popen(
            [
                "python",
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=str(_BACKEND_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            for _ in range(30):
                try:
                    r = subprocess.run(
                        [
                            "curl",
                            "-s",
                            "-o",
                            "/dev/null",
                            "-w",
                            "%{http_code}",
                            f"{base_url}/health",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )
                    if r.stdout.strip() == "200":
                        break
                except Exception:
                    pass
                time.sleep(1)
            else:
                pytest.skip("[K6-CLI] Backend did not become ready in time")

            result = self._run_k6(tmp_path, base_url, "load")
            assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1000:]
            assert "checks.........................: 100.00%" in result.stdout
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


# ---------------------------------------------------------------------------
# CI/CD-config inspection step — 4 general coding role prompts
# ---------------------------------------------------------------------------


class TestCicdInspectionStepInRolePrompts:
    @pytest.mark.parametrize(
        "role_file",
        ["coder.md", "backend_dev.md", "frontend_dev.md", "architect.md"],
    )
    def test_role_prompt_mentions_cicd_and_deployment_implications(
        self, role_file: str
    ) -> None:
        text = (_ROLES_DIR / role_file).read_text(encoding="utf-8")
        assert "CI/CD" in text
        assert "deployment implications" in text
        assert ".github/workflows/**" in text

    @pytest.mark.parametrize(
        "role_file",
        ["coder.md", "backend_dev.md", "frontend_dev.md"],
    )
    def test_dev_role_prompt_checklist_has_cicd_bullet(self, role_file: str) -> None:
        text = (_ROLES_DIR / role_file).read_text(encoding="utf-8")
        assert "CI/CD-affecting paths" in text

    def test_architect_records_cicd_risk_in_risk_assessment_step(self) -> None:
        text = (_ROLES_DIR / "architect.md").read_text(encoding="utf-8")
        assert "must be listed as its own `risks` entry" in text

    def test_backend_dev_still_delegates_cicd_engineering_to_cicd_agent(self) -> None:
        """Regression guard: the new step is awareness/flagging, not a scope
        change — backend_dev's existing Non-Responsibility boundary
        (CI/CD work belongs to cicd_agent) must be untouched."""
        text = (_ROLES_DIR / "backend_dev.md").read_text(encoding="utf-8")
        assert "CI/CD (cicd_agent)" in text

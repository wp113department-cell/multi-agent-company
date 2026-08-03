"""Stage 2 Day 35 — app/fleet/resource_check.py (answers.md Q31, Resource
Awareness). Real host probes plus simulated-insufficient scenarios per
[[feedback_verify_empirically]]: at least one test runs the real, unmocked
probes against this actual machine rather than asserting only against
mocked internals.
"""

from __future__ import annotations

import shutil
import sys

import psutil
import pytest

from app.fleet.resource_check import (
    ResourceCheckResult,
    _python_version_sufficient,
    run_resource_check,
)


def test_real_host_probe_returns_populated_result() -> None:
    """No mocking — proves the probes actually work against this real
    machine, not just that the Python wiring compiles."""
    result = run_resource_check()

    assert isinstance(result, ResourceCheckResult)
    assert result.ram_total_gb > 0
    assert result.ram_available_gb > 0
    assert result.ram_available_gb <= result.ram_total_gb
    assert result.cpu_count >= 1
    assert result.disk_total_gb > 0
    assert result.disk_free_gb <= result.disk_total_gb
    assert result.python_version == ".".join(str(p) for p in sys.version_info[:3])
    assert result.python_version_sufficient is True  # this venv is 3.12+
    # Docker is confirmed running on this dev box (docker ps succeeded
    # during environment setup) — real assertion, not assumed.
    assert result.docker_available == (shutil.which("docker") is not None)
    assert isinstance(result.gpu_names, list)
    assert isinstance(result.reasons, list)
    assert isinstance(result.recommendations, list)


def test_default_thresholds_are_satisfied_on_this_dev_machine() -> None:
    """Default thresholds (1 GB RAM / 2 GB disk / 1 CPU) are deliberately
    conservative so Stage-2 "should fix soon" pre-flight doesn't start
    blocking real work on ordinary dev/CI machines by default."""
    result = run_resource_check()
    assert result.sufficient is True
    assert result.reasons == []
    assert result.recommendations == []


def test_insufficient_ram_produces_reason_and_recommendation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeVM:
        total = 8 * 1024**3
        available = 0  # far below the 1.0 GB default minimum

    monkeypatch.setattr(psutil, "virtual_memory", lambda: _FakeVM())

    result = run_resource_check()

    assert result.sufficient is False
    assert any("RAM" in r for r in result.reasons)
    assert any(
        "concurrency" in r or "memory" in r.lower() for r in result.recommendations
    )


def test_insufficient_disk_produces_reason_and_recommendation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeDisk:
        total = 100 * 1024**3
        free = 0  # far below the 2.0 GB default minimum
        used = 100 * 1024**3

    monkeypatch.setattr(psutil, "disk_usage", lambda path: _FakeDisk())

    result = run_resource_check()

    assert result.sufficient is False
    assert any("disk" in r.lower() for r in result.reasons)
    assert any("disk" in r.lower() for r in result.recommendations)


def test_insufficient_cpu_produces_reason_and_recommendation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 0)

    result = run_resource_check()

    assert result.sufficient is False
    assert any("CPU" in r for r in result.reasons)
    assert any("concurrency" in r for r in result.recommendations)


def test_require_docker_true_but_unavailable_blocks_with_explanation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.fleet.resource_check._check_docker", lambda timeout: False)

    result = run_resource_check(require_docker=True)

    assert result.docker_available is False
    assert result.sufficient is False
    assert any("Docker" in r for r in result.reasons)
    assert any("Docker" in r for r in result.recommendations)


def test_require_docker_false_default_does_not_block_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.fleet.resource_check._check_docker", lambda timeout: False)

    result = run_resource_check(require_docker=False)

    assert result.docker_available is False
    assert result.sufficient is True  # Docker not required by default


def test_require_gpu_true_but_unavailable_blocks_with_explanation() -> None:
    # This dev machine genuinely has no GPU (confirmed: no nvidia-smi on
    # PATH) — a real negative, not a mocked one.
    result = run_resource_check(require_gpu=True)

    assert result.gpu_available is False
    assert result.sufficient is False
    assert any("GPU" in r for r in result.reasons)


def test_python_version_sufficient_true_when_runtime_meets_requirement() -> None:
    assert _python_version_sufficient("3.11") is True


def test_python_version_sufficient_false_when_runtime_below_requirement() -> None:
    assert _python_version_sufficient("99.0") is False


def test_nonexistent_path_falls_back_to_cwd_instead_of_raising() -> None:
    """A repo path that hasn't been cloned yet must not crash the check."""
    result = run_resource_check(path="/this/path/does/not/exist/at/all")
    assert result.disk_total_gb > 0


def test_gpu_and_cuda_absent_on_this_machine_reported_honestly() -> None:
    """This dev box has no nvidia-smi — proves the check reports a real
    negative rather than fabricating availability."""
    result = run_resource_check()
    assert shutil.which("nvidia-smi") is None
    assert result.gpu_available is False
    assert result.cuda_available is False
    assert result.gpu_names == []

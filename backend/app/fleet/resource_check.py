"""Resource Awareness pre-flight check — Stage 2 Day 35 (answers.md Q31).

Probes real host resource availability (RAM, CPU, GPU, disk, Docker, Python,
Node, CUDA, virtualization) before expensive operations (epic start,
container-based test runs). Follows the same shape
`app/pipeline/cost_controller.py` already established for token cost:
compute a real number, compare it to a config threshold, and — if
insufficient — explain why and recommend an alternative instead of a silent
hard stop. This is a genuinely separate concern from
`app/fleet/budget_manager.py`'s `_current_memory_mb()`, which tracks this
*process's own* peak RSS after a run completes; this module probes the
*host's* available capacity before a run starts.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from app.config import get_settings


@dataclass(frozen=True)
class ResourceCheckResult:
    ram_total_gb: float
    ram_available_gb: float
    cpu_count: int
    cpu_percent: float
    disk_total_gb: float
    disk_free_gb: float
    docker_available: bool
    python_version: str
    python_version_sufficient: bool
    node_available: bool
    node_version: str | None
    gpu_available: bool
    gpu_names: list[str] = field(default_factory=list)
    cuda_available: bool = False
    virtualization: str | None = None
    sufficient: bool = True
    reasons: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


def _run_probe(
    cmd: list[str], timeout: float
) -> subprocess.CompletedProcess[str] | None:
    """Best-effort external probe — any failure (missing binary, timeout,
    permission error) is treated as "unavailable", never raised."""
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _check_docker(timeout: float) -> bool:
    if shutil.which("docker") is None:
        return False
    result = _run_probe(["docker", "info"], timeout)
    return result is not None and result.returncode == 0


def _check_node(timeout: float) -> tuple[bool, str | None]:
    if shutil.which("node") is None:
        return False, None
    result = _run_probe(["node", "--version"], timeout)
    if result is None or result.returncode != 0:
        return False, None
    return True, result.stdout.strip() or None


def _check_gpu_cuda(timeout: float) -> tuple[bool, list[str], bool]:
    """nvidia-smi presence + a successful query is treated as GPU-available;
    the plain (no-args) invocation's banner reports a "CUDA Version:" line
    when the installed driver supports CUDA — parsed directly rather than
    assumed from GPU presence alone, since a GPU can be present with a
    driver too old for the CUDA toolkit."""
    if shutil.which("nvidia-smi") is None:
        return False, [], False

    names_result = _run_probe(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], timeout
    )
    gpu_names = (
        [line.strip() for line in names_result.stdout.splitlines() if line.strip()]
        if names_result is not None and names_result.returncode == 0
        else []
    )
    gpu_available = len(gpu_names) > 0

    banner_result = _run_probe(["nvidia-smi"], timeout)
    cuda_available = (
        banner_result is not None
        and banner_result.returncode == 0
        and "CUDA Version:" in banner_result.stdout
    )
    return gpu_available, gpu_names, cuda_available


def _check_virtualization(timeout: float) -> str | None:
    """Real value ("kvm", "docker", "none", ...) when `systemd-detect-virt`
    is on PATH; otherwise honestly unknown (None) — never guessed."""
    if shutil.which("systemd-detect-virt") is None:
        return None
    result = _run_probe(["systemd-detect-virt"], timeout)
    if result is None:
        return None
    value = result.stdout.strip()
    return None if value in ("", "none") else value


def _python_version_sufficient(required: str) -> bool:
    required_major, required_minor = (int(part) for part in required.split(".")[:2])
    return sys.version_info[:2] >= (required_major, required_minor)


def run_resource_check(
    *,
    path: str | Path | None = None,
    require_docker: bool | None = None,
    require_gpu: bool | None = None,
) -> ResourceCheckResult:
    """Run all real, live probes and evaluate them against config thresholds.

    `path` selects which filesystem's free space to report (defaults to the
    current working directory) — pass the target repo's working path when
    checking ahead of a repo-scoped operation.
    """
    settings = get_settings()
    require_docker = (
        settings.resource_require_docker if require_docker is None else require_docker
    )
    require_gpu = settings.resource_require_gpu if require_gpu is None else require_gpu
    timeout = settings.resource_check_subprocess_timeout_seconds

    vm = psutil.virtual_memory()
    ram_total_gb = vm.total / (1024**3)
    ram_available_gb = vm.available / (1024**3)

    cpu_count = psutil.cpu_count(logical=True) or 0
    cpu_percent = psutil.cpu_percent(interval=0.1)

    disk_path = Path(path) if path is not None else Path.cwd()
    if not disk_path.exists():
        # Caller-supplied path (e.g. a repo not yet cloned) — fall back to
        # cwd rather than raising; this check must never crash its caller.
        disk_path = Path.cwd()
    disk = psutil.disk_usage(str(disk_path))
    disk_total_gb = disk.total / (1024**3)
    disk_free_gb = disk.free / (1024**3)

    docker_available = _check_docker(timeout)
    node_available, node_version = _check_node(timeout)
    gpu_available, gpu_names, cuda_available = _check_gpu_cuda(timeout)
    virtualization = _check_virtualization(timeout)

    python_version = ".".join(str(part) for part in sys.version_info[:3])
    python_version_sufficient = _python_version_sufficient(
        settings.resource_required_python_version
    )

    reasons: list[str] = []
    recommendations: list[str] = []

    if ram_available_gb < settings.resource_min_ram_gb:
        reasons.append(
            f"Available RAM ({ram_available_gb:.2f} GB) is below the required "
            f"minimum ({settings.resource_min_ram_gb} GB)"
        )
        recommendations.append(
            "Reduce agent concurrency or close other processes to free memory "
            "before starting this operation."
        )

    if disk_free_gb < settings.resource_min_disk_gb:
        reasons.append(
            f"Free disk space ({disk_free_gb:.2f} GB) is below the required "
            f"minimum ({settings.resource_min_disk_gb} GB)"
        )
        recommendations.append(
            "Free disk space (clear old worktrees, Docker images, or logs) "
            "before starting this operation."
        )

    if cpu_count < settings.resource_min_cpu_count:
        reasons.append(
            f"Logical CPU count ({cpu_count}) is below the required minimum "
            f"({settings.resource_min_cpu_count})"
        )
        recommendations.append(
            "Reduce configured concurrency caps (agent_run_slot / "
            "subtask_slot) to match available CPU cores, or run on a "
            "larger machine."
        )

    if not python_version_sufficient:
        reasons.append(
            f"Running Python {python_version}; this project requires >= "
            f"{settings.resource_required_python_version}"
        )
        recommendations.append("Upgrade the Python interpreter running the backend.")

    if require_docker and not docker_available:
        reasons.append(
            "Docker is required for this operation (e.g. sandboxed bash "
            "execution) but is not available or not running."
        )
        recommendations.append(
            "Install Docker or start the Docker daemon, or skip the "
            "Docker-dependent step if acceptable for this task."
        )

    if require_gpu and not gpu_available:
        reasons.append("A GPU is required for this operation but none was detected.")
        recommendations.append(
            "Run on a machine with a CUDA-capable GPU, or skip the "
            "GPU-dependent step if acceptable for this task."
        )

    return ResourceCheckResult(
        ram_total_gb=ram_total_gb,
        ram_available_gb=ram_available_gb,
        cpu_count=cpu_count,
        cpu_percent=cpu_percent,
        disk_total_gb=disk_total_gb,
        disk_free_gb=disk_free_gb,
        docker_available=docker_available,
        python_version=python_version,
        python_version_sufficient=python_version_sufficient,
        node_available=node_available,
        node_version=node_version,
        gpu_available=gpu_available,
        gpu_names=gpu_names,
        cuda_available=cuda_available,
        virtualization=virtualization,
        sufficient=not reasons,
        reasons=reasons,
        recommendations=recommendations,
    )

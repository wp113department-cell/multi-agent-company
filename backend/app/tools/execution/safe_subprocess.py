"""subprocess with the platform's secrets removed from the child's environment.

The code-running tools (run_python_snippet, run_node, run_script, run_make, run_tests,
run_single_test, type_check, run_linter, coverage_report, deps_outdated, find_unused_imports)
started their child processes with no `env=`, so the child inherited the server's whole
environment: ANTHROPIC_API_KEY, JWT_SECRET_KEY and DATABASE_URL were readable by any code an
agent ran — including code written by a prompt-injected agent, which can also reach the network.
(The coder's `bash` runs in the Docker sandbox with a minimal environment; these did not.)

Drop-in module: the tool files do `from app.tools.execution import safe_subprocess as subprocess`
and keep calling subprocess.run / Popen / check_output unchanged.
"""

from __future__ import annotations

import os
import re
import subprocess as _subprocess
from subprocess import (  # noqa: F401  (re-exported so callers keep using the same names)
    DEVNULL,
    PIPE,
    STDOUT,
    CalledProcessError,
    CompletedProcess,
    TimeoutExpired,
)
from typing import Any, Mapping

_SECRET_NAME = re.compile(
    r"(KEY|SECRET|TOKEN|PASSWORD|PASSWD|PWD|CREDENTIAL|AUTH|PRIVATE|DSN|COOKIE)", re.IGNORECASE
)
_SECRET_EXACT = frozenset({"DATABASE_URL", "REDIS_URL", "REDIS_URI", "MONGODB_URI", "AMQP_URL"})


def safe_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """`base` (default: the current environment) minus every variable that looks like a credential."""
    source = os.environ if base is None else base
    return {
        name: value
        for name, value in source.items()
        if name not in _SECRET_EXACT and not _SECRET_NAME.search(name)
    }


def _scrubbed(kwargs: dict[str, Any]) -> dict[str, Any]:
    kwargs["env"] = safe_env(kwargs.get("env"))
    return kwargs


def run(*args: Any, **kwargs: Any) -> "_subprocess.CompletedProcess[Any]":
    return _subprocess.run(*args, **_scrubbed(kwargs))


def check_output(*args: Any, **kwargs: Any) -> Any:
    return _subprocess.check_output(*args, **_scrubbed(kwargs))


def Popen(*args: Any, **kwargs: Any) -> "_subprocess.Popen[Any]":  # noqa: N802 - mirrors subprocess
    return _subprocess.Popen(*args, **_scrubbed(kwargs))

"""Production audit 11 (2026-10-02): secrets around agent bash commands.

1. extra_env (credential vault) values are masked in command output — the
   vault promised they never reach tool output, but `env` printed them.
2. Host mode (BASH_SANDBOX_ENABLED=false) no longer hands the backend's own
   API keys / database URL to agent commands.
Host mode is used here so no Docker is needed; real subprocesses run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.tools.execution.bash import _run_bash_command


@pytest.fixture()
def host_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "bash_sandbox_enabled", False)


def test_vault_value_is_masked_in_output(host_mode: None, tmp_path: Path) -> None:
    out, err, code, _ = _run_bash_command(
        "echo token=$THIRD_PARTY_API; echo also $THIRD_PARTY_API >&2",
        str(tmp_path),
        timeout=10,
        extra_env={"THIRD_PARTY_API": "sk-live-abc123XYZ"},
    )
    assert code == 0
    assert "sk-live-abc123XYZ" not in out + err
    assert "token=[REDACTED]" in out


def test_streamed_output_is_masked_too(host_mode: None, tmp_path: Path) -> None:
    chunks: list[str] = []
    _run_bash_command(
        "echo $THIRD_PARTY_API",
        str(tmp_path),
        timeout=10,
        extra_env={"THIRD_PARTY_API": "sk-live-abc123XYZ"},
        on_output=lambda _stream, chunk: chunks.append(chunk),
    )
    assert chunks and "sk-live-abc123XYZ" not in "".join(chunks)


def test_host_mode_hides_backend_secrets(
    host_mode: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "backend-secret-key-1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:pw@db/x")
    out, _, code, _ = _run_bash_command(
        'echo "[$ANTHROPIC_API_KEY][$DATABASE_URL][$PATH]"',
        str(tmp_path),
        timeout=10,
    )
    assert code == 0
    assert "backend-secret-key-1" not in out
    assert "postgresql://" not in out
    assert "[][]" in out and "/bin" in out, "ordinary env (PATH) must still pass"

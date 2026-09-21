"""Verification batch B6 (#101-#115, #133-#145) — the agent scaffold, checked across EVERY agent instead
of a sample: each `run_*` entry point is driven with `run_agent_graph` replaced by a recorder, and what
it would have sent to the model (role, tools, handlers, verification contract, model) is audited.
"""

from __future__ import annotations

import inspect
import importlib
import json
import pkgutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import app.agents as agents_pkg

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def captured(tmp_path_factory) -> dict[str, list[dict[str, Any]]]:
    repo = tmp_path_factory.mktemp("b6repo")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=a@b", "-c", "user.name=n", "commit", "-qm", "i"],
        cwd=repo,
        check=True,
    )

    calls: dict[str, list[dict[str, Any]]] = {}

    def recorder(name: str):
        def fake(*a: Any, **kw: Any) -> Any:
            calls.setdefault(name, []).append(kw)
            raise RuntimeError("captured")

        return fake

    for info in pkgutil.iter_modules(agents_pkg.__path__):
        if info.name in ("base_graph", "chat_agent"):
            continue
        mod = importlib.import_module(f"app.agents.{info.name}")
        if not hasattr(mod, "run_agent_graph"):
            continue
        runners = [
            f
            for n, f in inspect.getmembers(mod, inspect.isfunction)
            if n.startswith("run_")
            and f.__module__ == mod.__name__
            and n != "run_agent_graph"
        ]
        for fn in runners:
            kwargs: dict[str, Any] = {}
            for pname, p in inspect.signature(fn).parameters.items():
                if p.default is not inspect.Parameter.empty or p.kind in (
                    p.VAR_POSITIONAL,
                    p.VAR_KEYWORD,
                ):
                    continue
                ann = str(p.annotation)
                if "int" in ann:
                    kwargs[pname] = 1
                elif "str" in ann and any(
                    k in pname for k in ("path", "repo", "dir", "worktree")
                ):
                    kwargs[pname] = str(repo)
                elif "list" in ann:
                    kwargs[pname] = []
                elif "dict" in ann:
                    kwargs[pname] = {}
                else:
                    kwargs[pname] = "task text"
            with patch.object(mod, "run_agent_graph", recorder(info.name)):
                try:
                    fn(**kwargs)
                except Exception:
                    pass
    return calls


def test_the_audit_actually_reached_the_fleet(captured) -> None:
    assert len(captured) >= 70, sorted(captured)


def test_every_advertised_tool_has_a_handler(captured) -> None:
    """advertised-but-not-dispatched: the model is offered a tool the agent cannot run."""
    problems = []
    for name, calls in captured.items():
        for kw in calls:
            offered = [t["name"] for t in kw.get("tools", [])]
            missing = [t for t in offered if t not in kw.get("tool_handlers", {})]
            if missing:
                problems.append((name, missing))
    assert problems == []


def test_every_agent_loads_a_real_role_prompt(captured) -> None:
    from app.agents.base import load_role

    bad = []
    for name, calls in captured.items():
        role = calls[0].get("role_name")
        if (
            role and name != "bhaskar_agent"
        ):  # bhaskar_agent is bhaskar_tool's internal engine
            if (
                not (BACKEND / "roles" / f"{role}.md").is_file()
                or len(load_role(role)) < 200
            ):
                bad.append((name, role))
    assert bad == []


def test_every_agent_has_a_verification_contract(captured) -> None:
    bare = [
        name
        for name, calls in captured.items()
        if not (
            calls[0].get("verification_cfg") is not None
            and (
                calls[0]["verification_cfg"].set_by
                or calls[0]["verification_cfg"].enforce_in_result
            )
        )
    ]
    assert bare == []


def test_the_safety_and_learning_layers_are_on_fleet_wide(captured) -> None:
    for flag in (
        "enable_planning",
        "enable_memory",
        "enable_reflection",
        "enable_lesson",
    ):
        off = [n for n, c in captured.items() if not c[0].get(flag)]
        assert len(off) <= 1, (flag, off)  # at most one deliberately lean agent


def test_no_agent_hardcodes_a_model_id() -> None:
    offenders = []
    for path in (BACKEND / "app").rglob("*.py"):
        rel = path.relative_to(BACKEND).as_posix()
        if rel in ("app/config.py", "app/fleet/model_router.py"):
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if '"claude-' in code or "'claude-" in code:
                offenders.append(f"{rel}:{i}")
    assert offenders == []


# ------------------------------------------------------------------ architecture map (#128)


def test_architecture_map_survives_a_fenced_json_reply(tmp_path) -> None:
    """Claude fences JSON even when told 'JSON only'; the bare json.loads failed every attempt and
    the map was never built."""
    from app.repo_tools.architecture_mapper import (
        ArchitectureMap,
        build_architecture_map,
    )
    from app.repo_tools.scanner import index_repository

    (tmp_path / "app.py").write_text("print(1)\n")
    idx = index_repository(str(tmp_path))
    payload = {
        "summary": "A tiny app",
        "components": [
            {"name": "core", "description": "does things", "key_files": ["app.py"]}
        ],
    }
    block = MagicMock()
    block.text = "Here is the map:\n```json\n" + json.dumps(payload) + "\n```\n"
    response = MagicMock()
    response.content = [block]
    with patch("anthropic.Anthropic") as anth:
        anth.return_value.messages.create.return_value = response
        result = build_architecture_map(str(tmp_path), idx)
    assert isinstance(result, ArchitectureMap) and result.summary == "A tiny app"


# ------------------------------------------------------------------ credential handling (#125)

SECRETS = {
    "anthropic": "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJ-abcdef",
    "openai_project": "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGH",
    "github_pat": "github_pat_11ABCDEFG0abcdefghijkl_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghijklmnopqrstuv",
    "jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    "stripe": "sk_live_abcdefghijklmnopqrstuvwx",
    "google": "AIzaSyA1234567890abcdefghijklmnopqrstuvw"[:39],
}


@pytest.mark.parametrize("name", sorted(SECRETS))
def test_provider_tokens_are_redacted_from_agent_output_and_blocked_from_commits(
    name,
) -> None:
    from app.agents.tool_security import (
        _redact_secrets_in_text,
        _scan_content_for_secrets,
    )

    secret = SECRETS[name]
    text = f"the value is {secret} ok"
    redacted, found = _redact_secrets_in_text(text)
    assert found and secret not in redacted and secret[10:] not in redacted
    assert _scan_content_for_secrets(text) is not None


def test_db_url_passwords_and_bearer_tokens_are_redacted() -> None:
    from app.agents.tool_security import _redact_secrets_in_text

    out, found = _redact_secrets_in_text(
        "DATABASE_URL=postgresql://gridiron:s3cretPass99@db:5432/x\nAuthorization: Bearer abcdefghijklmnop1234567890"
    )
    assert (
        found and "s3cretPass99" not in out and "abcdefghijklmnop1234567890" not in out
    )
    assert (
        "postgresql://gridiron:" in out and "@db:5432/x" in out
    )  # the rest stays readable


def test_every_token_on_a_line_is_redacted_not_just_the_first() -> None:
    from app.agents.tool_security import _redact_secrets_in_text

    a, b = SECRETS["anthropic"], "ghp_16C7e42F292c6912E7710c838347Ae178B4a"
    out, _ = _redact_secrets_in_text(f"{b} then {a}")
    assert a[8:] not in out and b[8:] not in out


def test_masking_a_password_reveals_nothing_but_a_provider_token_keeps_its_prefix() -> (
    None
):
    from app.agents.tool_security import _mask_secret_value

    assert _mask_secret_value("DB_PASSWORD", "hunter2hunter2") == "***REDACTED"
    assert _mask_secret_value(
        "TOKEN", "ghp_16C7e42F292c6912E7710c838347Ae178B4a"
    ).startswith("ghp_16")


def test_ordinary_text_is_left_alone() -> None:
    from app.agents.tool_security import (
        _redact_secrets_in_text,
        _scan_content_for_secrets,
    )

    text = "see https://example.com/a/b and postgresql://user@db:5432/x, version 1.2.3, sk-short"
    assert _redact_secrets_in_text(text) == (text, False)
    assert _scan_content_for_secrets(text) is None

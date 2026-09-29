"""Production audit 05 (2026-09-29) — command policy gaps found by the executed
probe What_is/AUDIT_REPORT/evidence/policy_probe.py:

1. Shell quote/escape splitting defeated every pattern: `r''m -rf /` was ALLOWED.
2. Cloud control-plane CLIs were ALLOWED (`aws s3 rm s3://b --recursive`)
   while kubectl/terraform were denied.
"""

from __future__ import annotations

import pytest

from app.policy.engine import check_command, is_command_override_eligible

BYPASSES = [
    "r''m -rf /",
    'r""m -rf /',
    "'rm' '-rf' /",
    "r\\m -rf /",
    "ls; r''m -fr ~",
    "su''do ls",
    "doc''ker push img",
    "git pu''sh origin main",
]

CLOUD = [
    "aws s3 rm s3://bucket --recursive",
    "aws ec2 terminate-instances --instance-ids i-1",
    "AWS_PROFILE=prod aws s3 ls",
    "ls && gcloud compute instances delete vm1",
    "az group delete -n rg",
    "gsutil rm -r gs://b",
    "doctl compute droplet delete x",
    "flyctl deploy",
    "fly deploy",
    "railway up",
    "netlify deploy --prod",
    "firebase deploy",
    "serverless deploy",
    "vercel --prod",
    "echo $(aws sts get-caller-identity)",
]

HARMLESS = [
    "pytest -q",
    "ls -la",
    "git status",
    "grep -rn az src",
    "grep -rn aws docs/",
    "echo 'deploying is a human action'",
    "cat README.md",
    "python -c 'print(1)'",
    "git commit -m 'update fly config docs'",
    "ls .aws_mock",
    "cd azure_helpers && ls",
    "npm run build",
]


@pytest.mark.parametrize("cmd", BYPASSES)
def test_quote_and_escape_splitting_no_longer_bypasses(cmd: str) -> None:
    assert not check_command(cmd).allowed, cmd


@pytest.mark.parametrize("cmd", CLOUD)
def test_cloud_cli_is_denied(cmd: str) -> None:
    assert not check_command(cmd).allowed, cmd


@pytest.mark.parametrize("cmd", HARMLESS)
def test_look_alike_harmless_commands_still_allowed(cmd: str) -> None:
    assert check_command(cmd).allowed, cmd


def test_cloud_cli_stays_human_overridable_but_rm_rf_does_not() -> None:
    assert is_command_override_eligible("aws s3 ls")
    assert not is_command_override_eligible("r''m -rf /")

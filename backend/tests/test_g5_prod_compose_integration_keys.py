"""G5 (2026-10-19): every integration key the code reads from the
environment reaches the production backend and worker.

The Slack and Linear tools read SLACK_WEBHOOK_URL / LINEAR_API_KEY from the
process environment, but docker-compose.prod.yml never passed them (the same
gap A43 found for ALERT_WEBHOOK_URL), so in production these tools could not
be enabled. The live Slack check on 2026-10-19 sent a real message.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
KEYS = [
    "SLACK_WEBHOOK_URL",
    "LINEAR_API_KEY",
    "FIRECRAWL_API_KEY",
    "ALERT_WEBHOOK_URL",
    "ALERT_WEBHOOK_SECRET",
]


@pytest.mark.parametrize("service", ["backend", "worker"])
def test_integration_keys_reach_production(service: str) -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text())
    env = compose["services"][service]["environment"]
    assert [k for k in KEYS if k not in env] == []


def test_integration_keys_are_documented() -> None:
    example = (ROOT / "backend" / ".env.example").read_text()
    assert [k for k in KEYS if f"\n{k}=" not in example] == []

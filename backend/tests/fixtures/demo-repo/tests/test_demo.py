"""Tests for demo_module — used by specialist-agent fixture tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from demo_module import greet, multiply


def test_greet_returns_string() -> None:
    result = greet("Alice")
    assert isinstance(result, str)
    assert "Alice" in result


def test_multiply_integers() -> None:
    assert multiply(3, 4) == 12
    assert multiply(0, 100) == 0
    assert multiply(-2, 5) == -10

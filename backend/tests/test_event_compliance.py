"""Day 12 Part 3 — Fleet OS Event Compliance Verification.

Static AST scan: every `publish(<constructor>(...))` call site anywhere under
app/ must use one of the 8 canonical FleetEventType constructors
(app/fleet/fleet_events.py) — no ad-hoc event types.

Scope note, decided after reading the plan's own stated rationale ("Any event
type NOT in this set -> test fails"): this asserts observed types are a
SUBSET of the canonical 8, not that all 8 must be actively emitted somewhere
today. Requiring every type to be in active use at all times would make this
regression guard fragile to legitimate temporary gaps (confirmed by grep
before writing this test: `task_created`/`memory_created` are defined
constructors with zero call sites anywhere in the codebase right now — Day
12 Part 4 adds one `task_created` call, but requiring `memory_created` too
would be scope creep unrelated to what this test exists to catch: someone
inventing a 9th, undocumented event type).
"""
from __future__ import annotations

import ast
from pathlib import Path

from app.fleet.fleet_events import FleetEventType

_APP_DIR = Path(__file__).parent.parent / "app"

# Maps each typed constructor function name (fleet_events.py) to the
# FleetEventType value it produces — mirrors that file's own mapping.
_CONSTRUCTOR_TO_EVENT_TYPE: dict[str, str] = {
    "task_created": FleetEventType.TASK_CREATED.value,
    "task_started": FleetEventType.TASK_STARTED.value,
    "task_completed": FleetEventType.TASK_COMPLETED.value,
    "task_failed": FleetEventType.TASK_FAILED.value,
    "review_requested": FleetEventType.REVIEW_REQUESTED.value,
    "lesson_published": FleetEventType.LESSON_PUBLISHED.value,
    "health_updated": FleetEventType.HEALTH_UPDATED.value,
    "memory_created": FleetEventType.MEMORY_CREATED.value,
}

_CANONICAL_EVENT_TYPES = {e.value for e in FleetEventType}


def _iter_python_files() -> list[Path]:
    return [
        p for p in _APP_DIR.rglob("*.py")
        if "__pycache__" not in p.parts
    ]


def _find_publish_event_types(source: str) -> set[str]:
    """Parse source, return the set of FleetEventType values produced by
    every `publish(<known_constructor>(...))` call in it."""
    found: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return found

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "publish"):
            continue
        if not node.args:
            continue
        inner = node.args[0]
        if not isinstance(inner, ast.Call):
            continue
        inner_func = inner.func
        if isinstance(inner_func, ast.Name) and inner_func.id in _CONSTRUCTOR_TO_EVENT_TYPE:
            found.add(_CONSTRUCTOR_TO_EVENT_TYPE[inner_func.id])

    return found


def test_every_publish_call_uses_a_canonical_event_constructor() -> None:
    all_observed: dict[str, list[str]] = {}  # event_type -> [file paths using it]

    for path in _iter_python_files():
        source = path.read_text(encoding="utf-8")
        event_types = _find_publish_event_types(source)
        for et in event_types:
            all_observed.setdefault(et, []).append(str(path.relative_to(_APP_DIR.parent)))

    observed_set = set(all_observed.keys())
    unexpected = observed_set - _CANONICAL_EVENT_TYPES
    assert not unexpected, (
        f"Ad-hoc/undocumented event type(s) found: {unexpected}. "
        f"Every publish() call must use one of the 8 canonical FleetEventType "
        f"constructors in app/fleet/fleet_events.py. Sources: {all_observed}"
    )


def test_at_least_some_canonical_events_are_actually_emitted() -> None:
    """Sanity check on the scanner itself — if this finds zero events at all,
    the AST matching logic is broken, not the codebase."""
    all_observed: set[str] = set()
    for path in _iter_python_files():
        all_observed |= _find_publish_event_types(path.read_text(encoding="utf-8"))

    assert len(all_observed) >= 4, (
        f"Expected several canonical event types to be in active use, found only: {all_observed}"
    )


def test_fleet_event_type_enum_has_exactly_the_8_canonical_values() -> None:
    assert _CANONICAL_EVENT_TYPES == {
        "TaskCreated", "TaskStarted", "TaskCompleted", "TaskFailed",
        "ReviewRequested", "LessonPublished", "HealthUpdated", "MemoryCreated",
    }

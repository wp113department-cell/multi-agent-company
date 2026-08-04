"""Add a real CHECK constraint on dev_tasks.priority — gap-closure Stage 4
Tier 3 (2026-08-05, answer2.md Q2: "DevTask.priority not DB-enforced").

Before this, `priority` was `String(20)` with zero validation anywhere in
the stack — any string (a typo, an empty string, arbitrary garbage) could
reach the column unchecked via any write path that isn't the one HTTP API
endpoint (app/api/tasks.py::CreateTaskRequest, which this same gap-closure
pass tightened to `Literal["low", "medium", "high"]` — Pydantic validation
alone doesn't cover internal/programmatic writes that bypass that endpoint,
which is what this migration is for).

Confirmed safe before writing this: every existing dev_tasks row already
has priority='medium' (queried live — 38/38 rows), so no data cleanup is
needed before adding the constraint.

Not the same as `status`'s own validation (VALID_TRANSITIONS/
can_transition() in app/db/models.py) — status is a state machine (which
transitions are valid FROM the current value matters), priority is not
(any of the 3 values is valid at any time), so a plain CHECK constraint is
the right-sized fix here rather than a parallel Python state-machine
validator.

Revision ID: 027
Revises: 026
Create Date: 2026-08-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "027"
down_revision: Union[str, None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT_NAME = "ck_dev_tasks_priority_valid_values"


def upgrade() -> None:
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "dev_tasks",
        "priority IN ('low', 'medium', 'high')",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "dev_tasks", type_="check")

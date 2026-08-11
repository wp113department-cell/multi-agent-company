"""Add task_logs.rationale — a typed decision-rationale column.

AUDIT_Q_BATCH13 §44 "Explainability": no model anywhere had a typed
rationale/reasoning column (task_logs.extra_data is generic, untyped JSONB
used for many unrelated purposes). This is additive: append_log() gains an
optional rationale kwarg (defaults None), so every existing caller is
unaffected; only call sites that carry a real, computed decision rationale
(e.g. FleetManager.select()'s DispatchPlan.reason) set it.

Nullable, no backfill: legacy rows predating this column correctly have no
rationale rather than a guessed one.

Revision ID: 040
Revises: 039
Create Date: 2026-08-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "040"
down_revision: Union[str, None] = "039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("task_logs", sa.Column("rationale", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("task_logs", "rationale")

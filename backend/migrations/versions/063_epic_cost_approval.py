"""Record epic cost approval — Qoder cross-check H-5 (2026-10-02)

"Approve Cost & Start Agents" set the epic back to pending and relaunched the
epic manager, whose first node re-estimated the same cost and halted at
pending_cost_approval again: an approved over-threshold epic could never
start. These columns make the approval durable; the cost node skips the gate
while the estimate stays within the approved amount.

Revision ID: 063
Revises: 062
Create Date: 2026-10-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "063"
down_revision: Union[str, None] = "062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "epics", sa.Column("cost_approved_usd", sa.Numeric(10, 4), nullable=True)
    )
    op.add_column("epics", sa.Column("cost_approved_by", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("epics", "cost_approved_by")
    op.drop_column("epics", "cost_approved_usd")

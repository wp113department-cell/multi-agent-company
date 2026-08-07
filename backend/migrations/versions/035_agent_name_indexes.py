"""Add index on pending_approvals.agent_name and epic_scratchpad.agent_name

Blocker (AUDIT_Q_BATCH05_PERFORMANCE_ARCHITECTURE.md §46 "DB indexing on
frequently-filtered columns"): both tables index their sibling `status`/
`epic_id` columns but not `agent_name`, despite it being a common filter
column (e.g. "show pending approvals for agent X", "show scratchpad entries
written by agent X") — every such query does a sequential scan.

Revision ID: 035
Revises: 034
Create Date: 2026-08-07
"""

from typing import Sequence, Union

from alembic import op

revision: str = "035"
down_revision: Union[str, None] = "034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_pending_approvals_agent_name",
        "pending_approvals",
        ["agent_name"],
        unique=False,
    )
    op.create_index(
        "ix_epic_scratchpad_agent_name",
        "epic_scratchpad",
        ["agent_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_epic_scratchpad_agent_name", table_name="epic_scratchpad")
    op.drop_index("ix_pending_approvals_agent_name", table_name="pending_approvals")

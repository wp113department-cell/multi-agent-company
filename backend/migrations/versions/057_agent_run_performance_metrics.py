"""Add retries/verification_pct/confidence/tool_accuracy to agent_runs —
T2-B7 gap-closure (2026-09-24, GRIDIRON_PARTIAL #407 "Per-agent performance
metrics aggregated over time (persisted, not just ring buffer)")

See app/db/models.py::AgentRun's own comment for the full design note.

Revision ID: 057
Revises: 056
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "057"
down_revision: Union[str, None] = "056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("retries", sa.Integer(), nullable=True))
    op.add_column("agent_runs", sa.Column("verification_pct", sa.Float(), nullable=True))
    op.add_column("agent_runs", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("agent_runs", sa.Column("tool_accuracy", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "tool_accuracy")
    op.drop_column("agent_runs", "confidence")
    op.drop_column("agent_runs", "verification_pct")
    op.drop_column("agent_runs", "retries")

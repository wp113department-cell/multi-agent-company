"""Add citation_hallucination_count to agent_runs — #443 gap-closure
(2026-09-28, GRIDIRON_PARTIAL "Detect hallucinating agents / memory leaks
/ sync failures")

See app/db/models.py::AgentRun's own comment for the full design note.

Revision ID: 061
Revises: 060
Create Date: 2026-09-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "061"
down_revision: Union[str, None] = "060"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("citation_hallucination_count", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "citation_hallucination_count")

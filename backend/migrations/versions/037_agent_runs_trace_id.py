"""Add agent_runs.trace_id — links a durable agent_runs row to the actual
LangGraph checkpointer thread_id (run_agent_graph()'s own `tid`) it was
checkpointed under.

AUDIT_Q_BATCH08 §14 "Recovery after reboot"/"Continue from checkpoint if
interrupted": previously there was no stored link between an agent_runs row
(what app/fleet/failure_ladder.py::reconcile_orphaned_runs() queries for
crash/orphan recovery) and the Postgres-backed LangGraph checkpoint its
worker-agent run actually lives under — an orphaned run's checkpoint state
existed, but nothing could look it up starting from the DB row alone. This
column is real, additive forward progress toward that (making the
checkpoint genuinely traceable/auditable per run); see
app/db/models.py::AgentRun.trace_id's own docstring for why full automatic
cross-restart resume remains a deliberately separate, larger decision.

Nullable, no backfill: legacy rows predating this column correctly have no
trace_id rather than a guessed one.

Revision ID: 037
Revises: 036
Create Date: 2026-08-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "037"
down_revision: Union[str, None] = "036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_runs", sa.Column("trace_id", sa.String(length=100), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "trace_id")

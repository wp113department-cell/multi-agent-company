"""Add agents_scores table — AUDIT_Q_BATCH15 §117 gap-closure (2026-08-11)

quality_score.py's aggregator listed "agents" as a real, working producer
(benchmark_manager.py/agent_benchmarks) excluded only because it's scoped by
agent_name, not repo_id — one agent runs across many repos. This table
stores the per-repo resolution: for a given repo_id, the real set of
agent_names that actually ran against that repo (via a join through
agent_runs.task_id -> dev_tasks.repo_id) and the mean of those agents'
already-real, already-persisted baseline benchmark_score
(agent_benchmarks.is_baseline=True). Mirrors architecture_scores (migration
028) exactly for shape and repo_id nullability semantics.

Revision ID: 042
Revises: 041
Create Date: 2026-08-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "042"
down_revision: Union[str, None] = "041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agents_scores",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "repo_id",
            sa.BigInteger(),
            sa.ForeignKey("repos.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("agent_names", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("per_agent_scores", JSONB(), nullable=False, server_default="{}"),
        sa.Column("agents_score", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_agents_scores_repo_id", "agents_scores", ["repo_id"])


def downgrade() -> None:
    op.drop_index("ix_agents_scores_repo_id", table_name="agents_scores")
    op.drop_table("agents_scores")

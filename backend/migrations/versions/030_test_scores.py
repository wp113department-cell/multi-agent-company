"""Add test_scores table — Stage 4 Cluster Q, Tests slice dedicated
persistence added while building the cross-category aggregation layer
(2026-08-05, STAGE4_BACKLOG.md)

The Tests slice's coverage_pct (test_coverage_agent's submit schema) was
already captured and persisted, but only inside the generic `artifacts`
table's opaque JSON payload — that table has no `repo_id` column and no
dedicated read-back function, unlike architecture_scores/security_scores
(migrations 028/029). This table brings Tests to the same structural bar,
a real prerequisite for uniform cross-category aggregation — not a
redesign of the existing artifact-persistence path, which is unchanged.

test_score is coverage_pct normalized to [0.0, 1.0] so it combines
meaningfully with architecture_score/security_score, which are already on
that scale. Only ever written when the run's coverage_measured
verification flag is real True and a coverage_pct was actually reported.

repo_id follows Cluster O's established single source of truth (ADR 006):
resolved from DevTask.repo_id, nullable for the same reason
architecture_scores.repo_id / security_scores.repo_id are nullable.

Revision ID: 030
Revises: 029
Create Date: 2026-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "030"
down_revision: Union[str, None] = "029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "test_scores",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column(
            "repo_id",
            sa.BigInteger(),
            sa.ForeignKey("repos.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("coverage_pct", sa.Float(), nullable=False),
        sa.Column("test_score", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_test_scores_task_id", "test_scores", ["task_id"])
    op.create_index("ix_test_scores_repo_id", "test_scores", ["repo_id"])


def downgrade() -> None:
    op.drop_index("ix_test_scores_repo_id", table_name="test_scores")
    op.drop_index("ix_test_scores_task_id", table_name="test_scores")
    op.drop_table("test_scores")

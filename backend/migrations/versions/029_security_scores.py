"""Add security_scores table — Stage 4 Cluster Q Security slice (2026-08-05,
STAGE4_BACKLOG.md)

Each row is one dependency_security_agent run's real, independently
computed `pip-audit --format=json` result against the target repo's
requirements.txt. Verified before this migration: pip-audit's real JSON
schema (pip_audit._service.interface.VulnerabilityResult, confirmed by
reading the installed package, not assumed) has no severity field
(id/description/fix_versions/aliases/published only) — so this table
stores a real vulnerability COUNT, not a severity-weighted score, honestly
matching what the tool actually reports. Mirrors architecture_scores
(migration 028) for the same "one row per verified run" shape, minus the
per-severity breakdown that table has and this one genuinely can't.

Only ever written when the run's `audited` verification flag is real True
— an unverified run's tool-use claim isn't grounded, so no row is written.

Node/npm dependency scoring is a documented, separate gap not covered
here — see STAGE4_BACKLOG.md's Cluster Q Security slice.

repo_id follows Cluster O's established single source of truth (ADR 006):
resolved from DevTask.repo_id, nullable for the same reason
architecture_scores.repo_id / memory_embeddings.repo_id are nullable.

Revision ID: 029
Revises: 028
Create Date: 2026-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "029"
down_revision: Union[str, None] = "028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "security_scores",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column(
            "repo_id",
            sa.BigInteger(),
            sa.ForeignKey("repos.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("vulnerable_package_count", sa.Integer(), nullable=False),
        sa.Column("total_vuln_count", sa.Integer(), nullable=False),
        sa.Column("security_score", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_security_scores_task_id", "security_scores", ["task_id"])
    op.create_index("ix_security_scores_repo_id", "security_scores", ["repo_id"])


def downgrade() -> None:
    op.drop_index("ix_security_scores_repo_id", table_name="security_scores")
    op.drop_index("ix_security_scores_task_id", table_name="security_scores")
    op.drop_table("security_scores")

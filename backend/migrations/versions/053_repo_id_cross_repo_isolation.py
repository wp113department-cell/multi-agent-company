"""Add nullable repo_id FK to events/artifacts/pending_approvals/
epic_scratchpad — T2-B6 gap-closure (2026-09-22, GRIDIRON_PARTIAL #383
"Full cross-repo isolation (every table)")

These 4 tables were the remaining ones with no repo_id at all, per the
audit's own list. Mirrors the exact migration pattern already proven once
for indexed_files/call_edges/code_embeddings (migration 043): additive,
nullable, NULL = unscoped/legacy — existing task_id/epic_id filters remain
the real query key unchanged, repo_id is populated opportunistically going
forward wherever the real caller already knows it.

Revision ID: 053
Revises: 052
Create Date: 2026-09-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "053"
down_revision: Union[str, None] = "052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("events", "artifacts", "pending_approvals", "epic_scratchpad")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "repo_id",
                sa.BigInteger(),
                sa.ForeignKey("repos.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index(f"ix_{table}_repo_id", table, ["repo_id"])


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"ix_{table}_repo_id", table_name=table)
        op.drop_column(table, "repo_id")

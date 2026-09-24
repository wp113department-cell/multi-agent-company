"""Add roadmaps and roadmap_items tables — T2-B10 gap-closure (2026-09-24,
GRIDIRON_PARTIAL #498/#484 "Roadmap tracked, sequenced, and re-sequenced
against real progress" / "Product Management (roadmap/strategy)")

See app/db/models.py::Roadmap/RoadmapItem's own comments for the full
design note.

Revision ID: 060
Revises: 059
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "060"
down_revision: Union[str, None] = "059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "roadmaps",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "repo_id",
            sa.BigInteger(),
            sa.ForeignKey("repos.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("dev_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_roadmaps_repo_id", "roadmaps", ["repo_id"])

    op.create_table(
        "roadmap_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "roadmap_id",
            sa.BigInteger(),
            sa.ForeignKey("roadmaps.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phase", sa.String(length=100), nullable=False),
        sa.Column("initiative", sa.Text(), nullable=False),
        sa.Column("impact", sa.String(length=50), nullable=True),
        sa.Column("effort", sa.String(length=50), nullable=True),
        sa.Column("confidence", sa.String(length=50), nullable=True),
        sa.Column("dependencies", ARRAY(sa.Text()), nullable=True),
        sa.Column("sequence_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="planned"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_roadmap_items_roadmap_id", "roadmap_items", ["roadmap_id"])


def downgrade() -> None:
    op.drop_index("ix_roadmap_items_roadmap_id", table_name="roadmap_items")
    op.drop_table("roadmap_items")
    op.drop_index("ix_roadmaps_repo_id", table_name="roadmaps")
    op.drop_table("roadmaps")

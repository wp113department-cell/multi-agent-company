"""Add category column to memory_embeddings; document retention policy

Adds a 'category' column to memory_embeddings so that memories can be tagged
as task | architecture | failure | learning — matching Doc 11 (Memory System Specification).

Revision ID: 010
Revises: 009
Create Date: 2026-07-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "memory_embeddings",
        sa.Column(
            "category",
            sa.String(50),
            nullable=False,
            server_default="task",
        ),
    )
    op.create_index("ix_memory_embeddings_category", "memory_embeddings", ["category"])


def downgrade() -> None:
    op.drop_index("ix_memory_embeddings_category", table_name="memory_embeddings")
    op.drop_column("memory_embeddings", "category")

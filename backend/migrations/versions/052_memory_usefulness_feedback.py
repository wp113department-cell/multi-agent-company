"""Add helpful_count/not_helpful_count to memory_embeddings — T2-B4
gap-closure (2026-09-22, GRIDIRON_PARTIAL #98 "Memory Quality Control
(accuracy validation)")

A real per-use usefulness signal, distinct from `verified` (write-time
outcome boolean) and the existing MemoryQualityDecision content gate
(authorship quality at write time) — neither ever asked "did retrieving and
using THIS memory actually help." See app/db/models.py::MemoryEmbedding's
own comment for the full design note.

Revision ID: 052
Revises: 051
Create Date: 2026-09-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "052"
down_revision: Union[str, None] = "051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "memory_embeddings",
        sa.Column("helpful_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "memory_embeddings",
        sa.Column(
            "not_helpful_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )


def downgrade() -> None:
    op.drop_column("memory_embeddings", "not_helpful_count")
    op.drop_column("memory_embeddings", "helpful_count")

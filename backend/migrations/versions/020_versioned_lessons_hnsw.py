"""Add HNSW index to versioned_lessons.embedding

Audit 03 gap-closure (2026-07-24): memory_embeddings got an HNSW index in
migration 004, but versioned_lessons (added 10 migrations later, same
pgvector Vector(1536) column type) never did. _find_most_similar_published()
runs a cosine-distance ORDER BY on this column on every publish() call
(every lesson extraction fleet-wide when VOYAGE_API_KEY is set) — without
this index it's a full sequential scan.

Revision ID: 020
Revises: 019
Create Date: 2026-07-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS versioned_lessons_embedding_hnsw "
        "ON versioned_lessons USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS versioned_lessons_embedding_hnsw")

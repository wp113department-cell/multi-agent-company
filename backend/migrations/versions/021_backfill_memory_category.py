"""Backfill mistagged category values on memory_embeddings

Audit 03 gap-closure (2026-07-24): embed_architecture_note()/embed_failure()
never set category=, so every existing architecture/failure row was silently
tagged category="task" (the ORM's Python-side default) instead of matching
its real outcome. The application code is fixed separately (app/memory/store.py);
this is the one-time data correction for rows written before that fix.

Revision ID: 021
Revises: 020
Create Date: 2026-07-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE memory_embeddings SET category = outcome "
        "WHERE outcome IN ('architecture', 'failure') AND category != outcome"
    )


def downgrade() -> None:
    # Not reversible without knowing which rows this migration actually
    # touched vs. were already correct — intentionally a no-op. The prior
    # (wrong) state was itself a bug, not a value worth restoring.
    pass

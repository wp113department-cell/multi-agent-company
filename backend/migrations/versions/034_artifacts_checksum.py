"""Add content_sha256 checksum column to artifacts

Blocker (audit_v1.md 4.6 #4 / L-Phase): "No checksum/integrity verification
on artifacts in either backend — silent disk corruption or a corrupted S3
object would be returned to a caller (e.g. a diff rendered in Mission
Control, or test results fed into a QA gate) with no detection."

Revision ID: 034
Revises: 033
Create Date: 2026-08-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "034"
down_revision: Union[str, None] = "033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "artifacts", sa.Column("content_sha256", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("artifacts", "content_sha256")

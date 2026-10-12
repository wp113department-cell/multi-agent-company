"""Remove chat project notes (C6, owner decision 2026-10-12)

The chat now only answers questions about a project; the editable project
notes it used (C3) were removed with their API. Their stored rows
(system_settings "project-notes:<id>") would otherwise keep people's names
in a feature that no longer exists, outside the privacy export and erasure,
so they are deleted. Downgrade cannot bring the notes back.

Revision ID: 070
Revises: 069
Create Date: 2026-10-12
"""

from typing import Sequence, Union

from alembic import op

revision: str = "070"
down_revision: Union[str, None] = "069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM system_settings WHERE key LIKE 'project-notes:%'")


def downgrade() -> None:
    pass  # the deleted notes cannot be restored

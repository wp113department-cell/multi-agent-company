"""Token version per user (Sol A12, 2026-10-09)

A sign-in token stayed valid for its whole lifetime even after the
password was changed or the user signed out — a copied token kept working.
Tokens now carry the user's token_version; changing the password or
signing out raises it, so every older token is refused. Purely additive
(existing users start at 0; tokens issued before this carry none and count
as 0, so nobody is signed out by the upgrade itself).

Revision ID: 068
Revises: 067
Create Date: 2026-10-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "068"
down_revision: Union[str, None] = "067"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")

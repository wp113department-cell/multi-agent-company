"""Add EnhancementRequest impact-simulation + quality-decline-rollback
columns — AUDIT_Q_BATCH18 §69 gap-closure (2026-08-12)

"Autonomous Quality Improvement": 6 of 8 safe-improvement-lifecycle steps
were real; missing: pre-change impact simulation, automatic rollback-on-
quality-decline. `impact_simulation` is written by submit_enhancement_
request (SCAN phase, before any human decision) via app.fleet.
enhancement_impact.simulate_enhancement_impact. The other three are
written by app.fleet.enhancement_rollback's scheduled monitor loop, which
mirrors the already-real, already-automatic (no human-approval gate)
_prompt_auto_rollback_loop pattern (app/main.py) — extended to
EnhancementRequest-driven code commits via `git revert`, not just prompt
versions.

Revision ID: 046
Revises: 045
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "046"
down_revision: Union[str, None] = "045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "enhancement_requests",
        sa.Column("impact_simulation", JSONB(), nullable=True),
    )
    op.add_column(
        "enhancement_requests",
        # null=not yet due for a check; monitoring=applied, waiting out the
        # post-window; stable=checked, no real decline; rolled_back=decline
        # detected and reverted automatically; rollback_failed=decline
        # detected but git revert itself failed (needs human attention).
        sa.Column("quality_check_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "enhancement_requests",
        sa.Column("rollback_commit_sha", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "enhancement_requests",
        sa.Column("rollback_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("enhancement_requests", "rollback_at")
    op.drop_column("enhancement_requests", "rollback_commit_sha")
    op.drop_column("enhancement_requests", "quality_check_status")
    op.drop_column("enhancement_requests", "impact_simulation")

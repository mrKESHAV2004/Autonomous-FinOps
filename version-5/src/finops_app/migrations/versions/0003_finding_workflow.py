"""finding workflow: status history, snooze date, lookup by resource

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-26 13:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("findings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("snoozed_until", sa.Date(), nullable=True))
        batch_op.add_column(
            sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_index("ix_findings_org_resource", ["org_id", "resource_key"], unique=False)

    op.create_table(
        "finding_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("finding_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("from_status", sa.String(length=16), nullable=False),
        sa.Column("to_status", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("snoozed_until", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("finding_events", schema=None) as batch_op:
        batch_op.create_index(
            "ix_finding_events_org_finding", ["org_id", "finding_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("finding_events", schema=None) as batch_op:
        batch_op.drop_index("ix_finding_events_org_finding")
    op.drop_table("finding_events")
    with op.batch_alter_table("findings", schema=None) as batch_op:
        batch_op.drop_index("ix_findings_org_resource")
        batch_op.drop_column("status_changed_at")
        batch_op.drop_column("snoozed_until")

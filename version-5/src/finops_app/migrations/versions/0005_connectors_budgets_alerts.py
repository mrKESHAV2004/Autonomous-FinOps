"""connectors, budgets, and alerts (Phase 5)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-26 15:45:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cloud_connections",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("role_arn", sa.String(length=255), nullable=True),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("s3_bucket", sa.String(length=255), nullable=True),
        sa.Column("s3_prefix", sa.String(length=512), nullable=True),
        sa.Column("region", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "name", name="uq_cloud_connection_org_name"),
    )
    with op.batch_alter_table("cloud_connections", schema=None) as batch_op:
        batch_op.create_index("ix_cloud_connections_org", ["org_id"], unique=False)

    op.create_table(
        "budgets",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_value", sa.String(length=255), nullable=True),
        sa.Column("monthly_amount", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "scope_type", "scope_value", name="uq_budget_org_scope"),
    )
    with op.batch_alter_table("budgets", schema=None) as batch_op:
        batch_op.create_index("ix_budgets_org", ["org_id"], unique=False)

    op.create_table(
        "alert_configs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("channel_type", sa.String(length=32), nullable=False),
        sa.Column("destination", sa.String(length=512), nullable=False),
        sa.Column("notify_high_confidence", sa.Boolean(), nullable=False),
        sa.Column("notify_budget_exceeded", sa.Boolean(), nullable=False),
        sa.Column("notify_spend_spikes", sa.Boolean(), nullable=False),
        sa.Column("spike_threshold_percent", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("alert_configs", schema=None) as batch_op:
        batch_op.create_index("ix_alert_configs_org", ["org_id"], unique=False)

    op.create_table(
        "alert_history",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("analysis_id", sa.String(length=32), nullable=True),
        sa.Column("channel_type", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.String(length=512), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("alert_history", schema=None) as batch_op:
        batch_op.create_index(
            "ix_alert_history_org_created", ["org_id", "created_at"], unique=False
        )

    with op.batch_alter_table("datasets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("connection_id", sa.String(length=32), nullable=True))
        batch_op.create_foreign_key(
            "fk_datasets_connection_id",
            "cloud_connections",
            ["connection_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("datasets", schema=None) as batch_op:
        batch_op.drop_constraint("fk_datasets_connection_id", type_="foreignkey")
        batch_op.drop_column("connection_id")

    with op.batch_alter_table("alert_history", schema=None) as batch_op:
        batch_op.drop_index("ix_alert_history_org_created")
    op.drop_table("alert_history")

    with op.batch_alter_table("alert_configs", schema=None) as batch_op:
        batch_op.drop_index("ix_alert_configs_org")
    op.drop_table("alert_configs")

    with op.batch_alter_table("budgets", schema=None) as batch_op:
        batch_op.drop_index("ix_budgets_org")
    op.drop_table("budgets")

    with op.batch_alter_table("cloud_connections", schema=None) as batch_op:
        batch_op.drop_index("ix_cloud_connections_org")
    op.drop_table("cloud_connections")

"""model registry (Phase 7)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-26 17:50:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_versions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("algorithm", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("training_window_start", sa.String(length=10), nullable=True),
        sa.Column("training_window_end", sa.String(length=10), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_name", "version", name="uq_model_versions_name_ver"),
    )
    op.create_index(
        "ix_model_versions_name_active",
        "model_versions",
        ["model_name", "is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_model_versions_name_active", table_name="model_versions")
    op.drop_table("model_versions")

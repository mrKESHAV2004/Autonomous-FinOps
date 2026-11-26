"""accounts: password hash and last login; account events in the audit log

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-26 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("password_hash", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.alter_column("org_id", existing_type=sa.String(length=32), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM audit_log WHERE org_id IS NULL")
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.alter_column("org_id", existing_type=sa.String(length=32), nullable=False)
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("last_login_at")
        batch_op.drop_column("password_hash")

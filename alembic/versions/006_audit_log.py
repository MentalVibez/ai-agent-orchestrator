"""Add audit_log table.

Revision ID: 006_audit_log
Revises: 005_dex_foundation
Create Date: 2026-03-04
"""

import sqlalchemy as sa
from alembic import op

revision = "006_audit_log"
down_revision = "005_dex_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(64), nullable=True, index=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False, index=True),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("path", sa.String(1024), nullable=False, index=True),
        sa.Column("status_code", sa.Integer(), nullable=True, index=True),
        sa.Column("api_key_id", sa.String(64), nullable=True, index=True),
        sa.Column("api_key_role", sa.String(32), nullable=True),
        sa.Column("client_ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("request_body", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("audit_log")

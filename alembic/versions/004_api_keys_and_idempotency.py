"""Add api_keys and idempotency_records tables.

Revision ID: 004_api_keys
Revises: 003_checkpoint
Create Date: 2026-02-25

api_keys          — named, hashed API keys with RBAC roles for key rotation/revocation
idempotency_records — prevents duplicate runs from client retries
"""

import sqlalchemy as sa
from alembic import op

revision = "004_api_keys"
down_revision = "003_checkpoint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key_id", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="operator"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("idempotency_key", sa.String(256), unique=True, nullable=False, index=True),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_table("api_keys")

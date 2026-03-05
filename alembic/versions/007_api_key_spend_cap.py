"""Add per-key monthly spend cap and api_key_id on cost records.

Revision ID: 007_api_key_spend_cap
Revises: 006_audit_log
Create Date: 2026-03-04

Changes:
- api_keys.max_monthly_cost_usd (Float, nullable) — NULL = no cap
- cost_records.api_key_id (String(64), nullable, indexed) — per-key spend tracking
"""

import sqlalchemy as sa
from alembic import op

revision = "007_api_key_spend_cap"
down_revision = "006_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("max_monthly_cost_usd", sa.Float(), nullable=True))
    op.add_column(
        "cost_records",
        sa.Column("api_key_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_cost_records_api_key_id"),
        "cost_records",
        ["api_key_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_cost_records_api_key_id"), table_name="cost_records")
    op.drop_column("cost_records", "api_key_id")
    op.drop_column("api_keys", "max_monthly_cost_usd")

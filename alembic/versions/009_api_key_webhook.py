"""Add webhook_url to api_keys table.

Revision ID: 009_api_key_webhook
Revises: 008_run_ownership
Create Date: 2026-03-04
"""

import sqlalchemy as sa

from alembic import op

revision = "009_api_key_webhook"
down_revision = "008_run_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("webhook_url", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("api_keys", "webhook_url")

"""Add api_key_id column to runs for row-level security.

Revision ID: 008_run_ownership
Revises: 007_api_key_spend_cap
Create Date: 2026-03-04
"""

import sqlalchemy as sa
from alembic import op

revision = "008_run_ownership"
down_revision = "007_api_key_spend_cap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("api_key_id", sa.String(64), nullable=True))
    op.create_index("ix_runs_api_key_id", "runs", ["api_key_id"])


def downgrade() -> None:
    op.drop_index("ix_runs_api_key_id", "runs")
    op.drop_column("runs", "api_key_id")

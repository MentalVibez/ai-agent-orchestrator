"""Add checkpoint_step_index to runs; create cost_records table.

Revision ID: 003_checkpoint
Revises: 002_pending
Create Date: 2026-02-18

"""

import sqlalchemy as sa
from alembic import op

revision = "003_checkpoint"
down_revision = "002_pending"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add checkpoint column to existing runs table
    op.add_column(
        "runs",
        sa.Column("checkpoint_step_index", sa.Integer(), nullable=True, server_default="0"),
    )

    # Create cost_records table for persisted LLM cost tracking
    op.create_table(
        "cost_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(), nullable=True, index=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("agent_id", sa.String(128), nullable=True),
        sa.Column("endpoint", sa.String(256), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("cost_records")
    op.drop_column("runs", "checkpoint_step_index")

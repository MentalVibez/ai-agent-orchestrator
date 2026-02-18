"""Add pending_tool_call to runs for HITL (awaiting_approval).

Revision ID: 002_pending
Revises: 001_initial
Create Date: 2025-02-17

"""
from alembic import op
import sqlalchemy as sa


revision = "002_pending"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("pending_tool_call", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "pending_tool_call")

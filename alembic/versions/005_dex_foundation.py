"""Add DEX (Digital Employee Experience) tables.

Revision ID: 005_dex_foundation
Revises: 004_api_keys
Create Date: 2026-02-27

Tables added:
  dex_endpoints        — managed endpoint registry (fleet inventory)
  dex_metric_snapshots — point-in-time telemetry readings per endpoint
  dex_scores           — calculated composite DEX score (0-100) per endpoint
  dex_alerts           — active alerts (threshold, predictive, prometheus-sourced)
  dex_feedback         — employee pulse survey responses (eNPS source)
"""

import sqlalchemy as sa
from alembic import op

revision = "005_dex_foundation"
down_revision = "004_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dex_endpoints",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("hostname", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("owner_email", sa.String(255), nullable=True),
        sa.Column("persona", sa.String(64), nullable=True),
        sa.Column("criticality_tier", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("os_platform", sa.String(32), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "dex_metric_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("hostname", sa.String(255), nullable=False, index=True),
        sa.Column("run_id", sa.String(64), nullable=True, index=True),
        sa.Column("cpu_pct", sa.Float(), nullable=True),
        sa.Column("memory_pct", sa.Float(), nullable=True),
        sa.Column("disk_pct", sa.Float(), nullable=True),
        sa.Column("network_latency_ms", sa.Float(), nullable=True),
        sa.Column("packet_loss_pct", sa.Float(), nullable=True),
        sa.Column("services_down", sa.JSON(), nullable=True),
        sa.Column("log_error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_output", sa.JSON(), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "dex_scores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("hostname", sa.String(255), nullable=False, index=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("device_health_score", sa.Float(), nullable=True),
        sa.Column("network_score", sa.Float(), nullable=True),
        sa.Column("app_performance_score", sa.Float(), nullable=True),
        sa.Column("remediation_score", sa.Float(), nullable=True),
        sa.Column(
            "scored_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "dex_alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("hostname", sa.String(255), nullable=False, index=True),
        sa.Column("alert_name", sa.String(255), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False, server_default="warning"),
        sa.Column("alert_type", sa.String(32), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("predicted_time_to_impact", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("remediation_run_id", sa.String(64), nullable=True),
        sa.Column("acknowledged_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "dex_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("hostname", sa.String(255), nullable=True, index=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("dex_feedback")
    op.drop_table("dex_alerts")
    op.drop_table("dex_scores")
    op.drop_table("dex_metric_snapshots")
    op.drop_table("dex_endpoints")

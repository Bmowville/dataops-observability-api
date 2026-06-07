"""alert delivery audit table

Revision ID: 0002_alert_deliveries
Revises: 0001_initial
Create Date: 2026-06-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_alert_deliveries"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("pipeline_run_id", sa.Integer(), nullable=True),
        sa.Column("quality_check_id", sa.Integer(), nullable=True),
        sa.Column("receiver", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["quality_check_id"], ["quality_checks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_deliveries_event_type", "alert_deliveries", ["event_type"])
    op.create_index("ix_alert_deliveries_pipeline_run_id", "alert_deliveries", ["pipeline_run_id"])
    op.create_index(
        "ix_alert_deliveries_quality_check_id",
        "alert_deliveries",
        ["quality_check_id"],
    )
    op.create_index("ix_alert_deliveries_status", "alert_deliveries", ["status"])


def downgrade() -> None:
    op.drop_index("ix_alert_deliveries_status", table_name="alert_deliveries")
    op.drop_index("ix_alert_deliveries_quality_check_id", table_name="alert_deliveries")
    op.drop_index("ix_alert_deliveries_pipeline_run_id", table_name="alert_deliveries")
    op.drop_index("ix_alert_deliveries_event_type", table_name="alert_deliveries")
    op.drop_table("alert_deliveries")
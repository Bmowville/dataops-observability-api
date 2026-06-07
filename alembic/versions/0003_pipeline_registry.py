"""pipeline registry

Revision ID: 0003_pipeline_registry
Revises: 0002_alert_deliveries
Create Date: 2026-06-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_pipeline_registry"
down_revision: str | None = "0002_alert_deliveries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipelines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("owner", sa.String(length=120), nullable=False),
        sa.Column("source_system", sa.String(length=80), nullable=False),
        sa.Column("expected_cadence_minutes", sa.Integer(), nullable=True),
        sa.Column("stale_after_minutes", sa.Integer(), nullable=False),
        sa.Column("alert_severity", sa.String(length=20), nullable=False),
        sa.Column("runbook_url", sa.String(length=500), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pipelines_name", "pipelines", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_pipelines_name", table_name="pipelines")
    op.drop_table("pipelines")
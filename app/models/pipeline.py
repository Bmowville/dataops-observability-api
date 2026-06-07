from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    source_system: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), index=True, default="queued")
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    quality_checks: Mapped[list[QualityCheck]] = relationship(
        back_populates="pipeline_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class QualityCheck(Base):
    __tablename__ = "quality_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
        index=True,
    )
    check_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), index=True)
    severity: Mapped[str] = mapped_column(String(20))
    expected_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    observed_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    details: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    pipeline_run: Mapped[PipelineRun] = relationship(back_populates="quality_checks")


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    pipeline_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    quality_check_id: Mapped[int | None] = mapped_column(
        ForeignKey("quality_checks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    receiver: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), index=True)
    http_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
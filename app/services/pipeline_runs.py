from datetime import UTC, datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.pipeline import PipelineRun, QualityCheck
from app.schemas.pipeline import (
    MetricsSummary,
    PipelineRunCreate,
    PipelineRunStatus,
    PipelineRunUpdate,
    QualityCheckCreate,
    QualityCheckStatus,
)


def create_pipeline_run(db: Session, payload: PipelineRunCreate) -> PipelineRun:
    started_at = payload.started_at
    if payload.status == PipelineRunStatus.running and started_at is None:
        started_at = datetime.now(UTC)

    run = PipelineRun(
        name=payload.name,
        source_system=payload.source_system,
        status=payload.status.value,
        records_processed=payload.records_processed,
        started_at=started_at,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def list_pipeline_runs(
    db: Session,
    status: PipelineRunStatus | None = None,
    limit: int = 100,
) -> list[PipelineRun]:
    statement: Select[tuple[PipelineRun]] = (
        select(PipelineRun)
        .options(selectinload(PipelineRun.quality_checks))
        .order_by(PipelineRun.created_at.desc())
        .limit(limit)
    )
    if status is not None:
        statement = statement.where(PipelineRun.status == status.value)
    return list(db.scalars(statement).all())


def get_pipeline_run(db: Session, run_id: int) -> PipelineRun | None:
    statement = (
        select(PipelineRun)
        .options(selectinload(PipelineRun.quality_checks))
        .where(PipelineRun.id == run_id)
    )
    return db.scalar(statement)


def update_pipeline_run(
    db: Session,
    run: PipelineRun,
    payload: PipelineRunUpdate,
) -> PipelineRun:
    update_data = payload.model_dump(exclude_unset=True)

    if payload.status is not None:
        run.status = payload.status.value
        if payload.status == PipelineRunStatus.running and run.started_at is None:
            run.started_at = datetime.now(UTC)
        if payload.status in {PipelineRunStatus.succeeded, PipelineRunStatus.failed}:
            run.finished_at = payload.finished_at or datetime.now(UTC)

    if "records_processed" in update_data:
        run.records_processed = payload.records_processed or 0
    if "error_message" in update_data:
        run.error_message = payload.error_message
    if "started_at" in update_data and payload.started_at is not None:
        run.started_at = payload.started_at
    if "finished_at" in update_data and payload.finished_at is not None:
        run.finished_at = payload.finished_at

    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def create_quality_check(
    db: Session,
    run: PipelineRun,
    payload: QualityCheckCreate,
) -> QualityCheck:
    check = QualityCheck(
        pipeline_run_id=run.id,
        check_name=payload.check_name,
        status=payload.status.value,
        severity=payload.severity.value,
        expected_value=payload.expected_value,
        observed_value=payload.observed_value,
        details=payload.details,
    )
    db.add(check)
    db.commit()
    db.refresh(check)
    return check


def list_quality_checks(db: Session, run_id: int) -> list[QualityCheck]:
    statement = (
        select(QualityCheck)
        .where(QualityCheck.pipeline_run_id == run_id)
        .order_by(QualityCheck.created_at.desc())
    )
    return list(db.scalars(statement).all())


def get_metrics_summary(db: Session) -> MetricsSummary:
    total_runs = db.scalar(select(func.count(PipelineRun.id))) or 0
    rows = db.execute(
        select(PipelineRun.status, func.count(PipelineRun.id)).group_by(PipelineRun.status)
    )
    runs_by_status = {str(status): int(count) for status, count in rows.all()}

    failed_checks = db.scalar(
        select(func.count(QualityCheck.id)).where(
            QualityCheck.status == QualityCheckStatus.failed.value
        )
    ) or 0
    warning_checks = db.scalar(
        select(func.count(QualityCheck.id)).where(
            QualityCheck.status == QualityCheckStatus.warning.value
        )
    ) or 0

    return MetricsSummary(
        total_runs=int(total_runs),
        runs_by_status=runs_by_status,
        failed_quality_checks=int(failed_checks),
        warning_quality_checks=int(warning_checks),
    )
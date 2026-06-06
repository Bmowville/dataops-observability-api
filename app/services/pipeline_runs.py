from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.pipeline import PipelineRun, QualityCheck
from app.schemas.pipeline import (
    MetricsSummary,
    PipelineHealthRollup,
    PipelineRunCreate,
    PipelineRunStatus,
    PipelineRunTimelineEvent,
    PipelineRunUpdate,
    QualityCheckCreate,
    QualityCheckSeverity,
    QualityCheckSeverityRollup,
    QualityCheckStatus,
    StalePipelineRunMetric,
)

SEVERITY_PRIORITY = {
    QualityCheckSeverity.critical.value: 0,
    QualityCheckSeverity.high.value: 1,
    QualityCheckSeverity.medium.value: 2,
    QualityCheckSeverity.low.value: 3,
}
ACTIVE_RUN_STATUSES = {
    PipelineRunStatus.queued.value,
    PipelineRunStatus.running.value,
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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


def get_latest_pipeline_run(db: Session, name: str) -> PipelineRun | None:
    statement = (
        select(PipelineRun)
        .options(selectinload(PipelineRun.quality_checks))
        .where(PipelineRun.name == name)
        .order_by(PipelineRun.started_at.desc(), PipelineRun.created_at.desc())
        .limit(1)
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


def get_pipeline_run_timeline(run: PipelineRun) -> list[PipelineRunTimelineEvent]:
    events = [
        PipelineRunTimelineEvent(
            timestamp=run.created_at,
            event_type="run_created",
            title="Pipeline run created",
            detail=f"{run.name} from {run.source_system}",
            status=run.status,
        )
    ]

    if run.started_at is not None:
        events.append(
            PipelineRunTimelineEvent(
                timestamp=run.started_at,
                event_type="run_started",
                title="Pipeline run started",
                detail=f"Processed records at start: {run.records_processed}",
                status=run.status,
            )
        )

    for check in run.quality_checks:
        events.append(
            PipelineRunTimelineEvent(
                timestamp=check.created_at,
                event_type="quality_check",
                title=check.check_name,
                detail=check.details,
                status=check.status,
            )
        )

    if run.finished_at is not None:
        events.append(
            PipelineRunTimelineEvent(
                timestamp=run.finished_at,
                event_type="run_finished",
                title="Pipeline run finished",
                detail=run.error_message,
                status=run.status,
            )
        )

    return sorted(events, key=lambda event: event.timestamp)


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


def get_pipeline_health_rollups(db: Session) -> list[PipelineHealthRollup]:
    runs = db.scalars(
        select(PipelineRun)
        .options(selectinload(PipelineRun.quality_checks))
        .order_by(
            PipelineRun.name.asc(),
            PipelineRun.started_at.desc(),
            PipelineRun.created_at.desc(),
        )
    ).all()

    grouped_runs: dict[str, list[PipelineRun]] = {}
    for run in runs:
        grouped_runs.setdefault(run.name, []).append(run)

    rollups = []
    for name, pipeline_runs in grouped_runs.items():
        latest_run = max(
            pipeline_runs,
            key=lambda run: run.started_at or run.created_at,
        )
        checks = [check for run in pipeline_runs for check in run.quality_checks]
        rollups.append(
            PipelineHealthRollup(
                name=name,
                total_runs=len(pipeline_runs),
                failed_runs=sum(
                    1 for run in pipeline_runs if run.status == PipelineRunStatus.failed
                ),
                latest_run_id=latest_run.id,
                latest_status=PipelineRunStatus(latest_run.status),
                latest_run_at=latest_run.started_at or latest_run.created_at,
                latest_finished_at=latest_run.finished_at,
                latest_records_processed=latest_run.records_processed,
                failed_quality_checks=sum(
                    1 for check in checks if check.status == QualityCheckStatus.failed
                ),
                warning_quality_checks=sum(
                    1 for check in checks if check.status == QualityCheckStatus.warning
                ),
            )
        )

    return sorted(rollups, key=lambda rollup: rollup.name)


def get_quality_check_severity_rollups(db: Session) -> list[QualityCheckSeverityRollup]:
    rows = db.execute(
        select(
            QualityCheck.severity,
            QualityCheck.status,
            func.count(QualityCheck.id),
        ).group_by(QualityCheck.severity, QualityCheck.status)
    ).all()

    grouped: dict[str, dict[str, int]] = {}
    for severity, status, count in rows:
        grouped.setdefault(str(severity), {})[str(status)] = int(count)

    rollups = [
        QualityCheckSeverityRollup(
            severity=QualityCheckSeverity(severity),
            total_checks=sum(status_counts.values()),
            passed_checks=status_counts.get(QualityCheckStatus.passed.value, 0),
            warning_checks=status_counts.get(QualityCheckStatus.warning.value, 0),
            failed_checks=status_counts.get(QualityCheckStatus.failed.value, 0),
        )
        for severity, status_counts in grouped.items()
    ]

    return sorted(
        rollups,
        key=lambda rollup: SEVERITY_PRIORITY[rollup.severity.value],
    )


def get_stale_pipeline_run_metrics(
    db: Session,
    max_age_minutes: int = 60,
    now: datetime | None = None,
) -> list[StalePipelineRunMetric]:
    current_time = _as_utc(now or datetime.now(UTC))
    cutoff = current_time - timedelta(minutes=max_age_minutes)
    runs = db.scalars(
        select(PipelineRun)
        .where(PipelineRun.status.in_(ACTIVE_RUN_STATUSES))
        .order_by(PipelineRun.created_at.asc())
    ).all()

    stale_runs = []
    for run in runs:
        reference_time = _as_utc(run.started_at or run.created_at)
        if reference_time > cutoff:
            continue

        age_minutes = max(0, int((current_time - reference_time).total_seconds() // 60))
        stale_runs.append(
            StalePipelineRunMetric(
                id=run.id,
                name=run.name,
                source_system=run.source_system,
                status=PipelineRunStatus(run.status),
                age_minutes=age_minutes,
                started_at=run.started_at,
                created_at=run.created_at,
                updated_at=run.updated_at,
            )
        )

    return sorted(stale_runs, key=lambda run: run.age_minutes, reverse=True)

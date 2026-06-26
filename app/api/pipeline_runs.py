from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import require_ingestion_api_key
from app.db.session import get_db
from app.models.pipeline import PipelineRun
from app.schemas.pipeline import (
    MetricsSummary,
    OperationsOverview,
    PipelineHealthRollup,
    PipelineRunCreate,
    PipelineRunRead,
    PipelineRunStatus,
    PipelineRunTimelineEvent,
    PipelineRunUpdate,
    QualityCheckCreate,
    QualityCheckRead,
    QualityCheckSeverityRollup,
    StalePipelineRunMetric,
)
from app.services.pipeline_runs import (
    create_pipeline_run,
    create_quality_check,
    get_latest_pipeline_run,
    get_metrics_summary,
    get_operations_overview,
    get_pipeline_health_rollups,
    get_pipeline_run,
    get_pipeline_run_timeline,
    get_quality_check_severity_rollups,
    get_stale_pipeline_run_metrics,
    list_pipeline_runs,
    list_quality_checks,
    render_prometheus_metrics,
    update_pipeline_run,
)
from app.services.webhook_alerts import queue_pipeline_run_alert, queue_quality_check_alert

router = APIRouter(tags=["pipeline runs"])


def _get_run_or_404(db: Session, run_id: int) -> PipelineRun:
    run = get_pipeline_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline run not found")
    return run


@router.post(
    "/pipeline-runs",
    response_model=PipelineRunRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_ingestion_api_key)],
)
def create_run(
    payload: PipelineRunCreate,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PipelineRun:
    run = create_pipeline_run(db, payload)
    queue_pipeline_run_alert(background_tasks, settings, run)
    return run


@router.get("/pipeline-runs", response_model=list[PipelineRunRead])
def list_runs(
    db: Annotated[Session, Depends(get_db)],
    status_filter: Annotated[PipelineRunStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[PipelineRun]:
    return list_pipeline_runs(db, status=status_filter, limit=limit)


@router.get("/pipeline-runs/latest", response_model=PipelineRunRead)
def read_latest_run(
    name: Annotated[str, Query(min_length=3, max_length=120)],
    db: Annotated[Session, Depends(get_db)],
) -> PipelineRun:
    run = get_latest_pipeline_run(db, name)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline run not found")
    return run


@router.get("/pipeline-runs/{run_id}", response_model=PipelineRunRead)
def read_run(run_id: int, db: Annotated[Session, Depends(get_db)]) -> PipelineRun:
    return _get_run_or_404(db, run_id)


@router.get("/pipeline-runs/{run_id}/timeline", response_model=list[PipelineRunTimelineEvent])
def read_run_timeline(
    run_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> list[PipelineRunTimelineEvent]:
    run = _get_run_or_404(db, run_id)
    return get_pipeline_run_timeline(run)


@router.patch(
    "/pipeline-runs/{run_id}",
    response_model=PipelineRunRead,
    dependencies=[Depends(require_ingestion_api_key)],
)
def patch_run(
    run_id: int,
    payload: PipelineRunUpdate,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PipelineRun:
    run = _get_run_or_404(db, run_id)
    updated_run = update_pipeline_run(db, run, payload)
    if payload.status in {PipelineRunStatus.failed, PipelineRunStatus.canceled}:
        queue_pipeline_run_alert(background_tasks, settings, updated_run)
    return updated_run


@router.post(
    "/pipeline-runs/{run_id}/quality-checks",
    response_model=QualityCheckRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_ingestion_api_key)],
)
def create_check(
    run_id: int,
    payload: QualityCheckCreate,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> QualityCheckRead:
    run = _get_run_or_404(db, run_id)
    check = create_quality_check(db, run, payload)
    queue_quality_check_alert(background_tasks, settings, run, check)
    return QualityCheckRead.model_validate(check)


@router.get("/pipeline-runs/{run_id}/quality-checks", response_model=list[QualityCheckRead])
def read_checks(run_id: int, db: Annotated[Session, Depends(get_db)]) -> list[QualityCheckRead]:
    _get_run_or_404(db, run_id)
    return [QualityCheckRead.model_validate(check) for check in list_quality_checks(db, run_id)]


@router.get("/metrics/summary", response_model=MetricsSummary)
def summary(db: Annotated[Session, Depends(get_db)]) -> MetricsSummary:
    return get_metrics_summary(db)


@router.get("/metrics/operations-overview", response_model=OperationsOverview)
def operations_overview(
    db: Annotated[Session, Depends(get_db)],
    stale_after_minutes: Annotated[int, Query(ge=1, le=1440)] = 60,
) -> OperationsOverview:
    return get_operations_overview(db, stale_after_minutes=stale_after_minutes)


@router.get("/metrics/prometheus", response_class=Response)
def prometheus_metrics(
    db: Annotated[Session, Depends(get_db)],
    stale_after_minutes: Annotated[int, Query(ge=1, le=1440)] = 60,
) -> Response:
    overview = get_operations_overview(db, stale_after_minutes=stale_after_minutes)
    return Response(
        content=render_prometheus_metrics(overview),
        media_type="text/plain; version=0.0.4",
    )


@router.get("/metrics/pipelines", response_model=list[PipelineHealthRollup])
def pipeline_health(db: Annotated[Session, Depends(get_db)]) -> list[PipelineHealthRollup]:
    return get_pipeline_health_rollups(db)


@router.get("/metrics/quality-checks", response_model=list[QualityCheckSeverityRollup])
def quality_check_health(
    db: Annotated[Session, Depends(get_db)],
) -> list[QualityCheckSeverityRollup]:
    return get_quality_check_severity_rollups(db)


@router.get("/metrics/stale-pipeline-runs", response_model=list[StalePipelineRunMetric])
def stale_pipeline_runs(
    db: Annotated[Session, Depends(get_db)],
    max_age_minutes: Annotated[int, Query(ge=1, le=1440)] = 60,
) -> list[StalePipelineRunMetric]:
    return get_stale_pipeline_run_metrics(db, max_age_minutes=max_age_minutes)

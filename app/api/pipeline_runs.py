from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.pipeline import PipelineRun
from app.schemas.pipeline import (
    MetricsSummary,
    PipelineHealthRollup,
    PipelineRunCreate,
    PipelineRunRead,
    PipelineRunStatus,
    PipelineRunTimelineEvent,
    PipelineRunUpdate,
    QualityCheckCreate,
    QualityCheckRead,
)
from app.services.pipeline_runs import (
    create_pipeline_run,
    create_quality_check,
    get_latest_pipeline_run,
    get_metrics_summary,
    get_pipeline_health_rollups,
    get_pipeline_run,
    get_pipeline_run_timeline,
    list_pipeline_runs,
    list_quality_checks,
    update_pipeline_run,
)

router = APIRouter(tags=["pipeline runs"])


def _get_run_or_404(db: Session, run_id: int) -> PipelineRun:
    run = get_pipeline_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline run not found")
    return run


@router.post("/pipeline-runs", response_model=PipelineRunRead, status_code=status.HTTP_201_CREATED)
def create_run(
    payload: PipelineRunCreate,
    db: Annotated[Session, Depends(get_db)],
) -> PipelineRun:
    return create_pipeline_run(db, payload)


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


@router.patch("/pipeline-runs/{run_id}", response_model=PipelineRunRead)
def patch_run(
    run_id: int,
    payload: PipelineRunUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> PipelineRun:
    run = _get_run_or_404(db, run_id)
    return update_pipeline_run(db, run, payload)


@router.post(
    "/pipeline-runs/{run_id}/quality-checks",
    response_model=QualityCheckRead,
    status_code=status.HTTP_201_CREATED,
)
def create_check(
    run_id: int,
    payload: QualityCheckCreate,
    db: Annotated[Session, Depends(get_db)],
) -> QualityCheckRead:
    run = _get_run_or_404(db, run_id)
    return QualityCheckRead.model_validate(create_quality_check(db, run, payload))


@router.get("/pipeline-runs/{run_id}/quality-checks", response_model=list[QualityCheckRead])
def read_checks(run_id: int, db: Annotated[Session, Depends(get_db)]) -> list[QualityCheckRead]:
    _get_run_or_404(db, run_id)
    return [QualityCheckRead.model_validate(check) for check in list_quality_checks(db, run_id)]


@router.get("/metrics/summary", response_model=MetricsSummary)
def summary(db: Annotated[Session, Depends(get_db)]) -> MetricsSummary:
    return get_metrics_summary(db)


@router.get("/metrics/pipelines", response_model=list[PipelineHealthRollup])
def pipeline_health(db: Annotated[Session, Depends(get_db)]) -> list[PipelineHealthRollup]:
    return get_pipeline_health_rollups(db)

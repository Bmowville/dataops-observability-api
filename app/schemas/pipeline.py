from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PipelineRunStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    canceled = "canceled"


class QualityCheckStatus(StrEnum):
    passed = "passed"
    warning = "warning"
    failed = "failed"


class QualityCheckSeverity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class AlertDeliveryStatus(StrEnum):
    succeeded = "succeeded"
    failed = "failed"


class HealthResponse(BaseModel):
    status: str
    app_name: str
    environment: str
    database: str


class PipelineRunCreate(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    source_system: str = Field(min_length=2, max_length=80)
    status: PipelineRunStatus = PipelineRunStatus.queued
    records_processed: int = Field(default=0, ge=0)
    started_at: datetime | None = None


class PipelineRunUpdate(BaseModel):
    status: PipelineRunStatus | None = None
    records_processed: int | None = Field(default=None, ge=0)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = Field(default=None, max_length=500)


class QualityCheckCreate(BaseModel):
    check_name: str = Field(min_length=3, max_length=120)
    status: QualityCheckStatus
    severity: QualityCheckSeverity = QualityCheckSeverity.medium
    expected_value: str | None = Field(default=None, max_length=200)
    observed_value: str | None = Field(default=None, max_length=200)
    details: str | None = Field(default=None, max_length=1000)


class QualityCheckRead(BaseModel):
    id: int
    pipeline_run_id: int
    check_name: str
    status: QualityCheckStatus
    severity: QualityCheckSeverity
    expected_value: str | None
    observed_value: str | None
    details: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AlertDeliveryRead(BaseModel):
    id: int
    event_type: str
    pipeline_run_id: int | None
    quality_check_id: int | None
    receiver: str
    status: AlertDeliveryStatus
    http_status_code: int | None
    error_message: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PipelineRunTimelineEvent(BaseModel):
    timestamp: datetime
    event_type: str
    title: str
    detail: str | None = None
    status: str | None = None


class PipelineRunRead(BaseModel):
    id: int
    name: str
    source_system: str
    status: PipelineRunStatus
    records_processed: int
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    quality_checks: list[QualityCheckRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class MetricsSummary(BaseModel):
    total_runs: int
    runs_by_status: dict[str, int]
    failed_quality_checks: int
    warning_quality_checks: int


class PipelineHealthRollup(BaseModel):
    name: str
    total_runs: int
    failed_runs: int
    latest_run_id: int
    latest_status: PipelineRunStatus
    latest_run_at: datetime
    latest_finished_at: datetime | None
    latest_records_processed: int
    failed_quality_checks: int
    warning_quality_checks: int


class StalePipelineRunMetric(BaseModel):
    id: int
    name: str
    source_system: str
    status: PipelineRunStatus
    age_minutes: int
    started_at: datetime | None
    created_at: datetime
    updated_at: datetime


class QualityCheckSeverityRollup(BaseModel):
    severity: QualityCheckSeverity
    total_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int


class RecommendedAction(BaseModel):
    priority: str
    title: str
    detail: str


class OperationsOverview(BaseModel):
    generated_at: datetime
    service_status: str
    summary: MetricsSummary
    pipeline_health: list[PipelineHealthRollup]
    quality_checks: list[QualityCheckSeverityRollup]
    stale_pipeline_runs: list[StalePipelineRunMetric]
    recommended_actions: list[RecommendedAction]


class SeedSampleDataSummary(BaseModel):
    pipeline_runs_created: int
    quality_checks_created: int
    source_system: str
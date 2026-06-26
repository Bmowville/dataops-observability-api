from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.pipeline import AlertDelivery, PipelineDefinition, PipelineRun, QualityCheck
from app.schemas.pipeline import AlertDeliveryStatus, SeedSampleDataSummary

SAMPLE_SOURCE_SYSTEM = "sample_seed"
SAMPLE_ALERT_RECEIVERS = (
    "https://alerts.example.com/dataops",
    "https://backup-alerts.example.com/dataops",
)


def seed_sample_data(db: Session) -> SeedSampleDataSummary:
    sample_pipeline_names = ["orders_daily_load", "inventory_snapshot"]
    db.execute(delete(AlertDelivery).where(AlertDelivery.receiver.in_(SAMPLE_ALERT_RECEIVERS)))
    db.execute(delete(PipelineDefinition).where(PipelineDefinition.name.in_(sample_pipeline_names)))

    existing_run_ids = list(
        db.scalars(select(PipelineRun.id).where(PipelineRun.source_system == SAMPLE_SOURCE_SYSTEM))
    )
    if existing_run_ids:
        db.execute(delete(QualityCheck).where(QualityCheck.pipeline_run_id.in_(existing_run_ids)))
        db.execute(delete(PipelineRun).where(PipelineRun.id.in_(existing_run_ids)))

    now = datetime.now(UTC)
    pipelines = [
        PipelineDefinition(
            name="orders_daily_load",
            owner="Data Platform",
            source_system=SAMPLE_SOURCE_SYSTEM,
            expected_cadence_minutes=1440,
            stale_after_minutes=90,
            alert_severity="high",
            runbook_url="https://runbooks.example.com/orders-daily-load",
        ),
        PipelineDefinition(
            name="inventory_snapshot",
            owner="Inventory Ops",
            source_system=SAMPLE_SOURCE_SYSTEM,
            expected_cadence_minutes=60,
            stale_after_minutes=15,
            alert_severity="medium",
            runbook_url="https://runbooks.example.com/inventory-snapshot",
        ),
    ]
    db.add_all(pipelines)

    runs = [
        PipelineRun(
            name="orders_daily_load",
            source_system=SAMPLE_SOURCE_SYSTEM,
            status="succeeded",
            records_processed=1284,
            created_at=now - timedelta(hours=3, minutes=15),
            updated_at=now - timedelta(hours=3),
            started_at=now - timedelta(hours=3, minutes=10),
            finished_at=now - timedelta(hours=3),
        ),
        PipelineRun(
            name="orders_daily_load",
            source_system=SAMPLE_SOURCE_SYSTEM,
            status="failed",
            records_processed=932,
            created_at=now - timedelta(days=1, hours=3, minutes=20),
            updated_at=now - timedelta(days=1, hours=3, minutes=2),
            started_at=now - timedelta(days=1, hours=3, minutes=15),
            finished_at=now - timedelta(days=1, hours=3, minutes=2),
            error_message="Freshness check exceeded threshold",
        ),
        PipelineRun(
            name="inventory_snapshot",
            source_system=SAMPLE_SOURCE_SYSTEM,
            status="running",
            records_processed=421,
            created_at=now - timedelta(minutes=20),
            updated_at=now - timedelta(minutes=18),
            started_at=now - timedelta(minutes=18),
        ),
    ]
    db.add_all(runs)
    db.flush()

    checks = [
        QualityCheck(
            pipeline_run_id=runs[0].id,
            check_name="row_count_minimum",
            status="passed",
            severity="high",
            expected_value="1000+",
            observed_value="1284",
            details="Loaded row count is above the operating threshold.",
            created_at=now - timedelta(hours=3, minutes=5),
        ),
        QualityCheck(
            pipeline_run_id=runs[0].id,
            check_name="freshness_sla",
            status="passed",
            severity="medium",
            expected_value="less than 2 hours",
            observed_value="45 minutes",
            details="Source extract arrived inside the freshness target.",
            created_at=now - timedelta(hours=3, minutes=3),
        ),
        QualityCheck(
            pipeline_run_id=runs[1].id,
            check_name="freshness_sla",
            status="failed",
            severity="critical",
            expected_value="less than 2 hours",
            observed_value="4 hours",
            details="Source extract arrived outside the freshness target.",
            created_at=now - timedelta(days=1, hours=3, minutes=4),
        ),
        QualityCheck(
            pipeline_run_id=runs[2].id,
            check_name="null_rate_check",
            status="warning",
            severity="medium",
            expected_value="less than 1%",
            observed_value="1.4%",
            details="Null rate is slightly above target while the run is still in progress.",
            created_at=now - timedelta(minutes=12),
        ),
    ]
    db.add_all(checks)
    db.flush()

    alert_deliveries = [
        AlertDelivery(
            event_type="pipeline_run_failed",
            pipeline_run_id=runs[1].id,
            quality_check_id=checks[2].id,
            receiver=SAMPLE_ALERT_RECEIVERS[0],
            status=AlertDeliveryStatus.succeeded.value,
            http_status_code=202,
            created_at=now - timedelta(days=1, hours=3, minutes=1),
        ),
        AlertDelivery(
            event_type="quality_check_warning",
            pipeline_run_id=runs[2].id,
            quality_check_id=checks[3].id,
            receiver=SAMPLE_ALERT_RECEIVERS[1],
            status=AlertDeliveryStatus.failed.value,
            http_status_code=503,
            error_message="Webhook receiver returned 503 Service Unavailable",
            created_at=now - timedelta(minutes=11),
        ),
    ]
    db.add_all(alert_deliveries)
    db.commit()

    return SeedSampleDataSummary(
        pipelines_registered=len(pipelines),
        pipeline_runs_created=len(runs),
        quality_checks_created=len(checks),
        alert_deliveries_created=len(alert_deliveries),
        source_system=SAMPLE_SOURCE_SYSTEM,
    )
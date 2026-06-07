from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import BackgroundTasks

from app.core.config import Settings
from app.models.pipeline import PipelineRun, QualityCheck
from app.schemas.pipeline import PipelineRunStatus, QualityCheckStatus

WEBHOOK_SECRET_HEADER = "X-DataOps-Webhook-Secret"
WEBHOOK_USER_AGENT = "dataops-observability-api/0.1"
ACTIONABLE_RUN_STATUSES = {
    PipelineRunStatus.failed.value,
    PipelineRunStatus.canceled.value,
}
ACTIONABLE_CHECK_STATUSES = {
    QualityCheckStatus.failed.value,
    QualityCheckStatus.warning.value,
}

AlertPayload = dict[str, object]

logger = logging.getLogger(__name__)


def get_configured_alert_webhook_urls(settings: Settings) -> tuple[str, ...]:
    return tuple(
        webhook_url.strip()
        for webhook_url in settings.alert_webhook_urls.split(",")
        if webhook_url.strip()
    )


def queue_pipeline_run_alert(
    background_tasks: BackgroundTasks,
    settings: Settings,
    run: PipelineRun,
) -> None:
    if run.status not in ACTIONABLE_RUN_STATUSES:
        return

    queue_webhook_alert(
        background_tasks,
        settings,
        build_pipeline_run_alert_payload(run, settings),
    )


def queue_quality_check_alert(
    background_tasks: BackgroundTasks,
    settings: Settings,
    run: PipelineRun,
    check: QualityCheck,
) -> None:
    if check.status not in ACTIONABLE_CHECK_STATUSES:
        return

    queue_webhook_alert(
        background_tasks,
        settings,
        build_quality_check_alert_payload(run, check, settings),
    )


def queue_webhook_alert(
    background_tasks: BackgroundTasks,
    settings: Settings,
    payload: AlertPayload,
) -> None:
    webhook_urls = get_configured_alert_webhook_urls(settings)
    if not webhook_urls:
        return

    background_tasks.add_task(
        send_webhook_alerts,
        webhook_urls,
        payload,
        settings.alert_webhook_secret,
        settings.alert_webhook_timeout_seconds,
    )


def build_pipeline_run_alert_payload(run: PipelineRun, settings: Settings) -> AlertPayload:
    event_type = f"pipeline_run_{run.status}"
    severity = "critical" if run.status == PipelineRunStatus.failed.value else "warning"
    return {
        "event_type": event_type,
        "severity": severity,
        "message": f"Pipeline run {run.name} is {run.status}.",
        "occurred_at": datetime.now(UTC).isoformat(),
        "pipeline_run": serialize_pipeline_run(run),
        "links": build_alert_links(run, settings),
    }


def build_quality_check_alert_payload(
    run: PipelineRun,
    check: QualityCheck,
    settings: Settings,
) -> AlertPayload:
    event_type = f"quality_check_{check.status}"
    severity = check.severity
    return {
        "event_type": event_type,
        "severity": severity,
        "message": f"Quality check {check.check_name} is {check.status} for {run.name}.",
        "occurred_at": datetime.now(UTC).isoformat(),
        "pipeline_run": serialize_pipeline_run(run),
        "quality_check": serialize_quality_check(check),
        "links": build_alert_links(run, settings),
    }


def serialize_pipeline_run(run: PipelineRun) -> dict[str, object]:
    return {
        "id": run.id,
        "name": run.name,
        "source_system": run.source_system,
        "status": run.status,
        "records_processed": run.records_processed,
        "started_at": format_datetime(run.started_at),
        "finished_at": format_datetime(run.finished_at),
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


def serialize_quality_check(check: QualityCheck) -> dict[str, object]:
    return {
        "id": check.id,
        "pipeline_run_id": check.pipeline_run_id,
        "check_name": check.check_name,
        "status": check.status,
        "severity": check.severity,
        "expected_value": check.expected_value,
        "observed_value": check.observed_value,
        "details": check.details,
        "created_at": check.created_at.isoformat(),
    }


def build_alert_links(run: PipelineRun, settings: Settings) -> dict[str, str]:
    base_url = settings.public_base_url.rstrip("/")
    return {
        "dashboard": f"{base_url}/dashboard",
        "pipeline_run": f"{base_url}{settings.api_prefix}/pipeline-runs/{run.id}",
        "timeline": f"{base_url}{settings.api_prefix}/pipeline-runs/{run.id}/timeline",
    }


def format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def send_webhook_alerts(
    webhook_urls: tuple[str, ...],
    payload: AlertPayload,
    shared_secret: str,
    timeout_seconds: float,
) -> None:
    for webhook_url in webhook_urls:
        send_webhook_alert(webhook_url, payload, shared_secret, timeout_seconds)


def send_webhook_alert(
    webhook_url: str,
    payload: AlertPayload,
    shared_secret: str,
    timeout_seconds: float,
) -> None:
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": WEBHOOK_USER_AGENT,
    }
    if shared_secret:
        headers[WEBHOOK_SECRET_HEADER] = shared_secret

    request = Request(
        url=webhook_url,
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds):
            return
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        logger.warning("Webhook alert delivery failed for %s: %s", webhook_url, error)
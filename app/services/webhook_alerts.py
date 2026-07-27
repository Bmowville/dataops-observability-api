from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import Settings
from app.db.session import SessionLocal
from app.models.pipeline import PipelineRun, QualityCheck
from app.schemas.pipeline import AlertDeliveryStatus, PipelineRunStatus, QualityCheckStatus
from app.services.alert_deliveries import create_alert_delivery

WEBHOOK_SECRET_HEADER = "X-DataOps-Webhook-Secret"
WEBHOOK_USER_AGENT = f"dataops-observability-api/{__version__}"
ACTIONABLE_RUN_STATUSES = {
    PipelineRunStatus.failed.value,
    PipelineRunStatus.canceled.value,
}
ACTIONABLE_CHECK_STATUSES = {
    QualityCheckStatus.failed.value,
    QualityCheckStatus.warning.value,
}

AlertPayload = dict[str, object]
SessionFactory = Callable[[], Session]

logger = logging.getLogger(__name__)

REDACTED_WEBHOOK_RECEIVER = "<redacted-webhook-receiver>"


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
        pipeline_run_id=run.id,
        quality_check_id=None,
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
        pipeline_run_id=run.id,
        quality_check_id=check.id,
    )


def queue_webhook_alert(
    background_tasks: BackgroundTasks,
    settings: Settings,
    payload: AlertPayload,
    *,
    pipeline_run_id: int | None,
    quality_check_id: int | None,
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
        pipeline_run_id,
        quality_check_id,
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
    pipeline_run_id: int | None,
    quality_check_id: int | None,
    session_factory: SessionFactory = SessionLocal,
) -> None:
    event_type = str(payload.get("event_type", "alert"))
    with session_factory() as db:
        for webhook_url in webhook_urls:
            delivery_status, http_status_code, error_message = send_webhook_alert(
                webhook_url,
                payload,
                shared_secret,
                timeout_seconds,
            )
            create_alert_delivery(
                db,
                event_type=event_type,
                pipeline_run_id=pipeline_run_id,
                quality_check_id=quality_check_id,
                receiver=sanitize_receiver(webhook_url),
                status=delivery_status,
                http_status_code=http_status_code,
                error_message=error_message,
            )


def send_webhook_alert(
    webhook_url: str,
    payload: AlertPayload,
    shared_secret: str,
    timeout_seconds: float,
) -> tuple[AlertDeliveryStatus, int | None, str | None]:
    receiver = sanitize_receiver(webhook_url)
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
        with urlopen(request, timeout=timeout_seconds) as response:
            return AlertDeliveryStatus.succeeded, response.getcode(), None
    except HTTPError as error:
        logger.warning(
            "Webhook alert delivery failed for %s with HTTP status %s",
            receiver,
            error.code,
        )
        return AlertDeliveryStatus.failed, error.code, safe_delivery_error(error)
    except (URLError, TimeoutError, OSError) as error:
        logger.warning(
            "Webhook alert delivery failed for %s (%s)",
            receiver,
            type(error).__name__,
        )
        return AlertDeliveryStatus.failed, None, safe_delivery_error(error)


def sanitize_receiver(webhook_url: str) -> str:
    """Return only a webhook origin, never credentials or request-target secrets."""
    try:
        parsed = urlsplit(webhook_url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return REDACTED_WEBHOOK_RECEIVER

    if not parsed.scheme or hostname is None:
        return REDACTED_WEBHOOK_RECEIVER

    if ":" in hostname:
        hostname = f"[{hostname}]"
    authority = hostname if port is None else f"{hostname}:{port}"
    return f"{parsed.scheme.casefold()}://{authority}"[:500]


def safe_delivery_error(error: BaseException) -> str:
    """Keep persisted diagnostics useful without retaining provider URLs or secrets."""
    if isinstance(error, HTTPError):
        return f"Webhook returned HTTP {error.code}"
    return f"{type(error).__name__}: webhook delivery failed"

from typing import Any

from fastapi.testclient import TestClient

import app.services.webhook_alerts as webhook_alerts
from app.core.config import Settings, get_settings
from app.main import app


def override_alert_settings(**values: Any) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(**values)


def create_running_run(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/v1/pipeline-runs",
        json={
            "name": "daily_orders_load",
            "source_system": "warehouse",
            "status": "running",
            "records_processed": 0,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_failed_pipeline_run_sends_webhook_alert(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    deliveries: list[
        tuple[tuple[str, ...], dict[str, object], str, float, int | None, int | None]
    ] = []

    def fake_send_webhook_alerts(
        webhook_urls: tuple[str, ...],
        payload: dict[str, object],
        shared_secret: str,
        timeout_seconds: float,
        pipeline_run_id: int | None,
        quality_check_id: int | None,
    ) -> None:
        deliveries.append(
            (
                webhook_urls,
                payload,
                shared_secret,
                timeout_seconds,
                pipeline_run_id,
                quality_check_id,
            )
        )

    monkeypatch.setattr(webhook_alerts, "send_webhook_alerts", fake_send_webhook_alerts)
    override_alert_settings(
        alert_webhook_urls="https://alerts.example/dataops, https://backup.example/dataops",
        alert_webhook_secret="local-secret",
        alert_webhook_timeout_seconds=2.5,
        public_base_url="https://dataops.example",
    )
    created = create_running_run(client)

    response = client.patch(
        f"/api/v1/pipeline-runs/{created['id']}",
        json={"status": "failed", "error_message": "warehouse load failed"},
    )

    assert response.status_code == 200
    assert len(deliveries) == 1
    webhook_urls, payload, shared_secret, timeout_seconds, pipeline_run_id, quality_check_id = (
        deliveries[0]
    )
    assert webhook_urls == ("https://alerts.example/dataops", "https://backup.example/dataops")
    assert shared_secret == "local-secret"
    assert timeout_seconds == 2.5
    assert pipeline_run_id == created["id"]
    assert quality_check_id is None
    assert payload["event_type"] == "pipeline_run_failed"
    assert payload["severity"] == "critical"
    assert payload["message"] == "Pipeline run daily_orders_load is failed."
    assert payload["pipeline_run"] == {
        **payload["pipeline_run"],
        "id": created["id"],
        "name": "daily_orders_load",
        "status": "failed",
        "error_message": "warehouse load failed",
    }
    assert payload["links"] == {
        "dashboard": "https://dataops.example/dashboard",
        "pipeline_run": f"https://dataops.example/api/v1/pipeline-runs/{created['id']}",
        "timeline": f"https://dataops.example/api/v1/pipeline-runs/{created['id']}/timeline",
    }


def test_warning_quality_check_sends_webhook_alert(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    deliveries: list[dict[str, object]] = []

    def fake_send_webhook_alerts(
        webhook_urls: tuple[str, ...],
        payload: dict[str, object],
        shared_secret: str,
        timeout_seconds: float,
        pipeline_run_id: int | None,
        quality_check_id: int | None,
    ) -> None:
        deliveries.append(payload)

    monkeypatch.setattr(webhook_alerts, "send_webhook_alerts", fake_send_webhook_alerts)
    override_alert_settings(alert_webhook_urls="https://alerts.example/dataops")
    created = create_running_run(client)

    response = client.post(
        f"/api/v1/pipeline-runs/{created['id']}/quality-checks",
        json={
            "check_name": "freshness_sla",
            "status": "warning",
            "severity": "medium",
            "expected_value": "less than 2 hours",
            "observed_value": "95 minutes",
        },
    )

    assert response.status_code == 201
    assert len(deliveries) == 1
    payload = deliveries[0]
    assert payload["event_type"] == "quality_check_warning"
    assert payload["severity"] == "medium"
    assert payload["message"] == "Quality check freshness_sla is warning for daily_orders_load."
    assert payload["quality_check"] == {
        **payload["quality_check"],
        "check_name": "freshness_sla",
        "status": "warning",
        "severity": "medium",
        "observed_value": "95 minutes",
    }


def test_non_actionable_events_do_not_send_webhook_alert(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    deliveries: list[dict[str, object]] = []

    def fake_send_webhook_alerts(
        webhook_urls: tuple[str, ...],
        payload: dict[str, object],
        shared_secret: str,
        timeout_seconds: float,
        pipeline_run_id: int | None,
        quality_check_id: int | None,
    ) -> None:
        deliveries.append(payload)

    monkeypatch.setattr(webhook_alerts, "send_webhook_alerts", fake_send_webhook_alerts)
    override_alert_settings(alert_webhook_urls="https://alerts.example/dataops")
    created = create_running_run(client)

    patch_response = client.patch(
        f"/api/v1/pipeline-runs/{created['id']}",
        json={"status": "succeeded", "records_processed": 1284},
    )
    check_response = client.post(
        f"/api/v1/pipeline-runs/{created['id']}/quality-checks",
        json={
            "check_name": "row_count_minimum",
            "status": "passed",
            "severity": "high",
        },
    )

    assert patch_response.status_code == 200
    assert check_response.status_code == 201
    assert deliveries == []


def test_failed_pipeline_run_without_configured_webhooks_does_not_deliver(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    def fail_if_called(
        webhook_urls: tuple[str, ...],
        payload: dict[str, object],
        shared_secret: str,
        timeout_seconds: float,
        pipeline_run_id: int | None,
        quality_check_id: int | None,
    ) -> None:
        raise AssertionError("No delivery should be queued without webhook URLs")

    monkeypatch.setattr(webhook_alerts, "send_webhook_alerts", fail_if_called)
    created = create_running_run(client)

    response = client.patch(
        f"/api/v1/pipeline-runs/{created['id']}",
        json={"status": "failed", "error_message": "warehouse load failed"},
    )

    assert response.status_code == 200
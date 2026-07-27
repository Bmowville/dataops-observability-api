from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import app.services.webhook_alerts as webhook_alerts
from app.models.pipeline import AlertDelivery
from app.schemas.pipeline import AlertDeliveryStatus
from app.services.alert_deliveries import create_alert_delivery


def test_send_webhook_alerts_records_each_delivery_attempt(
    db_session: Session,
    monkeypatch: Any,
) -> None:
    testing_session_local = sessionmaker(
        bind=db_session.get_bind(),
        autocommit=False,
        autoflush=False,
    )
    outcomes = {
        "https://alerts.example/dataops?token=secret": (
            AlertDeliveryStatus.succeeded,
            202,
            None,
        ),
        "https://user:secret@backup.example/hooks/dataops?token=secret": (
            AlertDeliveryStatus.failed,
            503,
            "Service Unavailable",
        ),
    }

    def fake_send_webhook_alert(
        webhook_url: str,
        payload: dict[str, object],
        shared_secret: str,
        timeout_seconds: float,
    ) -> tuple[AlertDeliveryStatus, int | None, str | None]:
        return outcomes[webhook_url]

    monkeypatch.setattr(webhook_alerts, "send_webhook_alert", fake_send_webhook_alert)

    webhook_alerts.send_webhook_alerts(
        tuple(outcomes),
        {"event_type": "pipeline_run_failed"},
        "local-secret",
        2.0,
        pipeline_run_id=None,
        quality_check_id=None,
        session_factory=testing_session_local,
    )

    deliveries = db_session.scalars(select(AlertDelivery).order_by(AlertDelivery.id)).all()
    assert len(deliveries) == 2
    assert deliveries[0].event_type == "pipeline_run_failed"
    assert deliveries[0].receiver == "https://alerts.example"
    assert deliveries[0].status == "succeeded"
    assert deliveries[0].http_status_code == 202
    assert deliveries[0].error_message is None
    assert deliveries[1].receiver == "https://backup.example"
    assert deliveries[1].status == "failed"
    assert deliveries[1].http_status_code == 503
    assert deliveries[1].error_message == "Service Unavailable"


def test_alert_delivery_endpoints_return_latest_and_filter(
    client: TestClient,
    db_session: Session,
) -> None:
    create_alert_delivery(
        db_session,
        event_type="pipeline_run_failed",
        pipeline_run_id=None,
        quality_check_id=None,
        receiver="https://alerts.example/dataops",
        status=AlertDeliveryStatus.failed,
        http_status_code=500,
        error_message="Internal Server Error",
    )
    latest = create_alert_delivery(
        db_session,
        event_type="quality_check_warning",
        pipeline_run_id=None,
        quality_check_id=None,
        receiver="https://backup.example/dataops",
        status=AlertDeliveryStatus.succeeded,
        http_status_code=204,
    )

    failed_response = client.get("/api/v1/alerts/deliveries?status=failed")
    latest_response = client.get("/api/v1/alerts/deliveries/latest")

    assert failed_response.status_code == 200
    assert [delivery["status"] for delivery in failed_response.json()] == ["failed"]
    assert failed_response.json()[0]["receiver"] == "https://alerts.example/dataops"
    assert latest_response.status_code == 200
    latest_json = latest_response.json()
    assert latest_json["id"] == latest.id
    assert latest_json["event_type"] == "quality_check_warning"
    assert latest_json["receiver"] == "https://backup.example/dataops"
    assert latest_json["status"] == "succeeded"
    assert latest_json["http_status_code"] == 204
    assert latest_json["error_message"] is None


def test_latest_alert_delivery_returns_404_when_empty(client: TestClient) -> None:
    response = client.get("/api/v1/alerts/deliveries/latest")

    assert response.status_code == 404
    assert response.json() == {"detail": "Alert delivery not found"}

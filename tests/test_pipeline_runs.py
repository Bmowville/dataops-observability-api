from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.pipeline import PipelineRun, QualityCheck
from app.services.sample_data import seed_sample_data


def create_run(client: TestClient, name: str = "daily_orders_load") -> dict[str, object]:
    response = client.post(
        "/api/v1/pipeline-runs",
        json={
            "name": name,
            "source_system": "warehouse",
            "status": "running",
            "records_processed": 0,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_create_and_read_pipeline_run(client: TestClient) -> None:
    created = create_run(client)

    response = client.get(f"/api/v1/pipeline-runs/{created['id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "daily_orders_load"
    assert payload["source_system"] == "warehouse"
    assert payload["status"] == "running"
    assert payload["quality_checks"] == []


def test_list_pipeline_runs_can_filter_by_status(client: TestClient) -> None:
    create_run(client, name="daily_orders_load")
    second = create_run(client, name="daily_inventory_load")
    client.patch(
        f"/api/v1/pipeline-runs/{second['id']}",
        json={"status": "failed", "error_message": "source file missing"},
    )

    response = client.get("/api/v1/pipeline-runs?status=failed")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["name"] == "daily_inventory_load"


def test_update_pipeline_run_sets_finished_at_for_terminal_status(client: TestClient) -> None:
    created = create_run(client)

    response = client.patch(
        f"/api/v1/pipeline-runs/{created['id']}",
        json={"status": "succeeded", "records_processed": 1284},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "succeeded"
    assert payload["records_processed"] == 1284
    assert payload["finished_at"] is not None


def test_quality_checks_attach_to_pipeline_run(client: TestClient) -> None:
    created = create_run(client)

    response = client.post(
        f"/api/v1/pipeline-runs/{created['id']}/quality-checks",
        json={
            "check_name": "row_count_minimum",
            "status": "passed",
            "severity": "high",
            "expected_value": "1000+",
            "observed_value": "1284",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["pipeline_run_id"] == created["id"]
    assert payload["check_name"] == "row_count_minimum"

    checks_response = client.get(f"/api/v1/pipeline-runs/{created['id']}/quality-checks")
    assert checks_response.status_code == 200
    assert len(checks_response.json()) == 1


def test_metrics_summary_counts_runs_and_checks(client: TestClient) -> None:
    created = create_run(client)
    client.post(
        f"/api/v1/pipeline-runs/{created['id']}/quality-checks",
        json={
            "check_name": "freshness_sla",
            "status": "failed",
            "severity": "critical",
            "expected_value": "less than 2 hours",
            "observed_value": "4 hours",
        },
    )

    response = client.get("/api/v1/metrics/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_runs"] == 1
    assert payload["runs_by_status"] == {"running": 1}
    assert payload["failed_quality_checks"] == 1
    assert payload["warning_quality_checks"] == 0


def test_latest_pipeline_run_returns_most_recent_run_for_name(
    client: TestClient,
    db_session: Session,
) -> None:
    seed_sample_data(db_session)

    response = client.get("/api/v1/pipeline-runs/latest?name=orders_daily_load")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "orders_daily_load"
    assert payload["status"] == "succeeded"
    assert payload["records_processed"] == 1284
    assert len(payload["quality_checks"]) == 2


def test_latest_pipeline_run_returns_404_for_unknown_name(client: TestClient) -> None:
    response = client.get("/api/v1/pipeline-runs/latest?name=unknown_pipeline")

    assert response.status_code == 404
    assert response.json()["detail"] == "Pipeline run not found"


def test_pipeline_run_timeline_returns_ordered_events(
    client: TestClient,
    db_session: Session,
) -> None:
    seed_sample_data(db_session)
    latest = client.get("/api/v1/pipeline-runs/latest?name=orders_daily_load").json()

    response = client.get(f"/api/v1/pipeline-runs/{latest['id']}/timeline")

    assert response.status_code == 200
    payload = response.json()
    assert [event["event_type"] for event in payload] == [
        "run_created",
        "run_started",
        "quality_check",
        "quality_check",
        "run_finished",
    ]
    assert payload[-1]["status"] == "succeeded"


def test_seed_sample_data_replaces_prior_sample_records(db_session: Session) -> None:
    first = seed_sample_data(db_session)
    second = seed_sample_data(db_session)

    run_count = db_session.scalar(select(func.count(PipelineRun.id)))
    check_count = db_session.scalar(select(func.count(QualityCheck.id)))

    assert first.pipeline_runs_created == 3
    assert first.quality_checks_created == 4
    assert second.pipeline_runs_created == 3
    assert second.quality_checks_created == 4
    assert run_count == 3
    assert check_count == 4
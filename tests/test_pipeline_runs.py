from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.main import app
from app.models.pipeline import PipelineDefinition, PipelineRun, QualityCheck
from app.services.sample_data import seed_sample_data

INGESTION_API_KEY_HEADER = "X-DataOps-API-Key"


def require_test_ingestion_keys(*api_keys: str) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        ingestion_api_keys=",".join(api_keys)
    )


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


def test_configured_ingestion_api_key_is_required_for_run_creation(
    client: TestClient,
) -> None:
    require_test_ingestion_keys("dev-key", "rotated-key")
    payload = {
        "name": "daily_orders_load",
        "source_system": "warehouse",
        "status": "running",
        "records_processed": 0,
    }

    missing_key = client.post("/api/v1/pipeline-runs", json=payload)
    invalid_key = client.post(
        "/api/v1/pipeline-runs",
        json=payload,
        headers={INGESTION_API_KEY_HEADER: "wrong-key"},
    )
    valid_key = client.post(
        "/api/v1/pipeline-runs",
        json=payload,
        headers={INGESTION_API_KEY_HEADER: "rotated-key"},
    )

    assert missing_key.status_code == 401
    assert missing_key.json()["detail"] == "Invalid or missing ingestion API key"
    assert invalid_key.status_code == 401
    assert valid_key.status_code == 201
    assert valid_key.json()["name"] == "daily_orders_load"


def test_configured_ingestion_api_key_is_required_for_mutations(
    client: TestClient,
) -> None:
    require_test_ingestion_keys("dev-key")
    created = client.post(
        "/api/v1/pipeline-runs",
        json={
            "name": "daily_orders_load",
            "source_system": "warehouse",
            "status": "running",
            "records_processed": 0,
        },
        headers={INGESTION_API_KEY_HEADER: "dev-key"},
    ).json()

    missing_patch_key = client.patch(
        f"/api/v1/pipeline-runs/{created['id']}",
        json={"status": "succeeded", "records_processed": 1284},
    )
    missing_check_key = client.post(
        f"/api/v1/pipeline-runs/{created['id']}/quality-checks",
        json={
            "check_name": "row_count_minimum",
            "status": "passed",
            "severity": "high",
        },
    )
    valid_patch_key = client.patch(
        f"/api/v1/pipeline-runs/{created['id']}",
        json={"status": "succeeded", "records_processed": 1284},
        headers={INGESTION_API_KEY_HEADER: "dev-key"},
    )
    valid_check_key = client.post(
        f"/api/v1/pipeline-runs/{created['id']}/quality-checks",
        json={
            "check_name": "row_count_minimum",
            "status": "passed",
            "severity": "high",
        },
        headers={INGESTION_API_KEY_HEADER: "dev-key"},
    )

    assert missing_patch_key.status_code == 401
    assert missing_check_key.status_code == 401
    assert valid_patch_key.status_code == 200
    assert valid_check_key.status_code == 201


def test_read_endpoints_stay_open_when_ingestion_api_key_is_configured(
    client: TestClient,
) -> None:
    require_test_ingestion_keys("dev-key")
    created = client.post(
        "/api/v1/pipeline-runs",
        json={
            "name": "daily_orders_load",
            "source_system": "warehouse",
            "status": "running",
            "records_processed": 0,
        },
        headers={INGESTION_API_KEY_HEADER: "dev-key"},
    ).json()

    run_response = client.get(f"/api/v1/pipeline-runs/{created['id']}")
    metrics_response = client.get("/api/v1/metrics/summary")

    assert run_response.status_code == 200
    assert metrics_response.status_code == 200


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


def test_operations_overview_returns_operator_snapshot(
    client: TestClient,
    db_session: Session,
) -> None:
    seed_sample_data(db_session)

    response = client.get("/api/v1/metrics/operations-overview?stale_after_minutes=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service_status"] == "attention_required"
    assert payload["summary"]["total_runs"] == 3
    assert [rollup["name"] for rollup in payload["pipeline_health"]] == [
        "inventory_snapshot",
        "orders_daily_load",
    ]
    assert payload["quality_checks"][0]["severity"] == "critical"
    assert [run["name"] for run in payload["stale_pipeline_runs"]] == ["inventory_snapshot"]
    assert [action["priority"] for action in payload["recommended_actions"]] == [
        "critical",
        "high",
        "medium",
    ]


def test_pipeline_health_rollups_group_runs_by_pipeline_name(
    client: TestClient,
    db_session: Session,
) -> None:
    seed_sample_data(db_session)

    response = client.get("/api/v1/metrics/pipelines")

    assert response.status_code == 200
    payload = response.json()
    assert [rollup["name"] for rollup in payload] == ["inventory_snapshot", "orders_daily_load"]

    inventory = payload[0]
    assert inventory["total_runs"] == 1
    assert inventory["owner"] == "Inventory Ops"
    assert inventory["stale_after_minutes"] == 15
    assert inventory["runbook_url"] == "https://runbooks.example.com/inventory-snapshot"
    assert inventory["failed_runs"] == 0
    assert inventory["latest_status"] == "running"
    assert inventory["warning_quality_checks"] == 1

    orders = payload[1]
    assert orders["total_runs"] == 2
    assert orders["owner"] == "Data Platform"
    assert orders["stale_after_minutes"] == 90
    assert orders["failed_runs"] == 1
    assert orders["latest_status"] == "succeeded"
    assert orders["latest_records_processed"] == 1284
    assert orders["failed_quality_checks"] == 1


def test_pipeline_health_rollups_return_empty_list_without_runs(client: TestClient) -> None:
    response = client.get("/api/v1/metrics/pipelines")

    assert response.status_code == 200
    assert response.json() == []


def test_quality_check_severity_rollups_count_statuses_by_severity(
    client: TestClient,
    db_session: Session,
) -> None:
    seed_sample_data(db_session)

    response = client.get("/api/v1/metrics/quality-checks")

    assert response.status_code == 200
    assert response.json() == [
        {
            "severity": "critical",
            "total_checks": 1,
            "passed_checks": 0,
            "warning_checks": 0,
            "failed_checks": 1,
        },
        {
            "severity": "high",
            "total_checks": 1,
            "passed_checks": 1,
            "warning_checks": 0,
            "failed_checks": 0,
        },
        {
            "severity": "medium",
            "total_checks": 2,
            "passed_checks": 1,
            "warning_checks": 1,
            "failed_checks": 0,
        },
    ]


def test_quality_check_severity_rollups_return_empty_list_without_checks(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/metrics/quality-checks")

    assert response.status_code == 200
    assert response.json() == []


def test_stale_pipeline_run_metrics_return_old_active_runs(
    client: TestClient,
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    db_session.add_all(
        [
            PipelineRun(
                name="orders_daily_load",
                source_system="warehouse",
                status="running",
                records_processed=800,
                started_at=now - timedelta(hours=2),
                created_at=now - timedelta(hours=2, minutes=5),
                updated_at=now - timedelta(hours=2),
            ),
            PipelineRun(
                name="inventory_snapshot",
                source_system="warehouse",
                status="queued",
                records_processed=0,
                created_at=now - timedelta(minutes=90),
                updated_at=now - timedelta(minutes=90),
            ),
            PipelineRun(
                name="recent_active_run",
                source_system="warehouse",
                status="running",
                records_processed=120,
                started_at=now - timedelta(minutes=20),
                created_at=now - timedelta(minutes=25),
                updated_at=now - timedelta(minutes=20),
            ),
            PipelineRun(
                name="completed_old_run",
                source_system="warehouse",
                status="succeeded",
                records_processed=1500,
                started_at=now - timedelta(hours=3),
                finished_at=now - timedelta(hours=2, minutes=45),
                created_at=now - timedelta(hours=3, minutes=5),
                updated_at=now - timedelta(hours=2, minutes=45),
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/metrics/stale-pipeline-runs?max_age_minutes=60")

    assert response.status_code == 200
    payload = response.json()
    assert [run["name"] for run in payload] == ["orders_daily_load", "inventory_snapshot"]
    assert payload[0]["status"] == "running"
    assert payload[0]["age_minutes"] >= 119
    assert payload[1]["status"] == "queued"
    assert payload[1]["age_minutes"] >= 89


def test_registered_pipeline_stale_threshold_overrides_default(
    client: TestClient,
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    db_session.add_all(
        [
            PipelineDefinition(
                name="fast_pipeline",
                owner="Data Platform",
                source_system="warehouse",
                expected_cadence_minutes=30,
                stale_after_minutes=15,
                alert_severity="high",
                runbook_url="https://runbooks.example.com/fast-pipeline",
            ),
            PipelineDefinition(
                name="slow_pipeline",
                owner="Finance Analytics",
                source_system="warehouse",
                expected_cadence_minutes=240,
                stale_after_minutes=60,
                alert_severity="medium",
            ),
            PipelineDefinition(
                name="paused_pipeline",
                owner="Data Platform",
                source_system="warehouse",
                expected_cadence_minutes=30,
                stale_after_minutes=5,
                alert_severity="low",
                is_enabled=False,
            ),
            PipelineRun(
                name="fast_pipeline",
                source_system="warehouse",
                status="running",
                records_processed=120,
                started_at=now - timedelta(minutes=20),
                created_at=now - timedelta(minutes=20),
                updated_at=now - timedelta(minutes=20),
            ),
            PipelineRun(
                name="slow_pipeline",
                source_system="warehouse",
                status="running",
                records_processed=120,
                started_at=now - timedelta(minutes=20),
                created_at=now - timedelta(minutes=20),
                updated_at=now - timedelta(minutes=20),
            ),
            PipelineRun(
                name="paused_pipeline",
                source_system="warehouse",
                status="running",
                records_processed=120,
                started_at=now - timedelta(hours=2),
                created_at=now - timedelta(hours=2),
                updated_at=now - timedelta(hours=2),
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/metrics/stale-pipeline-runs?max_age_minutes=10")

    assert response.status_code == 200
    payload = response.json()
    assert [run["name"] for run in payload] == ["fast_pipeline"]
    assert payload[0]["owner"] == "Data Platform"
    assert payload[0]["stale_after_minutes"] == 15
    assert payload[0]["runbook_url"] == "https://runbooks.example.com/fast-pipeline"


def test_stale_pipeline_run_metrics_return_empty_list_without_old_active_runs(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/metrics/stale-pipeline-runs?max_age_minutes=30")

    assert response.status_code == 200
    assert response.json() == []


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
    pipeline_count = db_session.scalar(select(func.count(PipelineDefinition.id)))

    assert first.pipelines_registered == 2
    assert first.pipeline_runs_created == 3
    assert first.quality_checks_created == 4
    assert second.pipelines_registered == 2
    assert second.pipeline_runs_created == 3
    assert second.quality_checks_created == 4
    assert pipeline_count == 2
    assert run_count == 3
    assert check_count == 4
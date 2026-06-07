from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app

INGESTION_API_KEY_HEADER = "X-DataOps-API-Key"


def require_test_ingestion_keys(*api_keys: str) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        ingestion_api_keys=",".join(api_keys)
    )


def pipeline_payload(name: str = "orders_daily_load") -> dict[str, object]:
    return {
        "name": name,
        "owner": "Data Platform",
        "source_system": "warehouse",
        "expected_cadence_minutes": 1440,
        "stale_after_minutes": 90,
        "alert_severity": "high",
        "runbook_url": "https://runbooks.example.com/orders-daily-load",
        "is_enabled": True,
    }


def test_pipeline_registry_create_read_list_and_update(client: TestClient) -> None:
    create_response = client.post("/api/v1/pipelines", json=pipeline_payload())
    duplicate_response = client.post("/api/v1/pipelines", json=pipeline_payload())
    list_response = client.get("/api/v1/pipelines?enabled=true")
    patch_response = client.patch(
        "/api/v1/pipelines/orders_daily_load",
        json={
            "owner": "Analytics Platform",
            "stale_after_minutes": 120,
            "runbook_url": None,
            "is_enabled": False,
        },
    )
    read_response = client.get("/api/v1/pipelines/orders_daily_load")

    assert create_response.status_code == 201
    assert create_response.json()["owner"] == "Data Platform"
    assert duplicate_response.status_code == 409
    assert list_response.status_code == 200
    assert [pipeline["name"] for pipeline in list_response.json()] == ["orders_daily_load"]
    assert patch_response.status_code == 200
    assert patch_response.json()["owner"] == "Analytics Platform"
    assert patch_response.json()["stale_after_minutes"] == 120
    assert patch_response.json()["runbook_url"] is None
    assert patch_response.json()["is_enabled"] is False
    assert read_response.status_code == 200
    assert read_response.json()["is_enabled"] is False


def test_pipeline_registry_mutations_use_ingestion_api_key(client: TestClient) -> None:
    require_test_ingestion_keys("dev-key")

    missing_key = client.post("/api/v1/pipelines", json=pipeline_payload())
    valid_key = client.post(
        "/api/v1/pipelines",
        json=pipeline_payload(),
        headers={INGESTION_API_KEY_HEADER: "dev-key"},
    )
    missing_patch_key = client.patch(
        "/api/v1/pipelines/orders_daily_load",
        json={"owner": "Analytics Platform"},
    )
    valid_patch_key = client.patch(
        "/api/v1/pipelines/orders_daily_load",
        json={"owner": "Analytics Platform"},
        headers={INGESTION_API_KEY_HEADER: "dev-key"},
    )

    assert missing_key.status_code == 401
    assert valid_key.status_code == 201
    assert missing_patch_key.status_code == 401
    assert valid_patch_key.status_code == 200
    assert valid_patch_key.json()["owner"] == "Analytics Platform"
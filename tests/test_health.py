from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


def test_live_returns_process_status_without_database(client: TestClient) -> None:
    def fail_if_database_is_requested() -> None:
        raise AssertionError("The liveness endpoint must not request a database session")

    app.dependency_overrides[get_db] = fail_if_database_is_requested

    response = client.get("/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app_name": "DataOps Observability API",
        "environment": "local",
    }


def test_health_returns_service_status(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "ok"
    assert payload["app_name"] == "DataOps Observability API"

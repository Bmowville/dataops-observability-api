from fastapi.testclient import TestClient


def test_root_redirects_to_dashboard(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/dashboard"


def test_dashboard_returns_html(client: TestClient) -> None:
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Operations Dashboard" in response.text


def test_dashboard_assets_are_served(client: TestClient) -> None:
    script_response = client.get("/static/dashboard.js")
    style_response = client.get("/static/dashboard.css")

    assert script_response.status_code == 200
    assert style_response.status_code == 200
    assert "OVERVIEW_URL" in script_response.text
    assert "metric-grid" in style_response.text
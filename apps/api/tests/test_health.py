"""The walking skeleton's proof: the path from Postgres to an HTTP response holds."""


def test_health_reports_ok_when_the_database_answers(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "up"}


def test_health_reports_degraded_when_the_database_cannot_be_reached(client_without_database):
    response = client_without_database.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "down"}


def test_openapi_document_describes_the_health_endpoint(client):
    response = client.get("/api/openapi.json")

    assert response.status_code == 200
    assert "/api/health" in response.json()["paths"]


def test_documentation_page_is_served(client):
    response = client.get("/api/docs")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

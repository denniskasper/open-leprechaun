"""The instance identifies itself: which environment it is, which build it runs."""

import re

from open_leprechaun.settings import Environment


def test_meta_in_development_reports_the_commit_hash(make_client):
    client = make_client(Environment.development)

    response = client.get("/api/meta")

    assert response.status_code == 200
    body = response.json()
    assert body["environment"] == "development"
    # A short git hash: hex, at least git's default seven characters.
    assert re.fullmatch(r"[0-9a-f]{7,}", body["version"])


def test_meta_in_production_reports_the_release_version(make_client):
    client = make_client(Environment.production, release_version="2026.08.1")

    response = client.get("/api/meta")

    assert response.status_code == 200
    assert response.json() == {"environment": "production", "version": "2026.08.1"}


def test_openapi_document_describes_the_meta_endpoint(client):
    response = client.get("/api/openapi.json")

    assert response.status_code == 200
    assert "/api/meta" in response.json()["paths"]

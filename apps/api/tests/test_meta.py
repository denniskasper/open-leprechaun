"""The instance identifies itself: which environment it is, which build it runs."""

import re
import socket

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
    assert response.json() == {"environment": "production", "version": "2026.08.1", "host": None}


def test_meta_in_development_names_the_machine_it_runs_on(make_client):
    """Several boxes run a dev server; the badge says which one this is."""
    client = make_client(Environment.development)

    assert client.get("/api/meta").json()["host"] == socket.gethostname()


def test_meta_in_production_never_names_its_machine(make_client):
    """The endpoint is public, and a production host name is nobody's business."""
    client = make_client(Environment.production, release_version="2026.08.1")

    assert client.get("/api/meta").json()["host"] is None


def test_openapi_document_describes_the_meta_endpoint(client):
    response = client.get("/api/openapi.json")

    assert response.status_code == 200
    assert "/api/meta" in response.json()["paths"]

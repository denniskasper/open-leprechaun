"""The auth posture: development skips authentication entirely, production requires it.

The credentials production will accept arrive with the login ticket; until
then a protected route in production answers 401 to everyone, and the point
here is that the same dependency waves development straight through.
"""

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from open_leprechaun.auth import AdminDep, require_admin
from open_leprechaun.main import create_app
from open_leprechaun.settings import Environment

# The routes production serves to the world. Everything else must authenticate.
PUBLIC_PATHS = {"/api/health", "/api/meta"}


def _add_protected_probe(client: TestClient) -> None:
    """A route protected the way every future non-public route will be."""

    @client.app.get("/api/probe")
    def probe(admin: AdminDep) -> dict[str, str]:
        return {"subject": admin.subject}


def test_development_serves_protected_routes_without_credentials(make_client):
    client = make_client(Environment.development)
    _add_protected_probe(client)

    response = client.get("/api/probe")

    assert response.status_code == 200
    assert response.json() == {"subject": "admin"}


def test_production_refuses_protected_routes_without_credentials(make_client):
    client = make_client(Environment.production)
    _add_protected_probe(client)

    response = client.get("/api/probe")

    assert response.status_code == 401


def test_every_route_outside_the_public_set_takes_the_admin_dependency():
    """The ratchet that keeps production failing closed.

    A new route either goes on the public list above — a deliberate, reviewed
    act — or it carries the admin dependency. Forgetting is a test failure,
    not an open endpoint.
    """
    unprotected = [
        route.path
        for route in create_app().routes
        if isinstance(route, APIRoute)
        and route.path not in PUBLIC_PATHS
        and not _requires_admin(route.dependant)
    ]

    assert unprotected == []


def _requires_admin(dependant) -> bool:
    if dependant.call is require_admin:
        return True
    return any(_requires_admin(dependency) for dependency in dependant.dependencies)


def test_health_and_meta_stay_public_in_production(make_client):
    client = make_client(Environment.production)

    # 503, not 401: the database behind this client is unreachable, but the
    # endpoint itself answered without asking who is calling.
    assert client.get("/api/health").status_code == 503
    assert client.get("/api/meta").status_code == 200

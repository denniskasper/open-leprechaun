"""The auth posture and the login that satisfies it.

Development skips authentication entirely. Production requires a session:
setup creates the single admin once, login mints a token delivered both as an
httpOnly cookie and in the response body, and the dependency accepts the
cookie first, then a bearer header.
"""

from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import text

from open_leprechaun.auth import SESSION_COOKIE, AdminDep, require_admin
from open_leprechaun.main import create_app
from open_leprechaun.settings import Environment

# The routes production serves to the world. Everything else must authenticate.
# Setup and login are how the admin comes to exist and to hold a session, so
# they cannot themselves sit behind one; logout only revokes what it is handed.
PUBLIC_PATHS = {
    "/api/health",
    "/api/meta",
    "/api/auth/setup",
    "/api/auth/login",
    "/api/auth/logout",
}

PASSWORD = "correct horse battery staple"


def _add_protected_probe(client: TestClient) -> None:
    """A route protected the way every future non-public route will be."""

    @client.app.get("/api/probe")
    def probe(admin: AdminDep) -> dict[str, str]:
        return {"subject": admin.subject}


@pytest.fixture
def production_client(make_client, alembic_config, engine) -> TestClient:
    """A production-mode client over the real test database, with no admin yet."""
    command.upgrade(alembic_config, "head")
    with engine.begin() as connection:
        # Cascades to admin_session, so every test starts before first run.
        connection.execute(text("DELETE FROM admin_user"))
    return make_client(Environment.production, engine=engine)


def _set_up_and_log_in(client: TestClient) -> str:
    assert client.post("/api/auth/setup", json={"password": PASSWORD}).status_code == 201
    response = client.post("/api/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200
    return response.json()["token"]


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


def test_a_fresh_instance_reports_that_setup_is_required(production_client):
    response = production_client.get("/api/auth/setup")

    assert response.status_code == 200
    assert response.json() == {"required": True}


def test_setup_creates_the_admin_and_is_then_no_longer_required(production_client):
    created = production_client.post("/api/auth/setup", json={"password": PASSWORD})

    assert created.status_code == 201
    assert production_client.get("/api/auth/setup").json() == {"required": False}


def test_setup_refuses_to_run_a_second_time(production_client):
    production_client.post("/api/auth/setup", json={"password": PASSWORD})

    again = production_client.post(
        "/api/auth/setup", json={"password": "another password entirely"}
    )

    assert again.status_code == 409


def test_setup_refuses_a_short_password(production_client):
    response = production_client.post("/api/auth/setup", json={"password": "short"})

    assert response.status_code == 422
    assert production_client.get("/api/auth/setup").json() == {"required": True}


def test_the_password_and_its_hash_never_appear_in_a_response(production_client, engine):
    setup = production_client.post("/api/auth/setup", json={"password": PASSWORD})
    login = production_client.post("/api/auth/login", json={"password": PASSWORD})

    with engine.connect() as connection:
        stored_hash = connection.execute(text("SELECT password_hash FROM admin_user")).scalar_one()

    assert PASSWORD not in setup.text + login.text
    assert stored_hash not in setup.text + login.text
    assert PASSWORD not in stored_hash


def test_login_issues_the_same_token_as_cookie_and_body(production_client):
    production_client.post("/api/auth/setup", json={"password": PASSWORD})

    response = production_client.post("/api/auth/login", json={"password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["token"] == response.cookies[SESSION_COOKIE]
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "secure" in set_cookie


def test_login_refuses_a_wrong_password(production_client):
    production_client.post("/api/auth/setup", json={"password": PASSWORD})

    response = production_client.post("/api/auth/login", json={"password": "not the password"})

    assert response.status_code == 401


def test_login_before_setup_points_at_setup(production_client):
    response = production_client.post("/api/auth/login", json={"password": PASSWORD})

    assert response.status_code == 409


def test_the_cookie_authenticates_the_browser(production_client):
    _add_protected_probe(production_client)
    _set_up_and_log_in(production_client)

    # The client carries the cookie by itself, exactly like a browser.
    response = production_client.get("/api/probe")

    assert response.status_code == 200
    assert response.json() == {"subject": "admin"}


def test_the_bearer_header_authenticates_a_cookieless_client(production_client):
    _add_protected_probe(production_client)
    token = _set_up_and_log_in(production_client)
    production_client.cookies.clear()

    response = production_client.get("/api/probe", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def test_a_valid_bearer_still_authenticates_when_the_cookie_has_gone_stale(production_client):
    """Cookie first, then bearer: a dead cookie falls through instead of vetoing."""
    _add_protected_probe(production_client)
    token = _set_up_and_log_in(production_client)
    production_client.cookies.set(SESSION_COOKIE, "a-token-that-was-never-issued")

    response = production_client.get("/api/probe", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def test_a_token_nobody_issued_is_refused(production_client):
    _add_protected_probe(production_client)
    _set_up_and_log_in(production_client)
    production_client.cookies.clear()

    response = production_client.get(
        "/api/probe", headers={"Authorization": "Bearer a-token-that-was-never-issued"}
    )

    assert response.status_code == 401


def test_an_expired_session_is_refused(production_client, engine):
    _add_protected_probe(production_client)
    _set_up_and_log_in(production_client)
    with engine.begin() as connection:
        connection.execute(text("UPDATE admin_session SET expires_at = now() - interval '1 hour'"))

    response = production_client.get("/api/probe")

    assert response.status_code == 401


def test_an_authenticated_request_renews_the_browser_cookie(production_client):
    """The cookie's lifetime slides with the session's, not with login's date."""
    _add_protected_probe(production_client)
    _set_up_and_log_in(production_client)

    response = production_client.get("/api/probe")

    set_cookie = response.headers.get("set-cookie", "")
    assert SESSION_COOKIE in set_cookie
    assert "Max-Age" in set_cookie


def test_a_bearer_request_gets_no_cookie(production_client):
    """A cookieless client asked for none and receives none."""
    _add_protected_probe(production_client)
    token = _set_up_and_log_in(production_client)
    production_client.cookies.clear()

    response = production_client.get("/api/probe", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert "set-cookie" not in response.headers


def test_a_malformed_stored_hash_verifies_as_nothing(production_client, engine):
    """Corrupt credential data reads as a wrong password, never a crash."""
    production_client.post("/api/auth/setup", json={"password": PASSWORD})
    with engine.begin() as connection:
        connection.execute(text("UPDATE admin_user SET password_hash = 'not a real hash'"))

    response = production_client.post("/api/auth/login", json={"password": PASSWORD})

    assert response.status_code == 401


def test_each_authenticated_request_slides_the_expiry_forward(production_client, engine):
    """The documented renewal behaviour: the lifetime runs from last use."""
    _add_protected_probe(production_client)
    _set_up_and_log_in(production_client)
    nearly_expired = datetime.now(UTC) + timedelta(minutes=5)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE admin_session SET expires_at = :at"), {"at": nearly_expired}
        )

    assert production_client.get("/api/probe").status_code == 200

    with engine.connect() as connection:
        renewed = connection.execute(text("SELECT expires_at FROM admin_session")).scalar_one()
    assert renewed > nearly_expired + timedelta(hours=1)


def test_the_session_lifetime_is_configurable(make_client, alembic_config, engine):
    command.upgrade(alembic_config, "head")
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM admin_user"))
    client = make_client(Environment.production, engine=engine, session_ttl_hours=1)

    client.post("/api/auth/setup", json={"password": PASSWORD})
    before = datetime.now(UTC)
    client.post("/api/auth/login", json={"password": PASSWORD})

    with engine.connect() as connection:
        expires_at = connection.execute(text("SELECT expires_at FROM admin_session")).scalar_one()
    assert before + timedelta(minutes=59) < expires_at < before + timedelta(minutes=61)


def test_logout_revokes_the_session(production_client):
    _add_protected_probe(production_client)
    token = _set_up_and_log_in(production_client)

    assert production_client.post("/api/auth/logout").status_code == 204

    production_client.cookies.clear()
    response = production_client.get("/api/probe", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_the_session_endpoint_names_the_caller(production_client):
    _set_up_and_log_in(production_client)

    response = production_client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json() == {"subject": "admin"}

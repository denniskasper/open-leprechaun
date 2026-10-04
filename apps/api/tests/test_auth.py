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
from open_leprechaun.routers.auth import get_clock
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


class _SteppedClock:
    """The login's clock, moved only by the test: backoff is measured in
    seconds to minutes, and no test should wait them out."""

    def __init__(self) -> None:
        self._now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, **delta) -> None:
        self._now += timedelta(**delta)


@pytest.fixture
def clock() -> _SteppedClock:
    return _SteppedClock()


@pytest.fixture
def production_client(make_client, alembic_config, engine, clock) -> TestClient:
    """A production-mode client over the real test database, with no admin yet."""
    command.upgrade(alembic_config, "head")
    with engine.begin() as connection:
        # Cascades to admin_session, so every test starts before first run.
        connection.execute(text("DELETE FROM admin_user"))
        # Failures are keyed by address alone, and every test client shares one.
        connection.execute(text("DELETE FROM login_failure"))
    client = make_client(Environment.production, engine=engine)
    client.app.dependency_overrides[get_clock] = lambda: clock
    return client


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


NEW_PASSWORD = "a rather different passphrase"


def test_setup_and_change_share_one_minimum_password_length(production_client):
    """One floor, two doors: neither takes an 11-character password."""
    eleven = "x" * 11

    assert production_client.post("/api/auth/setup", json={"password": eleven}).status_code == 422

    _set_up_and_log_in(production_client)
    changed = production_client.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": eleven}
    )
    assert changed.status_code == 422
    # The twelfth character is what both were waiting for.
    accepted = production_client.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": "x" * 12}
    )
    assert accepted.status_code == 204


def test_changing_the_password_refuses_a_wrong_current_password(production_client):
    _set_up_and_log_in(production_client)

    refused = production_client.post(
        "/api/auth/password",
        json={"current_password": "not the password", "new_password": NEW_PASSWORD},
    )

    assert refused.status_code == 403
    # Nothing changed: the old password still logs in, the new one does not.
    assert production_client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 200
    assert (
        production_client.post("/api/auth/login", json={"password": NEW_PASSWORD}).status_code
        == 401
    )


def test_a_changed_password_replaces_the_old_one_at_login(production_client, clock):
    _set_up_and_log_in(production_client)

    changed = production_client.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    )

    assert changed.status_code == 204
    assert production_client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 401
    clock.advance(seconds=1)  # the failed attempt's delay
    assert (
        production_client.post("/api/auth/login", json={"password": NEW_PASSWORD}).status_code
        == 200
    )


def _log_in_elsewhere(client: TestClient, password: str = PASSWORD) -> str:
    """A second Session, as another browser would hold: its token, not our cookie."""
    cookie = client.cookies.get(SESSION_COOKIE)
    token = client.post("/api/auth/login", json={"password": password}).json()["token"]
    client.cookies.set(SESSION_COOKIE, cookie)
    return token


def test_changing_the_password_revokes_every_other_session_and_keeps_this_one(
    production_client,
):
    _add_protected_probe(production_client)
    _set_up_and_log_in(production_client)
    elsewhere = _log_in_elsewhere(production_client)

    changed = production_client.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    )

    assert changed.status_code == 204
    # The cookie this client changed the password with still works...
    assert production_client.get("/api/probe").status_code == 200
    # ...and the other browser's Session is gone.
    production_client.cookies.clear()
    stranger = production_client.get("/api/probe", headers={"Authorization": f"Bearer {elsewhere}"})
    assert stranger.status_code == 401


def test_a_bearer_client_that_changes_the_password_keeps_its_own_session(production_client):
    """The session kept is the one that authenticated, cookie or not."""
    _add_protected_probe(production_client)
    browser = _set_up_and_log_in(production_client)
    client = _log_in_elsewhere(production_client)
    production_client.cookies.clear()
    as_client = {"Authorization": f"Bearer {client}"}

    changed = production_client.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=as_client,
    )

    assert changed.status_code == 204
    assert production_client.get("/api/probe", headers=as_client).status_code == 200
    abandoned = production_client.get("/api/probe", headers={"Authorization": f"Bearer {browser}"})
    assert abandoned.status_code == 401


def test_changing_the_password_before_setup_points_at_setup(make_client, alembic_config, engine):
    """Development authenticates nobody, so it can reach this with no admin."""
    command.upgrade(alembic_config, "head")
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM admin_user"))
    client = make_client(Environment.development, engine=engine)

    response = client.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    )

    assert response.status_code == 409


def test_the_active_session_count_follows_logins_and_ignores_the_expired(production_client, engine):
    _set_up_and_log_in(production_client)
    assert production_client.get("/api/auth/sessions").json() == {"active": 1}

    elsewhere = _log_in_elsewhere(production_client)
    assert production_client.get("/api/auth/sessions").json() == {"active": 2}

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE admin_session SET expires_at = now() - interval '1 hour' "
                "WHERE token_hash = encode(sha256(convert_to(:token, 'UTF8')), 'hex')"
            ),
            {"token": elsewhere},
        )
    assert production_client.get("/api/auth/sessions").json() == {"active": 1}


def test_signing_out_everywhere_revokes_every_session_including_this_one(production_client):
    _add_protected_probe(production_client)
    here = _set_up_and_log_in(production_client)
    elsewhere = _log_in_elsewhere(production_client)

    response = production_client.delete("/api/auth/sessions")

    assert response.status_code == 204
    # The browser is told to drop its cookie, not left holding a dead one: of
    # the cookies this response sets, the last word is the deletion.
    assert response.headers.get_list("set-cookie")[-1].startswith(f'{SESSION_COOKIE}=""')
    production_client.cookies.clear()
    for token in (here, elsewhere):
        refused = production_client.get("/api/probe", headers={"Authorization": f"Bearer {token}"})
        assert refused.status_code == 401


def test_signing_out_everywhere_requires_a_session(production_client):
    production_client.post("/api/auth/setup", json={"password": PASSWORD})

    assert production_client.delete("/api/auth/sessions").status_code == 401


def _guess(client: TestClient, password: str = "not the password"):
    return client.post("/api/auth/login", json={"password": password})


def test_a_failed_login_delays_the_next_attempt_from_that_address(production_client, clock):
    production_client.post("/api/auth/setup", json={"password": PASSWORD})
    assert _guess(production_client).status_code == 401

    throttled = _guess(production_client)

    assert throttled.status_code == 429
    assert throttled.headers["retry-after"] == "1"
    clock.advance(seconds=1)
    assert _guess(production_client).status_code == 401


def _fail(client: TestClient, clock: _SteppedClock, times: int) -> None:
    """Fail that many logins, each one made as soon as the last one's delay lets it."""
    for _ in range(times):
        response = _guess(client)
        if response.status_code == 429:
            clock.advance(seconds=int(response.headers["retry-after"]))
            response = _guess(client)
        assert response.status_code == 401


def _client_from(address: str, client: TestClient) -> TestClient:
    """The same running instance, reached from another source address."""
    return TestClient(client.app, base_url="https://testserver", client=(address, 50000))


def test_the_delay_doubles_with_each_failure_up_to_a_cap(production_client, clock):
    production_client.post("/api/auth/setup", json={"password": PASSWORD})
    delays = []

    for _ in range(11):
        assert _guess(production_client).status_code == 401
        delay = int(_guess(production_client).headers["retry-after"])
        delays.append(delay)
        clock.advance(seconds=delay)

    assert delays == [1, 2, 4, 8, 16, 32, 64, 128, 256, 300, 300]


def test_a_throttled_attempt_is_refused_the_same_whether_or_not_the_password_was_right(
    production_client,
):
    production_client.post("/api/auth/setup", json={"password": PASSWORD})
    assert _guess(production_client).status_code == 401

    wrong = _guess(production_client)
    right = _guess(production_client, PASSWORD)

    assert right.status_code == 429
    assert (right.json(), right.headers["retry-after"]) == (
        wrong.json(),
        wrong.headers["retry-after"],
    )
    assert SESSION_COOKIE not in right.cookies


def test_the_correct_password_still_succeeds_after_the_backoff(production_client, clock):
    production_client.post("/api/auth/setup", json={"password": PASSWORD})
    _fail(production_client, clock, times=12)
    assert _guess(production_client, PASSWORD).status_code == 429

    clock.advance(minutes=5)

    assert _guess(production_client, PASSWORD).status_code == 200


def test_hammering_through_a_delay_does_not_lengthen_it(production_client, clock):
    """What keeps a delay from becoming a lock: an attacker who never stops
    cannot push the moment the Admin may try any further away."""
    production_client.post("/api/auth/setup", json={"password": PASSWORD})
    _fail(production_client, clock, times=3)

    for _ in range(25):
        assert _guess(production_client).status_code == 429
    clock.advance(seconds=4)

    assert _guess(production_client, PASSWORD).status_code == 200


def test_a_correct_password_clears_the_address_of_its_failures(production_client, clock):
    production_client.post("/api/auth/setup", json={"password": PASSWORD})
    _fail(production_client, clock, times=4)
    clock.advance(seconds=8)
    assert _guess(production_client, PASSWORD).status_code == 200

    assert _guess(production_client).status_code == 401

    assert _guess(production_client).headers["retry-after"] == "1"


def test_one_address_failing_does_not_delay_another(production_client, clock):
    production_client.post("/api/auth/setup", json={"password": PASSWORD})
    attacker = _client_from("203.0.113.7", production_client)
    _fail(attacker, clock, times=5)
    assert _guess(attacker).status_code == 429

    assert _guess(production_client, PASSWORD).status_code == 200
    # ...and the Admin logging in from home forgives nothing elsewhere.
    assert _guess(attacker).status_code == 429


def test_a_restarted_instance_remembers_the_failures(production_client, make_client, engine, clock):
    production_client.post("/api/auth/setup", json={"password": PASSWORD})
    _fail(production_client, clock, times=3)

    restarted = make_client(Environment.production, engine=engine)
    restarted.app.dependency_overrides[get_clock] = lambda: clock
    throttled = _guess(restarted)

    assert throttled.status_code == 429
    assert throttled.headers["retry-after"] == "4"


def test_failures_gone_stale_count_for_nothing(production_client, clock):
    production_client.post("/api/auth/setup", json={"password": PASSWORD})
    _fail(production_client, clock, times=6)

    clock.advance(days=1, seconds=32)

    assert _guess(production_client).status_code == 401
    assert _guess(production_client).headers["retry-after"] == "1"


def test_a_login_purges_the_failure_records_gone_stale(production_client, engine, clock):
    production_client.post("/api/auth/setup", json={"password": PASSWORD})
    _fail(_client_from("203.0.113.7", production_client), clock, times=2)
    clock.advance(hours=12)
    _fail(_client_from("203.0.113.8", production_client), clock, times=2)

    clock.advance(hours=12, seconds=2)
    assert _guess(production_client, PASSWORD).status_code == 200

    with engine.connect() as connection:
        remembered = connection.execute(text("SELECT address FROM login_failure")).scalars().all()
    assert remembered == ["203.0.113.8"]

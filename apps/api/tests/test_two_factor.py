"""The Admin's TOTP second factor (ADR-0005).

Optional, enabled from settings, proven by a code before it activates. Login
stays the single endpoint: it answers a distinct `code_required` while a code
is still owed, and a correct code gates the unchanged token. There are no
recovery codes — the way back in is the server-side disable.
"""

import base64
import hashlib
import hmac
import struct
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import text

from open_leprechaun import disable_two_factor
from open_leprechaun.auth import SESSION_COOKIE
from open_leprechaun.routers.auth import get_clock
from open_leprechaun.settings import Environment

PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a rather different passphrase"


def _code(secret: str, at: datetime) -> str:
    """What an authenticator app shows for the secret at that instant.

    RFC 6238 written out independently of the service — SHA-1, six digits,
    thirty-second steps — and held to the RFC's own vectors below, so a code
    the API accepts from here is one a real app would have shown.
    """
    key = base64.b32decode(secret)
    counter = struct.pack(">Q", int(at.timestamp()) // 30)
    mac = hmac.new(key, counter, hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    number = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{number % 1_000_000:06d}"


@pytest.mark.parametrize(
    ("unix_time", "expected"),
    [(59, "287082"), (1111111109, "081804"), (1234567890, "005924")],
)
def test_the_tests_own_authenticator_agrees_with_rfc_6238(unix_time, expected):
    secret = base64.b32encode(b"12345678901234567890").decode()

    assert _code(secret, datetime.fromtimestamp(unix_time, UTC)) == expected


class _SteppedClock:
    """The API's clock, moved only by the test: codes change every thirty
    seconds and backoff runs to minutes, and no test should wait either out."""

    def __init__(self) -> None:
        # Five seconds into a thirty-second step, so a test that moves a few
        # seconds on stays inside the step it started in, whenever it runs.
        started = int(datetime.now(UTC).timestamp()) // 30 * 30 + 5
        self._now = datetime.fromtimestamp(started, UTC)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, **delta) -> None:
        self._now += timedelta(**delta)


@pytest.fixture
def clock() -> _SteppedClock:
    return _SteppedClock()


@pytest.fixture
def production_client(make_client, alembic_config, engine, clock) -> TestClient:
    """A production-mode client over the real test database, logged in as a
    freshly set-up Admin with no second factor yet."""
    command.upgrade(alembic_config, "head")
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM admin_user"))
        connection.execute(text("DELETE FROM login_failure"))
    client = make_client(Environment.production, engine=engine)
    client.app.dependency_overrides[get_clock] = lambda: clock
    assert client.post("/api/auth/setup", json={"password": PASSWORD}).status_code == 201
    assert client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 200
    return client


def _enroll(client: TestClient) -> str:
    """Start enrollment and answer the secret the authenticator would store."""
    response = client.post("/api/auth/two-factor/enrollment")
    assert response.status_code == 201
    return response.json()["secret"]


def _enable(client: TestClient, clock: _SteppedClock) -> str:
    """Enroll and activate, then move to a fresh code: one that was accepted
    is spent, so the next proof needs the next step."""
    secret = _enroll(client)
    activated = client.post(
        "/api/auth/two-factor/activation", json={"code": _code(secret, clock())}
    )
    assert activated.status_code == 204
    clock.advance(seconds=30)
    return secret


def _enabled(client: TestClient) -> bool:
    response = client.get("/api/auth/two-factor")
    assert response.status_code == 200
    return response.json()["enabled"]


def test_two_factor_is_off_until_the_admin_enables_it(production_client):
    assert _enabled(production_client) is False


def test_enrollment_hands_out_the_secret_and_a_uri_an_authenticator_can_read(production_client):
    response = production_client.post("/api/auth/two-factor/enrollment")

    assert response.status_code == 201
    body = response.json()
    uri = urlparse(body["uri"])
    assert (uri.scheme, uri.netloc) == ("otpauth", "totp")
    assert parse_qs(uri.query)["secret"] == [body["secret"]]
    assert parse_qs(uri.query)["issuer"] == ["Open Leprechaun"]
    # 160 bits, as RFC 4226 recommends: 32 base32 characters, no padding.
    assert len(base64.b32decode(body["secret"])) == 20


def test_enrolling_alone_activates_nothing(production_client):
    _enroll(production_client)

    assert _enabled(production_client) is False
    production_client.cookies.clear()
    assert production_client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 200


def test_a_wrong_code_does_not_activate(production_client, clock):
    secret = _enroll(production_client)
    wrong = f"{(int(_code(secret, clock())) + 1) % 1_000_000:06d}"

    refused = production_client.post("/api/auth/two-factor/activation", json={"code": wrong})

    assert refused.status_code == 403
    assert _enabled(production_client) is False


def test_a_verifying_code_activates_two_factor(production_client, clock):
    secret = _enroll(production_client)

    activated = production_client.post(
        "/api/auth/two-factor/activation", json={"code": _code(secret, clock())}
    )

    assert activated.status_code == 204
    assert _enabled(production_client) is True


def test_activation_without_an_enrollment_is_refused(production_client):
    refused = production_client.post("/api/auth/two-factor/activation", json={"code": "123456"})

    assert refused.status_code == 409


def test_the_secret_is_encrypted_at_rest(production_client, engine, clock):
    pending = _enroll(production_client)
    with engine.connect() as connection:
        stored_pending = connection.execute(
            text("SELECT totp_pending_secret FROM admin_user")
        ).scalar_one()
    production_client.post(
        "/api/auth/two-factor/activation", json={"code": _code(pending, clock())}
    )
    with engine.connect() as connection:
        stored_active = connection.execute(text("SELECT totp_secret FROM admin_user")).scalar_one()

    for stored in (bytes(stored_pending), bytes(stored_active)):
        assert pending.encode() not in stored
        assert base64.b32decode(pending) not in stored


def test_enrollment_is_refused_while_two_factor_is_active(production_client, clock):
    _enable(production_client, clock)

    refused = production_client.post("/api/auth/two-factor/enrollment")

    assert refused.status_code == 409
    assert _enabled(production_client) is True


def _fresh_client(client: TestClient) -> TestClient:
    """The same instance seen by a browser that holds no session."""
    client.cookies.clear()
    return client


def test_login_answers_a_distinct_code_required_when_the_password_came_alone(
    production_client, clock
):
    _enable(production_client, clock)
    client = _fresh_client(production_client)

    response = client.post("/api/auth/login", json={"password": PASSWORD})

    assert response.status_code == 401
    assert response.json()["result"] == "code_required"
    assert SESSION_COOKIE not in response.cookies
    assert "token" not in response.json()


def test_a_wrong_password_is_never_told_that_a_code_is_owed(production_client, clock):
    secret = _enable(production_client, clock)
    client = _fresh_client(production_client)

    response = client.post(
        "/api/auth/login", json={"password": "not the password", "code": _code(secret, clock())}
    )

    assert response.status_code == 401
    assert response.json()["result"] == "wrong_password"


def test_login_refuses_a_wrong_code(production_client, clock):
    secret = _enable(production_client, clock)
    client = _fresh_client(production_client)
    wrong = f"{(int(_code(secret, clock())) + 1) % 1_000_000:06d}"

    response = client.post("/api/auth/login", json={"password": PASSWORD, "code": wrong})

    assert response.status_code == 401
    assert response.json()["result"] == "wrong_code"
    assert SESSION_COOKIE not in response.cookies


def test_both_factors_issue_the_unchanged_token_on_the_cookie_and_the_bearer_path(
    production_client, clock
):
    secret = _enable(production_client, clock)
    client = _fresh_client(production_client)

    response = client.post(
        "/api/auth/login", json={"password": PASSWORD, "code": _code(secret, clock())}
    )

    # The same shape a one-factor login answers: one token, cookie and body.
    assert response.status_code == 200
    assert set(response.json()) == {"token", "expires_at"}
    token = response.json()["token"]
    assert response.cookies[SESSION_COOKIE] == token
    assert client.get("/api/auth/session").status_code == 200
    client.cookies.clear()
    bearer = client.get("/api/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert bearer.status_code == 200


def test_the_second_step_of_a_login_may_follow_the_first_at_once(production_client, clock):
    """What the browser does: the password alone, then the same again with the
    code. Being asked for the code is not a failure, so nothing delays the
    answer — a password manager fills it in within the same second."""
    secret = _enable(production_client, clock)
    client = _fresh_client(production_client)

    asked = client.post("/api/auth/login", json={"password": PASSWORD})
    entered = client.post(
        "/api/auth/login", json={"password": PASSWORD, "code": _code(secret, clock())}
    )

    assert asked.json()["result"] == "code_required"
    assert entered.status_code == 200


def test_a_code_typed_the_way_the_app_shows_it_is_accepted(production_client, clock):
    secret = _enable(production_client, clock)
    client = _fresh_client(production_client)
    code = _code(secret, clock())

    response = client.post(
        "/api/auth/login", json={"password": PASSWORD, "code": f"{code[:3]} {code[3:]}"}
    )

    assert response.status_code == 200


def test_a_code_from_the_previous_step_still_verifies_and_an_older_one_does_not(
    production_client, clock
):
    secret = _enable(production_client, clock)
    client = _fresh_client(production_client)
    stale = _code(secret, clock() - timedelta(seconds=90))
    # Activation spent the step before this one; move on so `previous` is unspent.
    clock.advance(seconds=30)
    previous = _code(secret, clock() - timedelta(seconds=30))

    too_old = client.post("/api/auth/login", json={"password": PASSWORD, "code": stale})
    clock.advance(seconds=1)
    drifted = client.post("/api/auth/login", json={"password": PASSWORD, "code": previous})

    assert too_old.json()["result"] == "wrong_code"
    assert drifted.status_code == 200


def test_a_code_is_accepted_only_once(production_client, clock):
    secret = _enable(production_client, clock)
    client = _fresh_client(production_client)
    code = _code(secret, clock())
    assert client.post(
        "/api/auth/login", json={"password": PASSWORD, "code": code}
    ).status_code == (200)

    replayed = _fresh_client(client).post(
        "/api/auth/login", json={"password": PASSWORD, "code": code}
    )

    assert replayed.status_code == 401
    assert replayed.json()["result"] == "wrong_code"


def test_guessing_codes_is_throttled_like_guessing_passwords(production_client, clock):
    _enable(production_client, clock)
    client = _fresh_client(production_client)

    first = client.post("/api/auth/login", json={"password": PASSWORD, "code": "000000"})
    second = client.post("/api/auth/login", json={"password": PASSWORD, "code": "000001"})

    assert first.status_code == 401
    assert second.status_code == 429


def test_asking_again_without_a_code_does_not_reset_the_delay_wrong_codes_earned(
    production_client, clock
):
    """The throttle cannot be laundered: alternating a code-less request with
    each guess must not buy the next guess any sooner."""
    _enable(production_client, clock)
    client = _fresh_client(production_client)
    client.post("/api/auth/login", json={"password": PASSWORD, "code": "000000"})
    clock.advance(seconds=1)
    assert client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 401
    client.post("/api/auth/login", json={"password": PASSWORD, "code": "000001"})

    # Third counted attempt: its delay is four seconds, not the first one's one.
    clock.advance(seconds=3)
    still_waiting = client.post("/api/auth/login", json={"password": PASSWORD, "code": "000002"})

    assert still_waiting.status_code == 429


def test_activation_signs_out_the_sessions_the_password_alone_opened(production_client, clock):
    elsewhere = production_client.post("/api/auth/login", json={"password": PASSWORD}).json()[
        "token"
    ]
    production_client.cookies.clear()
    here = production_client.post("/api/auth/login", json={"password": PASSWORD}).json()["token"]

    _enable(production_client, clock)

    assert production_client.get("/api/auth/session").status_code == 200
    production_client.cookies.clear()
    assert (
        production_client.get(
            "/api/auth/session", headers={"Authorization": f"Bearer {elsewhere}"}
        ).status_code
        == 401
    )
    assert (
        production_client.get(
            "/api/auth/session", headers={"Authorization": f"Bearer {here}"}
        ).status_code
        == 200
    )


def _change_password(client: TestClient, **extra):
    return client.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD, **extra},
    )


def test_changing_the_password_takes_a_current_code_while_two_factor_is_on(
    production_client, clock
):
    secret = _enable(production_client, clock)
    wrong = f"{(int(_code(secret, clock())) + 1) % 1_000_000:06d}"

    without = _change_password(production_client)
    with_wrong = _change_password(production_client, code=wrong)

    assert without.status_code == 403
    assert with_wrong.status_code == 403
    clock.advance(seconds=2)  # the delay the wrong code earned
    assert _change_password(production_client, code=_code(secret, clock())).status_code == 204
    clock.advance(seconds=30)
    entered = _fresh_client(production_client).post(
        "/api/auth/login", json={"password": NEW_PASSWORD, "code": _code(secret, clock())}
    )
    assert entered.status_code == 200


def test_changing_the_password_takes_no_code_while_two_factor_is_off(production_client):
    assert _change_password(production_client).status_code == 204


def test_disabling_takes_the_password_and_a_current_code(production_client, clock):
    secret = _enable(production_client, clock)
    code = _code(secret, clock())

    wrong_password = production_client.post(
        "/api/auth/two-factor/disable", json={"current_password": "not it", "code": code}
    )
    clock.advance(seconds=1)
    wrong_code = production_client.post(
        "/api/auth/two-factor/disable",
        json={"current_password": PASSWORD, "code": f"{(int(code) + 1) % 1_000_000:06d}"},
    )
    assert (wrong_password.status_code, wrong_code.status_code) == (403, 403)
    assert _enabled(production_client) is True
    clock.advance(seconds=2)  # the delay two failures earned
    code = _code(secret, clock())

    disabled = production_client.post(
        "/api/auth/two-factor/disable", json={"current_password": PASSWORD, "code": code}
    )

    assert disabled.status_code == 204
    assert _enabled(production_client) is False
    assert (
        _fresh_client(production_client)
        .post("/api/auth/login", json={"password": PASSWORD})
        .status_code
        == 200
    )


def test_a_session_does_not_buy_unmetered_guesses_at_the_code(production_client, clock):
    """Someone holding a stolen session and the password must not be able to
    run through the codes at the disable or the password change."""
    _enable(production_client, clock)

    first = production_client.post(
        "/api/auth/two-factor/disable", json={"current_password": PASSWORD, "code": "000000"}
    )
    second = production_client.post(
        "/api/auth/two-factor/disable", json={"current_password": PASSWORD, "code": "000001"}
    )
    third = _change_password(production_client, code="000002")

    assert first.status_code == 403
    assert (second.status_code, third.status_code) == (429, 429)
    assert second.headers["Retry-After"] == "1"
    assert _enabled(production_client) is True


def test_disabling_what_is_not_on_is_refused(production_client):
    refused = production_client.post(
        "/api/auth/two-factor/disable", json={"current_password": PASSWORD, "code": "123456"}
    )

    assert refused.status_code == 409


def test_a_secret_from_before_a_disable_proves_nothing_afterwards(production_client, clock):
    old = _enable(production_client, clock)
    production_client.post(
        "/api/auth/two-factor/disable",
        json={"current_password": PASSWORD, "code": _code(old, clock())},
    )
    clock.advance(seconds=30)
    _enroll(production_client)

    refused = production_client.post(
        "/api/auth/two-factor/activation", json={"code": _code(old, clock())}
    )

    assert refused.status_code == 403


def test_the_server_side_disable_lets_the_password_alone_back_in(production_client, engine, clock):
    """The anti-lockout path: the authenticator is gone, the host is not."""
    _enable(production_client, clock)
    client = _fresh_client(production_client)
    assert client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 401

    said = disable_two_factor.disable(engine)

    assert "disabled" in said
    assert client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 200
    assert _enabled(client) is False


def test_the_server_side_disable_says_so_when_there_was_nothing_to_disable(
    production_client, engine
):
    assert "not enabled" in disable_two_factor.disable(engine)


def test_the_two_factor_routes_require_a_session(production_client):
    client = _fresh_client(production_client)

    assert client.get("/api/auth/two-factor").status_code == 401
    assert client.post("/api/auth/two-factor/enrollment").status_code == 401

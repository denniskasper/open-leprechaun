"""Connection: the single credentialed link to one venue account (ADR-0004),
its credentials encrypted before they touch the database and never returned by
any endpoint in any form (ADR-0003).

The seams are the service over real Postgres — encryption and the schema's
constraints are what is under test — and the HTTP endpoints through the app.
"""

import logging

from sqlalchemy import text

from open_leprechaun.repositories import platforms
from open_leprechaun.services import connections
from open_leprechaun.settings import get_settings

KEY = "AJVqhlN2mUvg5rlIT4YDkbA1"
SECRET = "wJmoXjRk8pdFqe37cChM/2Zt5yUwbBHGSA=="
PASSPHRASE = "correct horse battery staple"


def register(db, platform_id, **overrides):
    given = dict(
        platform_id=platform_id,
        venue="okx",
        label="Main account",
        key=KEY,
        secret=SECRET,
        passphrase=PASSPHRASE,
    )
    given.update(overrides)
    return connections.register(db, get_settings(), **given)


def exchange(db, name="OKX"):
    return platforms.create_platform(db, name=name, kind="exchange")


def test_only_ciphertext_reaches_the_database(db):
    """The stored bytes contain no trace of the key, the secret or the
    passphrase — a database dump hands over nothing."""
    register(db, exchange(db))

    (row,) = db.connect().execute(text("SELECT * FROM connection")).mappings().all()
    stored = bytes(row["credentials_ciphertext"])
    for material in (KEY, SECRET, PASSPHRASE):
        assert material.encode() not in stored
        assert material not in str(dict(row))


def test_credentials_come_back_intact_for_a_sync(db):
    """Decryption round-trips exactly — the adapter (ticket 35) receives what
    the Admin typed, and using the credentials stamps last_used_at."""
    connection_id = register(db, exchange(db))

    credentials = connections.credentials_of(db, get_settings(), connection_id)

    assert credentials == connections.Credentials(key=KEY, secret=SECRET, passphrase=PASSPHRASE)
    (overview,) = connections.overview(db)
    assert overview.last_used_at is not None


def test_credentials_of_a_connection_that_is_not_there_is_none(db):
    assert connections.credentials_of(db, get_settings(), 12345) is None


def test_several_connections_to_the_same_platform(db):
    """One venue account per Connection, several accounts at one venue — both
    register, told apart by label."""
    okx = exchange(db)

    first = register(db, okx, label="Main account")
    second = register(db, okx, label="Bot subaccount")

    assert isinstance(first, int)
    assert isinstance(second, int)


def test_the_same_label_within_a_platform_mints_no_second(db):
    okx = exchange(db)
    register(db, okx, label="Main account")

    assert register(db, okx, label="Main account") is connections.Refusal.label_taken


def test_a_connection_under_a_platform_that_is_not_there_says_so(db):
    assert register(db, 12345) is connections.Refusal.no_such_platform


def test_a_venue_outside_the_registry_is_refused(db):
    """A Connection must resolve to adapters one day, so a venue nothing
    implements is refused at the door."""
    assert register(db, exchange(db), venue="mtgox") is connections.Refusal.unknown_venue


def test_a_passphrase_is_required_exactly_where_the_venue_requires_one(db):
    """OKX signs with key, secret and passphrase; Coinbase has no passphrase.
    The registry decides, not the caller."""
    okx = exchange(db)
    coinbase = exchange(db, name="Coinbase")

    assert register(db, okx, passphrase=None) is connections.Refusal.passphrase_missing
    assert isinstance(register(db, coinbase, venue="coinbase", label="Main", passphrase=None), int)


def test_a_key_only_venue_needs_no_secret(db):
    """Trading 212 authenticates with a single API key — the registry knows,
    and the missing secret is not an error there."""
    broker = platforms.create_platform(db, name="Trading 212", kind="broker")

    created = register(
        db, broker, venue="trading_212", label="Invest", secret=None, passphrase=None
    )

    assert isinstance(created, int)


def test_a_secret_is_required_where_the_venue_signs_with_one(db):
    assert register(db, exchange(db), secret=None) is connections.Refusal.secret_missing


def test_the_fingerprint_recognises_a_key_without_revealing_it(db):
    """Deterministic for the same key — the Admin can match it against a
    venue's own key list — while disclosing none of the key itself."""
    okx = exchange(db)
    register(db, okx, label="First", key=KEY)
    register(db, okx, label="Again", key=KEY)
    register(db, okx, label="Other", key="AnEntirelyDifferentKey42")

    first, again, other = sorted(connections.overview(db), key=lambda o: o.id)
    assert first.fingerprint == again.fingerprint
    assert other.fingerprint != first.fingerprint
    assert KEY not in first.fingerprint
    assert len(first.fingerprint) <= 16


def test_results_are_recorded_per_adapter_kind(db):
    """Spot succeeding and futures failing are two answers, never one — and a
    later success updates its own kind's row rather than minting another."""
    connection_id = register(db, exchange(db))

    assert connections.record_result(db, connection_id, "spot", error=None)
    assert connections.record_result(db, connection_id, "futures", error="401 from the venue")
    assert connections.record_result(db, connection_id, "spot", error=None)

    (overview,) = connections.overview(db)
    by_kind = {status.adapter_kind: status for status in overview.statuses}
    assert set(by_kind) == {"spot", "futures"}
    assert by_kind["spot"].last_success_at is not None
    assert by_kind["spot"].last_error is None
    assert by_kind["futures"].last_error == "401 from the venue"
    assert by_kind["futures"].last_success_at is None


def test_a_result_for_a_connection_that_is_not_there_is_refused(db):
    assert not connections.record_result(db, 12345, "spot", error=None)


def test_an_error_does_not_erase_the_last_success(db):
    """The health panel needs both: when the kind last worked and what broke
    since."""
    connection_id = register(db, exchange(db))
    connections.record_result(db, connection_id, "spot", error=None)
    connections.record_result(db, connection_id, "spot", error="timeout")

    (overview,) = connections.overview(db)
    (status,) = overview.statuses
    assert status.last_success_at is not None
    assert status.last_error == "timeout"
    assert status.last_error_at is not None


def test_the_api_registers_and_lists_without_ever_returning_secret_material(client, db):
    """The list shows a label, a fingerprint and a last-used timestamp — not
    masked secrets, not last four characters, nothing."""
    platform_id = client.post("/api/platforms", json={"name": "OKX", "kind": "exchange"}).json()[
        "id"
    ]

    created = client.post(
        "/api/connections",
        json={
            "platform_id": platform_id,
            "venue": "okx",
            "label": "Main account",
            "key": KEY,
            "secret": SECRET,
            "passphrase": PASSPHRASE,
        },
    )
    assert created.status_code == 201
    for material in (KEY, SECRET, PASSPHRASE):
        assert material not in created.text

    listed = client.get("/api/connections")
    for material in (KEY, SECRET, PASSPHRASE):
        assert material not in listed.text
    (connection,) = listed.json()
    assert connection["label"] == "Main account"
    assert connection["venue"] == "okx"
    assert connection["platform_id"] == platform_id
    assert connection["fingerprint"]
    assert connection["last_used_at"] is None
    assert connection["statuses"] == []


def test_no_secret_ever_reaches_a_log(client, db, caplog):
    """Everything logged while registering — at any level — is free of the
    material."""
    platform_id = client.post("/api/platforms", json={"name": "OKX", "kind": "exchange"}).json()[
        "id"
    ]

    with caplog.at_level(logging.DEBUG):
        client.post(
            "/api/connections",
            json={
                "platform_id": platform_id,
                "venue": "okx",
                "label": "Main account",
                "key": KEY,
                "secret": SECRET,
                "passphrase": PASSPHRASE,
            },
        )

    logged = "\n".join(record.getMessage() for record in caplog.records)
    for material in (KEY, SECRET, PASSPHRASE):
        assert material not in logged


def test_a_malformed_request_is_refused_without_echoing_the_secrets(client, db):
    """FastAPI's default 422 answer would return the offending input — the
    whole credential set — back to the caller. The app strips it: what was
    wrong and where, never the values."""
    response = client.post(
        "/api/connections",
        json={
            # platform_id missing: a validation error, not a service refusal.
            "venue": "okx",
            "label": "Main account",
            "key": KEY,
            "secret": SECRET,
            "passphrase": PASSPHRASE,
        },
    )

    assert response.status_code == 422
    for material in (KEY, SECRET, PASSPHRASE):
        assert material not in response.text


def test_the_api_refusals_are_distinct_answers(client, db):
    platform_id = client.post("/api/platforms", json={"name": "OKX", "kind": "exchange"}).json()[
        "id"
    ]
    payload = {
        "platform_id": platform_id,
        "venue": "okx",
        "label": "Main account",
        "key": KEY,
        "secret": SECRET,
        "passphrase": PASSPHRASE,
    }
    assert client.post("/api/connections", json=payload).status_code == 201

    assert client.post("/api/connections", json=payload).status_code == 409
    assert (
        client.post("/api/connections", json={**payload, "platform_id": 12345}).status_code == 404
    )
    assert (
        client.post(
            "/api/connections", json={**payload, "label": "Other", "venue": "mtgox"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/connections", json={**payload, "label": "Other", "passphrase": None}
        ).status_code
        == 422
    )


def test_the_api_removes_a_connection(client, db):
    platform_id = client.post("/api/platforms", json={"name": "OKX", "kind": "exchange"}).json()[
        "id"
    ]
    connection_id = client.post(
        "/api/connections",
        json={
            "platform_id": platform_id,
            "venue": "okx",
            "label": "Main account",
            "key": KEY,
            "secret": SECRET,
            "passphrase": PASSPHRASE,
        },
    ).json()["id"]

    assert client.delete(f"/api/connections/{connection_id}").status_code == 204
    assert client.get("/api/connections").json() == []
    assert client.delete(f"/api/connections/{connection_id}").status_code == 404


def test_every_venue_states_a_read_only_scope(client):
    """The registry tells the UI what to ask each venue for, and every scope
    is explicitly read-only — the application never holds a credential that
    could move funds."""
    venues = client.get("/api/connections/venues").json()

    assert {venue["venue"] for venue in venues} >= {"okx", "coinbase", "trading_212", "bitpanda"}
    for venue in venues:
        assert "read" in venue["required_scope"].lower()
        assert venue["name"]
        assert isinstance(venue["requires_secret"], bool)
        assert isinstance(venue["requires_passphrase"], bool)

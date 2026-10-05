"""The first-run checklist (ticket 58): the walk from an empty database to a
first tax report — set a password, enable two-factor, add Platforms and
Accounts, connect or import, reconcile, resolve blockers, generate a report.
Every item's state is derived from what the database holds; nothing here can
be ticked off or dismissed.

The seam is the HTTP API over real Postgres with fakes of the adapter and
reference-rate ports: each test does what the Admin would do through the API
and reads the checklist back.
"""

import base64
import hashlib
import hmac
import struct
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from open_leprechaun.adapters import get_venue_adapters
from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.ports import exchange as port
from open_leprechaun.rates import get_reference_rate_source
from open_leprechaun.repositories import crypto_prices, instruments, stances, statutory
from open_leprechaun.services.statutory import KEYS

# A year no migration seeds, so whether it is blocked rests on what the test
# itself configured.
BOUGHT_2031 = datetime(2031, 3, 14, 12, 0, tzinfo=UTC)
SOLD_2031 = datetime(2031, 6, 3, 12, 0, tzinfo=UTC)
AS_OF = datetime(2031, 6, 1, 12, 0, tzinfo=UTC)


class FakeReferenceRateSource:
    """The reference-rate port's fake: these ledgers settle in the numéraire,
    so no rate is ever asked for."""

    def daily_rates(self, currency, start, end):
        return []


class FakeAdapter:
    """A fake of the port that states balances: one kind, scripted positions."""

    lookback_days = 90

    def __init__(self, kind, *, positions=(), failure=None):
        self.kind = kind
        self._positions = tuple(positions)
        self.failure = failure

    def test(self, credentials):
        return "Authenticated."

    def pull(self, credentials):
        return port.Harvest()

    def normalized_positions(self, credentials):
        if self.failure is not None:
            raise port.AdapterError(self.failure)
        return self._positions


class SilentAdapter:
    """A kind whose venue states no balances — the port's base shape alone."""

    lookback_days = 90

    def __init__(self, kind):
        self.kind = kind

    def test(self, credentials):
        return "Authenticated."

    def pull(self, credentials):
        return port.Harvest()


@pytest.fixture
def adapters() -> dict:
    """The adapter registry under test control, read per request."""
    return {}


@pytest.fixture
def store(db: Engine) -> Engine:
    """The migrated database before first run: no Admin, and this file's
    statutory year wiped — neither is reset by the shared `db` fixture."""
    with db.begin() as connection:
        # Cascades to admin_session.
        connection.execute(text("DELETE FROM admin_user"))
        connection.execute(text("DELETE FROM statutory_value WHERE year >= 2030"))
    return db


@pytest.fixture
def client(store: Engine, adapters: dict) -> Iterator[TestClient]:
    """The API bound to the migrated test database and the fakes."""
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: store
    app.dependency_overrides[get_venue_adapters] = lambda: adapters
    app.dependency_overrides[get_reference_rate_source] = FakeReferenceRateSource
    with TestClient(app) as client:
        yield client


def checklist(client) -> dict:
    answered = client.get("/api/first-run-checklist")
    assert answered.status_code == 200, answered.text
    return answered.json()


def item(client, key) -> dict:
    return next(item for item in checklist(client)["items"] if item["key"] == key)


def an_account(client, platform="OKX") -> tuple[int, int]:
    """A Platform with one Account. Answers (platform_id, account_id)."""
    platform_id = client.post("/api/platforms", json={"name": platform, "kind": "exchange"})
    platform_id = platform_id.json()["id"]
    account = client.post(f"/api/platforms/{platform_id}/accounts", json={"name": "Trading"})
    return platform_id, account.json()["id"]


def a_connection(client, platform_id, account_id, label="Main account") -> int:
    """A Connection whose spot kind is paired with the Account."""
    connection_id = client.post(
        "/api/connections",
        json=dict(
            platform_id=platform_id,
            venue="okx",
            label=label,
            key="AJVqhlN2mUvg5rlIT4YDkbA1",
            secret="wJmoXjRk8pdFqe37cChM/2Zt5yUwbBHGSA==",
            passphrase="correct horse battery staple",
        ),
    ).json()["id"]
    client.put(f"/api/connections/{connection_id}/pairings/spot", json={"account_id": account_id})
    return connection_id


def position(symbol, quantity):
    return port.NormalizedPosition(symbol=symbol, quantity=Decimal(quantity), as_of=AS_OF)


def reconcile(client, connection_id):
    reconciled = client.post(f"/api/connections/{connection_id}/reconcile")
    assert reconciled.status_code == 200, reconciled.text


def transaction(client, type, occurred_at, *legs):
    created = client.post(
        "/api/transactions",
        json={
            "type": type,
            "occurred_at": occurred_at.isoformat(),
            "legs": [
                dict(account_id=account, instrument_id=instrument, role=role, quantity=quantity)
                for account, instrument, role, quantity in legs
            ],
        },
    )
    assert created.status_code == 201, created.text


def a_round_trip_in_2031(client, db, account_id) -> None:
    """One coin bought and sold within 2031 — activity that gives the year
    something to report, with the Stance and price a report needs."""
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    btc = instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    stances.classify(db, btc, stance="kept", account_id=account_id)
    crypto_prices.store_quote(
        db, instrument_id=btc, price_eur=Decimal("50000"), source="a test", as_of=SOLD_2031
    )
    transaction(
        client,
        "trade",
        BOUGHT_2031,
        (account_id, eur, "out", "10000"),
        (account_id, btc, "in", "1"),
    )
    transaction(
        client,
        "trade",
        SOLD_2031,
        (account_id, btc, "out", "1"),
        (account_id, eur, "in", "12000"),
    )


def statutory_values_for(db, year) -> None:
    """A complete statutory year: every required key set, for a year no
    migration seeds."""
    configured = {
        "private_sale_exemption_limit": "1000",
        "other_income_exemption_limit": "1000",
        "saver_allowance_single": "1000",
        "flat_rate": "0.25",
        "solidarity_surcharge_rate": "0.055",
    }
    for key, definition in KEYS.items():
        if definition.required:
            statutory.upsert_value(
                db,
                year=year,
                key=key,
                value=Decimal(configured.get(key, "0")),
                source="a test value",
            )


# --- The walk itself ---------------------------------------------------------


def test_an_empty_database_lists_the_whole_walk_with_nothing_done(client):
    """Before first run the checklist names every step in the order the
    Admin takes them, none done, each pointing at the screen that does it."""
    answered = checklist(client)

    assert [(item["key"], item["done"], item["resolve_path"]) for item in answered["items"]] == [
        ("password", False, "/setup"),
        ("two_factor", False, "/settings/security"),
        ("platforms_and_accounts", False, "/settings/platforms"),
        ("connect_or_import", False, "/imports"),
        ("reconcile", False, "/settings/connections"),
        ("blockers", False, "/tax/overview"),
        ("report", False, "/tax/overview"),
    ]
    assert answered["complete"] is False
    assert all(item["detail"] for item in answered["items"])


def test_setting_the_password_is_done_once_an_admin_exists(client):
    assert client.post("/api/auth/setup", json={"password": "correct horse battery"}).is_success

    assert item(client, "password")["done"] is True


def test_two_factor_is_optional_and_never_holds_the_walk_back(client):
    """Two-factor is opt-in (ADR-0005): the checklist names it, and says it
    is off, without making it a condition of finishing."""
    two_factor = item(client, "two_factor")

    assert two_factor["optional"] is True
    assert two_factor["done"] is False


def test_two_factor_is_done_once_a_code_has_activated_it(client):
    """Derived from the Admin's row like every other step: enrolling alone is
    not enough, a verifying code is."""
    assert client.post("/api/auth/setup", json={"password": "correct horse battery"}).is_success
    secret = client.post("/api/auth/two-factor/enrollment").json()["secret"]
    assert item(client, "two_factor")["done"] is False

    counter = struct.pack(">Q", int(datetime.now(UTC).timestamp()) // 30)
    mac = hmac.new(base64.b32decode(secret), counter, hashlib.sha1).digest()
    number = struct.unpack(">I", mac[mac[-1] & 0x0F :][:4])[0] & 0x7FFFFFFF
    activated = client.post(
        "/api/auth/two-factor/activation", json={"code": f"{number % 1_000_000:06d}"}
    )

    assert activated.status_code == 204
    assert item(client, "two_factor")["done"] is True


def test_a_platform_alone_is_not_enough_it_takes_an_account(client):
    """Transactions are recorded against Accounts, so a Platform holding
    none leaves the step open — and the checklist says which half is missing."""
    platform_id = client.post("/api/platforms", json={"name": "OKX", "kind": "exchange"})
    platform_id = platform_id.json()["id"]

    without_account = item(client, "platforms_and_accounts")
    client.post(f"/api/platforms/{platform_id}/accounts", json={"name": "Trading"})
    with_account = item(client, "platforms_and_accounts")

    assert without_account["done"] is False
    assert "no Account" in without_account["detail"]
    assert with_account["done"] is True


def test_a_connection_is_a_way_in_for_history(client):
    platform_id, account_id = an_account(client)
    assert item(client, "connect_or_import")["done"] is False

    a_connection(client, platform_id, account_id)

    assert item(client, "connect_or_import")["done"] is True


def test_history_in_the_ledger_counts_however_it_arrived(client, store):
    """An Admin who records Transactions by hand has history without a
    Connection or a file — the step is about the ledger holding something."""
    _, account_id = an_account(client)

    a_round_trip_in_2031(client, store, account_id)

    assert item(client, "connect_or_import")["done"] is True


# --- Reconcile ---------------------------------------------------------------


def test_with_no_connection_there_is_nothing_to_reconcile(client):
    """A ledger fed by imports alone has no venue balance to compare
    against: the step is named, open, and optional."""
    reconcile_item = item(client, "reconcile")

    assert reconcile_item["done"] is False
    assert reconcile_item["optional"] is True


def test_a_connection_whose_venue_states_no_balances_asks_for_no_reconciliation(client, adapters):
    """Nothing can be compared against a venue that states nothing, so such
    a Connection never holds the walk open — and reconciling it anyway does
    not read as the venue and the ledger agreeing."""
    platform_id, account_id = an_account(client)
    connection_id = a_connection(client, platform_id, account_id)
    adapters["okx"] = (SilentAdapter("spot"),)

    reconcile(client, connection_id)
    reconcile_item = item(client, "reconcile")

    assert reconcile_item["done"] is False
    assert reconcile_item["optional"] is True


def test_a_connection_is_unreconciled_until_a_reconciliation_has_run(client, adapters, store):
    """Reconciling is something that happened, not something ticked: the
    step is open, naming the Connection, until its reconciliation ran and
    found the venue and the ledger agreeing."""
    btc = instruments.create_native_coin(store, symbol="BTC", name="Bitcoin", chain="bitcoin")
    platform_id, account_id = an_account(client)
    connection_id = a_connection(client, platform_id, account_id)
    transaction(client, "transfer_in", BOUGHT_2031, (account_id, btc, "in", "1.5"))
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "1.5")]),)

    before = item(client, "reconcile")
    reconcile(client, connection_id)
    after = item(client, "reconcile")

    assert before["done"] is False
    assert before["optional"] is False
    assert "Main account" in before["detail"]
    assert after["done"] is True


def test_a_reconciliation_that_left_a_gap_leaves_the_step_open(client, adapters, store):
    """A gap is reported and never filled, so a reconciliation that found
    one has not finished the step — and closing the gap and reconciling
    again does."""
    btc = instruments.create_native_coin(store, symbol="BTC", name="Bitcoin", chain="bitcoin")
    platform_id, account_id = an_account(client)
    connection_id = a_connection(client, platform_id, account_id)
    transaction(client, "transfer_in", BOUGHT_2031, (account_id, btc, "in", "0.6"))
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "1.5")]),)

    reconcile(client, connection_id)
    with_gap = item(client, "reconcile")
    transaction(client, "transfer_in", BOUGHT_2031, (account_id, btc, "in", "0.9"))
    reconcile(client, connection_id)
    closed = item(client, "reconcile")

    assert with_gap["done"] is False
    assert "Main account" in with_gap["detail"]
    assert closed["done"] is True


def test_a_reconciliation_the_venue_refused_leaves_the_step_open(client, adapters):
    """A kind that could not be compared compared nothing — that is not the
    venue and the ledger agreeing."""
    platform_id, account_id = an_account(client)
    connection_id = a_connection(client, platform_id, account_id)
    adapters["okx"] = (FakeAdapter("spot", failure="The venue refused the key."),)

    reconcile(client, connection_id)

    assert item(client, "reconcile")["done"] is False


def test_every_connection_has_to_be_reconciled(client, adapters):
    platform_id, account_id = an_account(client)
    first = a_connection(client, platform_id, account_id)
    a_connection(client, platform_id, account_id, label="Second account")
    adapters["okx"] = (FakeAdapter("spot"),)

    reconcile(client, first)
    reconcile_item = item(client, "reconcile")

    assert reconcile_item["done"] is False
    assert "Second account" in reconcile_item["detail"]
    assert "Main account" not in reconcile_item["detail"]


# --- Blockers and the report -------------------------------------------------


def test_blockers_are_judged_only_once_a_tax_year_has_activity(client):
    """An empty ledger has no blockers — and nothing to report either, so
    their absence is not the step being done."""
    assert item(client, "blockers")["done"] is False


def test_a_blocked_tax_year_keeps_the_step_open_until_the_blocker_is_resolved(client, store):
    """2031 has activity but no statutory values: pre-flight names that, and
    the checklist stays open, naming the year, until they are configured."""
    _, account_id = an_account(client)
    a_round_trip_in_2031(client, store, account_id)

    blocked = item(client, "blockers")
    statutory_values_for(store, 2031)
    resolved = item(client, "blockers")

    assert blocked["done"] is False
    assert "2031" in blocked["detail"]
    assert resolved["done"] is True
    assert "2031" in resolved["detail"]


def test_generating_a_report_finishes_the_walk(client, adapters, store):
    """The whole walk, as the Admin takes it: once a report exists and every
    step before it holds, the checklist is complete — two-factor still off."""
    client.post("/api/auth/setup", json={"password": "correct horse battery"})
    platform_id, account_id = an_account(client)
    connection_id = a_connection(client, platform_id, account_id)
    a_round_trip_in_2031(client, store, account_id)
    statutory_values_for(store, 2031)
    adapters["okx"] = (FakeAdapter("spot", positions=[position("EUR", "2000")]),)
    reconcile(client, connection_id)
    before = checklist(client)

    assert client.post("/api/reports", json={"year": 2031}).status_code == 201
    after = checklist(client)

    assert [item["key"] for item in before["items"] if not item["done"]] == ["two_factor", "report"]
    assert before["complete"] is False
    assert [item["key"] for item in after["items"] if not item["done"]] == ["two_factor"]
    assert after["complete"] is True


def test_nothing_done_is_sticky_removing_the_thing_reopens_its_step(client):
    """Derived, not remembered: a step is done because what it asks for
    exists, and open again the moment it no longer does."""
    platform_id, account_id = an_account(client)
    connection_id = a_connection(client, platform_id, account_id)
    assert item(client, "connect_or_import")["done"] is True

    assert client.delete(f"/api/connections/{connection_id}").is_success

    assert item(client, "connect_or_import")["done"] is False


def test_removing_the_last_account_reopens_adding_platforms_and_accounts(client):
    _, account_id = an_account(client)
    assert item(client, "platforms_and_accounts")["done"] is True

    assert client.delete(f"/api/accounts/{account_id}").is_success

    assert item(client, "platforms_and_accounts")["done"] is False


def test_production_keeps_the_checklist_behind_authentication(make_client):
    assert make_client("production").get("/api/first-run-checklist").status_code == 401

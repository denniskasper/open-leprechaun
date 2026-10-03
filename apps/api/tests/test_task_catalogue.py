"""The scheduled tasks the application ships (ticket 42): price updates and
Connection syncs, each answering one sentence about its run and failing in
words the Admin can act on.

The seam is the HTTP API over real Postgres with the real catalogue, bound —
through the same dependencies production serves — to fakes of the price and
adapter ports. No live provider or venue is ever called.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from open_leprechaun.adapters import get_exchange_adapters
from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.market_data import get_security_prices
from open_leprechaun.ports import exchange as port
from open_leprechaun.ports.crypto_prices import ProviderOutageError, Quote, RateLimitedError
from open_leprechaun.prices import get_crypto_price_chain
from open_leprechaun.rates import get_reference_rate_source
from open_leprechaun.repositories import instruments

QUOTED_AT = datetime(2026, 8, 7, 14, 30, tzinfo=UTC)


class FakeCryptoProvider:
    def __init__(self, name, eur_by_symbol=None, fails_with=None):
        self.name = name
        self.eur_by_symbol = eur_by_symbol or {}
        self.fails_with = fails_with

    def quotes(self, priceable):
        if self.fails_with is not None:
            raise self.fails_with
        return [
            Quote(
                instrument_id=instrument.id,
                price=self.eur_by_symbol[instrument.symbol],
                currency="EUR",
                as_of=QUOTED_AT,
            )
            for instrument in priceable
            if instrument.symbol in self.eur_by_symbol
        ]


class NoSecurityQuotes:
    name = "fake"

    def quotes(self, listings):
        return []


class NoRates:
    def daily_rates(self, currency, start, end):
        return []


class FakeAdapter:
    def __init__(self, kind, *, failure=None):
        self.kind = kind
        self.failure = failure
        self.lookback_days = 90

    def pull(self, credentials):
        if self.failure is not None:
            raise port.AdapterError(self.failure)
        return port.Harvest()


@pytest.fixture
def ports() -> dict:
    """The fakes behind the catalogue — read per request, so a test's later
    edits take effect."""
    return {"chain": (), "security": NoSecurityQuotes, "adapters": {}}


@pytest.fixture
def client(db: Engine, ports: dict) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_crypto_price_chain] = lambda: ports["chain"]
    app.dependency_overrides[get_security_prices] = lambda: ports["security"]()
    app.dependency_overrides[get_reference_rate_source] = NoRates
    app.dependency_overrides[get_exchange_adapters] = lambda: ports["adapters"]
    with TestClient(app) as client:
        yield client


def run(client: TestClient, key: str) -> dict:
    response = client.post(f"/api/scheduled-tasks/{key}/run")
    assert response.status_code == 200
    return response.json()


def coins(db: Engine) -> None:
    instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    instruments.create_native_coin(db, symbol="ETH", name="Ether", chain="ethereum")


def test_price_updates_and_syncs_are_the_tasks_on_offer(client):
    tasks = client.get("/api/scheduled-tasks").json()

    assert [task["key"] for task in tasks] == [
        "crypto_prices",
        "security_prices",
        "connection_sync",
    ]
    assert all(task["enabled"] for task in tasks)


def test_a_crypto_price_update_says_how_many_instruments_it_priced(client, db, ports):
    coins(db)
    ports["chain"] = (FakeCryptoProvider("coingecko", {"BTC": Decimal("50000")}),)

    ran = run(client, "crypto_prices")

    assert (ran["outcome"], ran["detail"]) == ("ok", "1 fresh, 0 stale, 1 unpriced.")
    # The run stored what it priced: with every provider gone the next
    # update serves that price stale.
    ports["chain"] = ()
    assert run(client, "crypto_prices")["detail"] == "0 fresh, 1 stale, 1 unpriced."


def test_a_provider_failure_that_left_instruments_unpriced_fails_the_update(client, db, ports):
    coins(db)
    ports["chain"] = (
        FakeCryptoProvider("coingecko", fails_with=RateLimitedError()),
        FakeCryptoProvider("defillama", fails_with=ProviderOutageError()),
    )

    ran = run(client, "crypto_prices")

    assert ran["outcome"] == "failed"
    assert ran["error"] == (
        "coingecko is rate-limiting; defillama is not answering — 0 fresh, 0 stale, 2 unpriced."
    )


def test_a_provider_failure_the_chain_covered_for_is_no_failure(client, db, ports):
    coins(db)
    ports["chain"] = (
        FakeCryptoProvider("coingecko", fails_with=ProviderOutageError()),
        FakeCryptoProvider("defillama", {"BTC": Decimal("50000"), "ETH": Decimal("2000")}),
    )

    ran = run(client, "crypto_prices")

    assert (ran["outcome"], ran["detail"]) == ("ok", "2 fresh, 0 stale, 0 unpriced.")


def test_a_security_price_update_with_nothing_to_price_succeeds(client):
    ran = run(client, "security_prices")

    assert (ran["outcome"], ran["detail"]) == ("ok", "0 fresh, 0 stale, 0 unpriced.")


def test_an_unknown_security_provider_fails_its_own_task_and_no_other(client, ports):
    def misconfigured():
        raise ValueError("No market-data provider named 'nope' — one of: onvista.")

    ports["security"] = misconfigured

    assert client.get("/api/scheduled-tasks").status_code == 200
    ran = run(client, "security_prices")
    assert ran["outcome"] == "failed"
    assert ran["error"] == "No market-data provider named 'nope' — one of: onvista."
    assert run(client, "crypto_prices")["outcome"] == "ok"


def connection(client: TestClient, label: str) -> int:
    platform_id = client.post("/api/platforms", json={"name": label, "kind": "exchange"}).json()[
        "id"
    ]
    account_id = client.post(f"/api/platforms/{platform_id}/accounts", json={"name": "Trading"})
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
    for kind in ("spot", "futures"):
        paired = client.put(
            f"/api/connections/{connection_id}/pairings/{kind}",
            json={"account_id": account_id.json()["id"]},
        )
        assert paired.status_code < 300
    return connection_id


def test_a_sync_with_no_connections_succeeds(client):
    ran = run(client, "connection_sync")

    assert (ran["outcome"], ran["detail"]) == ("ok", "0 adapter kinds synced across 0 Connections.")


def test_the_sync_task_syncs_every_connection(client, ports):
    ports["adapters"]["okx"] = (FakeAdapter("spot"), FakeAdapter("futures"))
    connection(client, "Main")
    connection(client, "Second")

    ran = run(client, "connection_sync")

    assert (ran["outcome"], ran["detail"]) == ("ok", "4 adapter kinds synced across 2 Connections.")
    for listed in client.get("/api/connections").json():
        assert [status["last_success_at"] is not None for status in listed["statuses"]] == [
            True,
            True,
        ]


def test_one_kind_failing_fails_the_sync_task_naming_the_connection_and_kind(client, ports):
    ports["adapters"]["okx"] = (
        FakeAdapter("spot"),
        FakeAdapter("futures", failure="The venue is down."),
    )
    connection(client, "Main")

    ran = run(client, "connection_sync")

    assert ran["outcome"] == "failed"
    assert ran["error"] == "Main (futures): The venue is down."
    # The kind that worked still landed (ADR-0004).
    (listed,) = client.get("/api/connections").json()
    recorded = {status["adapter_kind"]: status for status in listed["statuses"]}
    assert recorded["spot"]["last_success_at"] is not None


def test_a_connection_that_cannot_be_synced_is_named_and_the_next_still_syncs(client, db, ports):
    from sqlalchemy import text

    ports["adapters"]["okx"] = (FakeAdapter("spot"), FakeAdapter("futures"))
    sealed = connection(client, "Sealed")
    connection(client, "Working")
    with db.begin() as connecting:
        connecting.execute(
            text("UPDATE connection SET credentials_ciphertext = :junk WHERE id = :id"),
            {"junk": b"not a ciphertext", "id": sealed},
        )

    ran = run(client, "connection_sync")

    assert ran["outcome"] == "failed"
    assert ran["error"].startswith("Sealed: ")
    assert "Working" not in ran["error"]
    working = next(c for c in client.get("/api/connections").json() if c["label"] == "Working")
    assert all(status["last_success_at"] is not None for status in working["statuses"])

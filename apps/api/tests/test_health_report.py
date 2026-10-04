"""The health panel's report (ticket 55): whether the numbers on every other
page are fresh — per data provider, per Connection, per scheduled task, and
what the store holds — and, when something is wrong, exactly what.

The seam is the HTTP API over real Postgres, with fakes of the provider ports
and tasks the test controls bound through the same dependencies production
serves. A provider's state is never set by hand: it is whatever the pricing
and conversion services recorded while asking the fake.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.market_data import get_security_prices
from open_leprechaun.ports.crypto_prices import (
    DailyClose,
    ProviderOutageError,
    Quote,
    RateLimitedError,
)
from open_leprechaun.ports.reference_rates import ReferenceRate
from open_leprechaun.ports.security_prices import ListingQuote
from open_leprechaun.prices import get_crypto_price_chain
from open_leprechaun.rates import get_reference_rate_source
from open_leprechaun.repositories import connections as connections_repository
from open_leprechaun.repositories import crypto_prices as stored_prices
from open_leprechaun.repositories import instruments
from open_leprechaun.services import crypto_prices, fx, security_prices
from open_leprechaun.services.scheduled_tasks import Task, TaskFailedError
from open_leprechaun.settings import Environment
from open_leprechaun.tasks import get_scheduled_tasks

QUOTED_AT = datetime(2026, 10, 2, 14, 30, tzinfo=UTC)


class FakeCryptoPrices:
    """The crypto price port's fake: answers for the symbols it was given,
    or fails the way the test chooses."""

    def __init__(self, name, symbols=(), fails_with=None, closes=()):
        self.name = name
        self.symbols = set(symbols)
        self.fails_with = fails_with
        self.closes = list(closes)

    def quotes(self, instruments):
        if self.fails_with is not None:
            raise self.fails_with
        return [
            Quote(instrument_id=row.id, price=Decimal("100"), currency="EUR", as_of=QUOTED_AT)
            for row in instruments
            if row.symbol in self.symbols
        ]

    def daily_closes(self, instrument, start, end):
        if self.fails_with is not None:
            raise self.fails_with
        return self.closes if instrument.symbol in self.symbols else []


class FakeSecurityPrices:
    def __init__(self, name="onvista", isins=(), fails_with=None):
        self.name = name
        self.isins = set(isins)
        self.fails_with = fails_with

    def quotes(self, listings):
        if self.fails_with is not None:
            raise self.fails_with
        return [
            ListingQuote(
                instrument_id=listing.instrument_id,
                price=Decimal("250"),
                currency="EUR",
                venue=listing.venue,
                as_of=QUOTED_AT,
            )
            for listing in listings
            if listing.isin in self.isins
        ]

    def daily_closes(self, listing, start, end):
        return []


class FakeReferenceRates:
    def __init__(self, rates=(), fails_with=None):
        self.rates = list(rates)
        self.fails_with = fails_with

    def daily_rates(self, currency, start, end):
        if self.fails_with is not None:
            raise self.fails_with
        return [
            rate
            for rate in self.rates
            if rate.currency == currency and start <= rate.rate_date <= end
        ]


class Instance:
    """What one test's API is bound to — edited in place, read per request."""

    def __init__(self):
        self.chain = [FakeCryptoPrices("coingecko"), FakeCryptoPrices("defillama")]
        self.securities = FakeSecurityPrices()
        self.rates = FakeReferenceRates()
        self.tasks: tuple[Task, ...] = ()


@pytest.fixture
def instance() -> Instance:
    return Instance()


@pytest.fixture
def client(db: Engine, instance: Instance) -> Iterator[TestClient]:
    with db.begin() as connection:
        connection.execute(text("DELETE FROM reference_rate"))
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_crypto_price_chain] = lambda: instance.chain
    app.dependency_overrides[get_security_prices] = lambda: instance.securities
    app.dependency_overrides[get_reference_rate_source] = lambda: instance.rates
    app.dependency_overrides[get_scheduled_tasks] = lambda: instance.tasks
    with TestClient(app) as client:
        yield client


def report(client: TestClient) -> dict:
    response = client.get("/api/health/report")
    assert response.status_code == 200
    return response.json()


def provider(client: TestClient, name: str) -> dict:
    return next(entry for entry in report(client)["providers"] if entry["name"] == name)


def coin(engine: Engine, symbol: str, name: str) -> int:
    return instruments.create_native_coin(engine, symbol=symbol, name=name, chain=name.lower())


def _priceable(engine: Engine) -> list:
    return stored_prices.priceable_instruments(engine)


def share(engine: Engine) -> int:
    return instruments.create_security(
        engine,
        symbol="ALV",
        name="Allianz",
        type="share",
        isin="DE0008404005",
        venue="Xetra",
        quote_currency="EUR",
    )


# --- Data providers ----------------------------------------------------------


def test_every_configured_provider_is_listed_before_anything_has_asked_it(client):
    """The roster is what this instance is configured with, in the order it
    asks — a provider nothing has called yet says so instead of being absent."""
    providers = report(client)["providers"]

    assert [(entry["name"], entry["feeds"]) for entry in providers] == [
        ("coingecko", "crypto_prices"),
        ("defillama", "crypto_prices"),
        ("onvista", "security_prices"),
        ("ecb", "reference_rates"),
    ]
    assert {entry["state"] for entry in providers} == {"never_asked"}
    assert providers[0]["last_success_at"] is None
    assert providers[0]["last_error_at"] is None
    assert providers[0]["affected_instruments"] == []


def test_a_provider_that_answered_states_when(client, db, instance):
    coin(db, "BTC", "Bitcoin")
    instance.chain[0].symbols = {"BTC"}

    crypto_prices.refresh_prices(db, instance.chain, instance.rates)

    coingecko = provider(client, "coingecko")
    assert coingecko["state"] == "ok"
    assert coingecko["last_success_at"] is not None
    assert coingecko["last_error"] is None
    # The chain stopped at the provider that answered for everything.
    assert provider(client, "defillama")["state"] == "never_asked"


def test_one_failing_provider_is_named_with_the_instruments_it_affects(client, db, instance):
    """CoinGecko answers for BTC; DefiLlama, the only one that knows KAS, is
    down. That is DefiLlama's outage and KAS's staleness — nothing else's."""
    coin(db, "BTC", "Bitcoin")
    kas_id = coin(db, "KAS", "Kaspa")
    instance.chain[0].symbols = {"BTC"}
    instance.chain[1].fails_with = ProviderOutageError("defillama answered HTTP 502.")

    crypto_prices.refresh_prices(db, instance.chain, instance.rates)

    defillama = provider(client, "defillama")
    assert defillama["state"] == "outage"
    assert defillama["last_error"] == "defillama answered HTTP 502."
    assert defillama["last_error_at"] is not None
    assert defillama["affected_instruments"] == [{"id": kas_id, "symbol": "KAS", "name": "Kaspa"}]
    coingecko = provider(client, "coingecko")
    assert coingecko["state"] == "ok"
    assert coingecko["affected_instruments"] == []


def test_a_rate_limit_is_its_own_state_never_an_outage(client, db, instance):
    btc_id = coin(db, "BTC", "Bitcoin")
    instance.chain[0].fails_with = RateLimitedError("coingecko asked for a pause (HTTP 429).")

    crypto_prices.refresh_prices(db, instance.chain, instance.rates)

    coingecko = provider(client, "coingecko")
    assert coingecko["state"] == "rate_limited"
    assert coingecko["last_error"] == "coingecko asked for a pause (HTTP 429)."
    assert [entry["id"] for entry in coingecko["affected_instruments"]] == [btc_id]
    # The fallback was asked, knew nothing, and is not blamed for it.
    assert provider(client, "defillama")["state"] == "ok"


def test_a_provider_another_answered_for_affects_nothing(client, db, instance):
    """CoinGecko is down but DefiLlama priced everything: a failing provider,
    and not one stale figure to show for it."""
    coin(db, "BTC", "Bitcoin")
    instance.chain[0].fails_with = ProviderOutageError("coingecko is unreachable.")
    instance.chain[1].symbols = {"BTC"}

    crypto_prices.refresh_prices(db, instance.chain, instance.rates)

    coingecko = provider(client, "coingecko")
    assert coingecko["state"] == "outage"
    assert coingecko["affected_instruments"] == []


def test_a_provider_answering_again_is_ok_and_keeps_its_last_error(client, db, instance):
    coin(db, "BTC", "Bitcoin")
    instance.chain[0].fails_with = ProviderOutageError("coingecko is unreachable.")
    crypto_prices.refresh_prices(db, instance.chain, instance.rates)

    instance.chain[0].fails_with = None
    instance.chain[0].symbols = {"BTC"}
    crypto_prices.refresh_prices(db, instance.chain, instance.rates)

    coingecko = provider(client, "coingecko")
    assert coingecko["state"] == "ok"
    assert coingecko["affected_instruments"] == []
    assert coingecko["last_error"] == "coingecko is unreachable."
    assert coingecko["last_success_at"] > coingecko["last_error_at"]


def test_a_fallback_no_longer_needed_stops_affecting_anything(client, db, instance):
    """DefiLlama failed while KAS depended on it; then CoinGecko learned KAS
    and the chain never reached DefiLlama again. Its last call still failed —
    but nothing is stale because of it."""
    coin(db, "KAS", "Kaspa")
    instance.chain[1].fails_with = ProviderOutageError("defillama answered HTTP 502.")
    crypto_prices.refresh_prices(db, instance.chain, instance.rates)
    assert len(provider(client, "defillama")["affected_instruments"]) == 1

    instance.chain[0].symbols = {"KAS"}
    crypto_prices.refresh_prices(db, instance.chain, instance.rates)

    defillama = provider(client, "defillama")
    assert defillama["state"] == "outage"
    assert defillama["affected_instruments"] == []


def test_a_failure_the_port_did_not_name_is_recorded_by_its_type_alone(client, db, instance):
    """A stray exception's message promises nothing about what it carries
    (ADR-0003). Historical resolution swallows it and asks on; once enough
    Instruments in a row failed to say it is the provider, only the type is
    kept."""
    symbols = {"BTC": "Bitcoin", "ETH": "Ethereum", "KAS": "Kaspa"}
    assert len(symbols) == crypto_prices.OUTAGE_PATIENCE
    for symbol, name in symbols.items():
        coin(db, symbol, name)
    instance.chain = [
        FakeCryptoPrices("coingecko", symbols, fails_with=KeyError("secret-looking-thing"))
    ]

    crypto_prices.resolve_daily_closes(
        db, instance.chain, instance.rates, [(row, [date(2026, 9, 1)]) for row in _priceable(db)]
    )

    coingecko = provider(client, "coingecko")
    assert coingecko["state"] == "outage"
    assert coingecko["last_error"] == "coingecko failed with KeyError."


def test_one_instruments_missing_history_does_not_call_the_provider_down(client, db, instance):
    """An unknown contract answers a history request like an outage; one such
    failure is that Instrument's, not the provider's."""
    coin(db, "BTC", "Bitcoin")
    instance.chain = [
        FakeCryptoPrices("coingecko", {"BTC"}, fails_with=ProviderOutageError("HTTP 404."))
    ]

    crypto_prices.resolve_daily_closes(
        db, instance.chain, instance.rates, [(row, [date(2026, 9, 1)]) for row in _priceable(db)]
    )

    assert provider(client, "coingecko")["state"] == "never_asked"


def test_the_security_provider_failing_names_the_securities_it_prices(client, db, instance):
    """A security that names no price source was never the provider's to
    answer — only the one it was asked for is affected."""
    share_id = share(db)
    instruments.create_security(
        db,
        symbol="SAP",
        name="SAP",
        type="share",
        isin="DE0007164600",
        venue=None,
        quote_currency=None,
    )
    instance.securities.fails_with = ProviderOutageError("onvista answered HTTP 503.")

    security_prices.refresh_prices(db, instance.securities, instance.rates)

    onvista = provider(client, "onvista")
    assert onvista["state"] == "outage"
    assert [entry["id"] for entry in onvista["affected_instruments"]] == [share_id]
    # The crypto providers are no part of this.
    assert provider(client, "coingecko")["state"] == "never_asked"


def test_the_reference_rate_source_records_its_fetches(client, db, instance):
    at = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    instance.rates.fails_with = httpx.ConnectError("no route to host")
    with pytest.raises(httpx.ConnectError):
        fx.convert(db, instance.rates, amount=Decimal("10"), currency="USD", at=at)

    ecb = provider(client, "ecb")
    assert ecb["state"] == "outage"
    assert ecb["last_error"] == "ecb failed with ConnectError."
    assert ecb["affected_instruments"] == []

    instance.rates.fails_with = None
    instance.rates.rates = [ReferenceRate("USD", date(2026, 9, 15), Decimal("1.10"))]
    fx.convert(db, instance.rates, amount=Decimal("10"), currency="USD", at=at)

    assert provider(client, "ecb")["state"] == "ok"


def test_a_misconfigured_security_provider_is_left_out_not_fatal(client, instance):
    def misconfigured():
        raise ValueError("No market-data provider named 'nope' — one of: onvista.")

    client.app.dependency_overrides[get_security_prices] = misconfigured

    assert [entry["name"] for entry in report(client)["providers"]] == [
        "coingecko",
        "defillama",
        "ecb",
    ]


# --- Connections --------------------------------------------------------------


def connection(client: TestClient, label: str = "Main account") -> int:
    platform_id = client.post("/api/platforms", json={"name": label, "kind": "exchange"}).json()[
        "id"
    ]
    return client.post(
        "/api/connections",
        json={
            "platform_id": platform_id,
            "venue": "okx",
            "label": label,
            "key": "AJVqhlN2mUvg5rlIT4YDkbA1",
            "secret": "wJmoXjRk8pdFqe37cChM/2Zt5yUwbBHGSA==",
            "passphrase": "correct horse battery staple",
        },
    ).json()["id"]


def test_a_connection_never_synced_says_so(client):
    connection_id = connection(client)

    assert report(client)["connections"] == [
        {
            "id": connection_id,
            "label": "Main account",
            "venue": "okx",
            "last_sync_at": None,
            "kinds": [],
        }
    ]


def test_each_kind_states_its_own_result_and_one_failing_does_not_hide_another(client, db):
    connection_id = connection(client)
    synced = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
    failed = datetime(2026, 10, 2, 6, 0, tzinfo=UTC)
    for at in (synced, failed):
        connections_repository.record_result(db, connection_id, "spot", error=None, at=at)
    connections_repository.record_result(db, connection_id, "futures", error=None, at=synced)
    connections_repository.record_result(
        db, connection_id, "futures", error="The venue refused the key.", at=failed
    )

    (listed,) = report(client)["connections"]

    assert listed["last_sync_at"] == "2026-10-02T06:00:00Z"
    kinds = {kind["adapter_kind"]: kind for kind in listed["kinds"]}
    assert kinds["spot"]["ok"] is True
    assert kinds["spot"]["last_success_at"] == "2026-10-02T06:00:00Z"
    assert kinds["futures"]["ok"] is False
    assert kinds["futures"]["last_error"] == "The venue refused the key."
    assert kinds["futures"]["last_error_at"] == "2026-10-02T06:00:00Z"
    # The failure kept the last success beside it.
    assert kinds["futures"]["last_success_at"] == "2026-10-01T06:00:00Z"


# --- Scheduled tasks ----------------------------------------------------------


def _failing() -> str:
    raise TaskFailedError("coingecko is not answering — 0 fresh, 1 stale, 0 unpriced.")


def test_each_task_states_its_last_run_and_when_it_is_next_due(client, instance):
    instance.tasks = (
        Task("prices", "Price update", "Prices.", "*/15 * * * *", run=_failing),
        Task("sync", "Sync", "Pulls.", "0 3 * * *", run=lambda: "Nothing new."),
        Task("idle", "Idle", "Rests.", "0 3 * * *", run=lambda: "", default_enabled=False),
    )
    client.post("/api/scheduled-tasks/prices/run")
    client.post("/api/scheduled-tasks/sync/run")

    tasks = {task["key"]: task for task in report(client)["tasks"]}

    assert tasks["prices"]["outcome"] == "failed"
    assert tasks["prices"]["error"].startswith("coingecko is not answering")
    assert tasks["prices"]["last_finished_at"] is not None
    assert tasks["prices"]["next_due_at"] is not None
    assert tasks["sync"]["outcome"] == "ok"
    assert tasks["sync"]["error"] is None
    assert tasks["idle"]["outcome"] is None
    assert tasks["idle"]["enabled"] is False
    assert tasks["idle"]["next_due_at"] is None


def test_the_report_says_whether_this_instance_answers_schedules(client, db, make_client):
    assert report(client)["scheduler_enabled"] is True

    unscheduled = make_client(Environment.development, db, scheduler_enabled=False)

    assert unscheduled.get("/api/health/report").json()["scheduler_enabled"] is False


# --- Storage ------------------------------------------------------------------


def test_storage_states_the_database_size_and_the_price_history_held(client, db, instance):
    coin(db, "BTC", "Bitcoin")
    instance.chain[0].symbols = {"BTC"}
    instance.chain[0].closes = [
        DailyClose(date(2026, 9, 1), Decimal("50000"), "EUR"),
        DailyClose(date(2026, 9, 2), Decimal("51000"), "EUR"),
    ]
    wanted = [(row, [date(2026, 9, 1), date(2026, 9, 2)]) for row in _priceable(db)]
    crypto_prices.resolve_daily_closes(db, instance.chain, instance.rates, wanted)
    # One published rate and the checked absence of a weekend day: only the
    # publication is price history.
    instance.rates.rates = [ReferenceRate("USD", date(2026, 9, 18), Decimal("1.10"))]
    fx.convert(
        db,
        instance.rates,
        amount=Decimal("10"),
        currency="USD",
        at=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
    )

    storage = report(client)["storage"]

    assert storage["crypto_daily_closes"] == 2
    assert storage["security_daily_closes"] == 0
    assert storage["reference_rates"] == 1
    assert storage["database_bytes"] > 0


# --- Who may read it ----------------------------------------------------------


def test_the_report_is_the_admins_alone_in_production(db, make_client):
    production = make_client(Environment.production, db)

    assert production.get("/api/health/report").status_code == 401
    # The readiness probe stays public.
    assert production.get("/api/health").status_code == 200


def test_a_lone_backfill_failure_is_the_instruments_but_a_rate_limit_is_the_providers(
    client, db, instance
):
    btc_id = coin(db, "BTC", "Bitcoin")
    span = dict(instrument_id=btc_id, start=date(2026, 9, 1), end=date(2026, 9, 2))
    instance.chain = [FakeCryptoPrices("coingecko", {"BTC"}, fails_with=ProviderOutageError())]

    crypto_prices.backfill_daily_closes(db, instance.chain, instance.rates, **span)
    assert provider(client, "coingecko")["state"] == "never_asked"

    instance.chain[0].fails_with = RateLimitedError("coingecko asked for a pause (HTTP 429).")
    crypto_prices.backfill_daily_closes(db, instance.chain, instance.rates, **span)
    assert provider(client, "coingecko")["state"] == "rate_limited"


def test_what_an_earlier_failure_affected_does_not_come_back_with_a_later_one(client, db, instance):
    """A refresh failed and named BTC; the provider then answered; a later
    rate-limited backfill is a new failure, and says nothing about BTC."""
    btc_id = coin(db, "BTC", "Bitcoin")
    instance.chain = [FakeCryptoPrices("coingecko", {"BTC"}, fails_with=ProviderOutageError())]
    crypto_prices.refresh_prices(db, instance.chain, instance.rates)
    instance.chain[0].fails_with = None
    crypto_prices.backfill_daily_closes(
        db,
        instance.chain,
        instance.rates,
        instrument_id=btc_id,
        start=date(2026, 9, 1),
        end=date(2026, 9, 2),
    )

    instance.chain[0].fails_with = RateLimitedError()
    crypto_prices.backfill_daily_closes(
        db,
        instance.chain,
        instance.rates,
        instrument_id=btc_id,
        start=date(2026, 9, 1),
        end=date(2026, 9, 2),
    )

    coingecko = provider(client, "coingecko")
    assert coingecko["state"] == "rate_limited"
    assert coingecko["affected_instruments"] == []

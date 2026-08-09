"""Crypto prices with a fallback chain (ticket 18): every crypto Instrument
gets a price from some provider in a documented chain, and when they all fail
the stored last-known price is served clearly labelled stale — never a blank
or a zero.

The seams are the schema over real Postgres, the repository over the stored
prices, the pricing service driven through fakes of the provider port, and
the CoinGecko and DefiLlama implementations against recorded responses.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from open_leprechaun.ports.crypto_prices import (
    DailyClose,
    ProviderOutageError,
    Quote,
    RateLimitedError,
)
from open_leprechaun.ports.reference_rates import ReferenceRate
from open_leprechaun.repositories import crypto_prices as stored_prices
from open_leprechaun.repositories import instruments
from open_leprechaun.services import crypto_prices

QUOTED_AT = datetime(2026, 8, 7, 14, 30, tzinfo=UTC)


class FakeCryptoPriceProvider:
    """The port's fake: quotes and closes keyed by symbol, or a failure the
    test chooses — which is how the chain's fallthrough and its named
    conditions are proven."""

    def __init__(self, name, quotes_by_symbol=None, closes_by_symbol=None, fails_with=None):
        self.name = name
        self.quotes_by_symbol = quotes_by_symbol or {}
        self.closes_by_symbol = closes_by_symbol or {}
        self.fails_with = fails_with

    def quotes(self, instruments):
        if self.fails_with is not None:
            raise self.fails_with
        return [
            Quote(
                instrument_id=instrument.id,
                price=self.quotes_by_symbol[instrument.symbol][0],
                currency=self.quotes_by_symbol[instrument.symbol][1],
                as_of=QUOTED_AT,
            )
            for instrument in instruments
            if instrument.symbol in self.quotes_by_symbol
        ]

    def daily_closes(self, instrument, start, end):
        if self.fails_with is not None:
            raise self.fails_with
        return [
            close
            for close in self.closes_by_symbol.get(instrument.symbol, [])
            if start <= close.close_date <= end
        ]


class FakeReferenceRateSource:
    def __init__(self, rates=()):
        self.rates = list(rates)

    def daily_rates(self, currency, start, end):
        return [
            rate
            for rate in self.rates
            if rate.currency == currency and start <= rate.rate_date <= end
        ]


@pytest.fixture
def priced_db(db):
    """The migrated database with no stored rates — a checked absence left by
    another test must not decide a conversion here."""
    with db.begin() as connection:
        connection.execute(text("DELETE FROM reference_rate"))
    return db


def _btc(engine) -> int:
    return instruments.create_native_coin(engine, symbol="BTC", name="Bitcoin", chain="bitcoin")


def _insert_price(engine, instrument_id, *, price_eur=Decimal("50000"), source="coingecko"):
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO crypto_price (instrument_id, price_eur, source, as_of)"
                " VALUES (:instrument_id, :price_eur, :source, :as_of)"
            ),
            {
                "instrument_id": instrument_id,
                "price_eur": price_eur,
                "source": source,
                "as_of": datetime(2026, 8, 7, 12, 0, tzinfo=UTC),
            },
        )


def _insert_close(engine, instrument_id, *, close_date="2026-08-07", price_eur=Decimal("50000")):
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO crypto_daily_close (instrument_id, close_date, price_eur, source)"
                " VALUES (:instrument_id, :close_date, :price_eur, 'coingecko')"
            ),
            {
                "instrument_id": instrument_id,
                "close_date": close_date,
                "price_eur": price_eur,
            },
        )


# --- The schema is the arbiter ----------------------------------------------


def test_the_schema_holds_one_last_known_price_per_instrument(priced_db):
    instrument_id = _btc(priced_db)
    _insert_price(priced_db, instrument_id)
    with pytest.raises(IntegrityError):
        _insert_price(priced_db, instrument_id, price_eur=Decimal("60000"))


def test_the_schema_refuses_a_non_positive_price(priced_db):
    with pytest.raises(IntegrityError):
        _insert_price(priced_db, _btc(priced_db), price_eur=Decimal("0"))


def test_the_schema_refuses_a_price_for_no_instrument(priced_db):
    with pytest.raises(IntegrityError):
        _insert_price(priced_db, 424242)


def test_the_schema_holds_one_close_per_instrument_and_date(priced_db):
    instrument_id = _btc(priced_db)
    _insert_close(priced_db, instrument_id)
    with pytest.raises(IntegrityError):
        _insert_close(priced_db, instrument_id, price_eur=Decimal("60000"))


def test_the_schema_refuses_a_non_positive_close(priced_db):
    with pytest.raises(IntegrityError):
        _insert_close(priced_db, _btc(priced_db), price_eur=Decimal("-1"))


# --- The chain prices, and what it learns is stored --------------------------


def test_a_fresh_quote_is_served_and_stored_with_its_source_and_timestamp(priced_db):
    instrument_id = _btc(priced_db)
    provider = FakeCryptoPriceProvider("coingecko", {"BTC": (Decimal("50000"), "EUR")})

    report = crypto_prices.refresh_prices(priced_db, [provider], FakeReferenceRateSource())

    (entry,) = report.prices
    assert entry.instrument_id == instrument_id
    assert entry.status == "fresh"
    assert entry.price_eur == Decimal("50000")
    assert entry.source == "coingecko"
    assert entry.as_of == QUOTED_AT

    stored = stored_prices.last_known(priced_db, instrument_id)
    assert stored.price_eur == Decimal("50000")
    assert stored.source == "coingecko"
    assert stored.as_of == QUOTED_AT


def test_providers_are_tried_in_order_and_the_first_answer_wins(priced_db):
    _btc(priced_db)
    first = FakeCryptoPriceProvider("coingecko", {"BTC": (Decimal("50000"), "EUR")})
    second = FakeCryptoPriceProvider("defillama", {"BTC": (Decimal("49000"), "EUR")})

    report = crypto_prices.refresh_prices(priced_db, [first, second], FakeReferenceRateSource())

    (entry,) = report.prices
    assert entry.price_eur == Decimal("50000")
    assert entry.source == "coingecko"


def test_an_instrument_the_primary_cannot_identify_falls_through_to_the_next(priced_db):
    """The criterion at the heart of the chain: a missing provider-specific
    identifier means "not covered here", never exclusion from pricing."""
    _btc(priced_db)
    instruments.create_native_coin(priced_db, symbol="KAS", name="Kaspa", chain="kaspa")
    primary = FakeCryptoPriceProvider("coingecko", {"BTC": (Decimal("50000"), "EUR")})
    fallback = FakeCryptoPriceProvider("defillama", {"KAS": (Decimal("0.12"), "EUR")})

    report = crypto_prices.refresh_prices(priced_db, [primary, fallback], FakeReferenceRateSource())

    by_symbol = {entry.symbol: entry for entry in report.prices}
    assert by_symbol["BTC"].source == "coingecko"
    assert by_symbol["KAS"].source == "defillama"
    assert by_symbol["KAS"].status == "fresh"
    assert report.conditions == ()


# --- Failures are named, and the store answers for them ----------------------


def test_a_rate_limit_is_its_own_condition_and_the_chain_moves_on(priced_db):
    _btc(priced_db)
    limited = FakeCryptoPriceProvider("coingecko", fails_with=RateLimitedError())
    fallback = FakeCryptoPriceProvider("defillama", {"BTC": (Decimal("49000"), "EUR")})

    report = crypto_prices.refresh_prices(priced_db, [limited, fallback], FakeReferenceRateSource())

    (entry,) = report.prices
    assert entry.status == "fresh"
    assert entry.source == "defillama"
    (condition,) = report.conditions
    assert condition.provider == "coingecko"
    assert condition.condition == "rate_limited"


def test_an_outage_is_reported_as_an_outage_not_a_rate_limit(priced_db):
    _btc(priced_db)
    down = FakeCryptoPriceProvider("coingecko", fails_with=ProviderOutageError())

    report = crypto_prices.refresh_prices(priced_db, [down], FakeReferenceRateSource())

    (condition,) = report.conditions
    assert condition.condition == "outage"


def test_when_every_provider_fails_the_stored_price_is_served_labelled_stale(priced_db):
    """The Admin sees the last known price with its source and age, clearly
    labelled stale — never a blank or a zero."""
    instrument_id = _btc(priced_db)
    _insert_price(priced_db, instrument_id, price_eur=Decimal("48000"), source="defillama")
    down = FakeCryptoPriceProvider("coingecko", fails_with=ProviderOutageError())

    report = crypto_prices.refresh_prices(priced_db, [down], FakeReferenceRateSource())

    (entry,) = report.prices
    assert entry.status == "stale"
    assert entry.price_eur == Decimal("48000")
    assert entry.source == "defillama"
    assert entry.as_of == datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def test_staleness_names_the_affected_instruments_never_a_blanket_outage(priced_db):
    """One provider down for one Instrument's only source: that Instrument is
    stale by name, the other stays fresh."""
    btc_id = _btc(priced_db)
    kas_id = instruments.create_native_coin(priced_db, symbol="KAS", name="Kaspa", chain="kaspa")
    _insert_price(priced_db, kas_id, price_eur=Decimal("0.10"), source="defillama")
    primary = FakeCryptoPriceProvider("coingecko", {"BTC": (Decimal("50000"), "EUR")})
    down = FakeCryptoPriceProvider("defillama", fails_with=ProviderOutageError())

    report = crypto_prices.refresh_prices(priced_db, [primary, down], FakeReferenceRateSource())

    by_id = {entry.instrument_id: entry for entry in report.prices}
    assert by_id[btc_id].status == "fresh"
    assert by_id[kas_id].status == "stale"
    assert by_id[kas_id].symbol == "KAS"


def test_an_instrument_nothing_ever_priced_is_named_unpriced_not_zero(priced_db):
    _btc(priced_db)
    down = FakeCryptoPriceProvider("coingecko", fails_with=ProviderOutageError())

    report = crypto_prices.refresh_prices(priced_db, [down], FakeReferenceRateSource())

    (entry,) = report.prices
    assert entry.status == "unpriced"
    assert entry.symbol == "BTC"
    assert entry.price_eur is None


def test_a_fresh_quote_replaces_the_stored_last_known_price(priced_db):
    instrument_id = _btc(priced_db)
    _insert_price(priced_db, instrument_id, price_eur=Decimal("48000"), source="defillama")
    provider = FakeCryptoPriceProvider("coingecko", {"BTC": (Decimal("50000"), "EUR")})

    crypto_prices.refresh_prices(priced_db, [provider], FakeReferenceRateSource())

    stored = stored_prices.last_known(priced_db, instrument_id)
    assert stored.price_eur == Decimal("50000")
    assert stored.source == "coingecko"


def test_a_non_eur_quote_converts_by_the_reference_rate_rule(priced_db):
    """A provider quoting USD is welcome; its answer goes through the same
    ADR-0017 rule as every other foreign-currency amount."""
    _btc(priced_db)
    provider = FakeCryptoPriceProvider("defillama", {"BTC": (Decimal("60000"), "USD")})
    rate_source = FakeReferenceRateSource([ReferenceRate("USD", date(2026, 8, 7), Decimal("1.20"))])

    report = crypto_prices.refresh_prices(priced_db, [provider], rate_source)

    (entry,) = report.prices
    assert entry.price_eur == Decimal("50000")


# --- Who is priceable at all -------------------------------------------------


def test_a_stablecoin_is_not_priced_by_the_chain(priced_db):
    """Its EUR value comes from its peg's daily reference rate — provider
    coverage of stablecoins is poor, and an unpriced disposal would
    manufacture a phantom loss."""
    instruments.create_crypto_token(
        priced_db,
        symbol="USDT",
        name="Tether USD",
        chain="ethereum",
        contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7",
        pegged_currency="USD",
    )
    provider = FakeCryptoPriceProvider("coingecko", {"USDT": (Decimal("0.9"), "EUR")})

    report = crypto_prices.refresh_prices(priced_db, [provider], FakeReferenceRateSource())

    assert report.prices == ()


def test_a_dangerous_or_only_ignored_instrument_is_not_priced(priced_db):
    """Neither may ever acquire a price source (ADR-0012) — but the same
    Instrument kept anywhere stays priceable."""
    from open_leprechaun.repositories import platforms, stances

    dangerous_id = _btc(priced_db)
    ignored_id = instruments.create_native_coin(
        priced_db, symbol="KAS", name="Kaspa", chain="kaspa"
    )
    kept_too_id = instruments.create_native_coin(
        priced_db, symbol="SOL", name="Solana", chain="solana"
    )
    platform_id = platforms.create_platform(priced_db, name="Kraken", kind="exchange")
    account_id = platforms.create_account(priced_db, platform_id, name="Main")
    other_account_id = platforms.create_account(priced_db, platform_id, name="Spare")
    stances.classify(priced_db, dangerous_id, stance="dangerous")
    stances.classify(priced_db, ignored_id, stance="ignored", account_id=account_id)
    stances.classify(priced_db, kept_too_id, stance="ignored", account_id=account_id)
    stances.classify(priced_db, kept_too_id, stance="kept", account_id=other_account_id)
    provider = FakeCryptoPriceProvider(
        "coingecko",
        {
            "BTC": (Decimal("50000"), "EUR"),
            "KAS": (Decimal("0.12"), "EUR"),
            "SOL": (Decimal("150"), "EUR"),
        },
    )

    report = crypto_prices.refresh_prices(priced_db, [provider], FakeReferenceRateSource())

    assert [entry.symbol for entry in report.prices] == ["SOL"]


# --- Daily closes and the backfill -------------------------------------------


def _closes(*days_and_prices, currency="EUR"):
    return [
        DailyClose(close_date=date(2026, 8, day), price=Decimal(price), currency=currency)
        for day, price in days_and_prices
    ]


def test_a_backfill_stores_the_chosen_range_with_source_attribution(priced_db):
    instrument_id = _btc(priced_db)
    provider = FakeCryptoPriceProvider(
        "coingecko", closes_by_symbol={"BTC": _closes((5, "49000"), (6, "49500"), (7, "50000"))}
    )

    report = crypto_prices.backfill_daily_closes(
        priced_db,
        [provider],
        FakeReferenceRateSource(),
        instrument_id=instrument_id,
        start=date(2026, 8, 5),
        end=date(2026, 8, 6),
    )

    assert report.stored == 2
    assert report.source == "coingecko"
    stored = stored_prices.daily_closes(
        priced_db, instrument_id, start=date(2026, 8, 1), end=date(2026, 8, 31)
    )
    assert [(row.close_date, row.price_eur, row.source) for row in stored] == [
        (date(2026, 8, 5), Decimal("49000"), "coingecko"),
        (date(2026, 8, 6), Decimal("49500"), "coingecko"),
    ]


def test_a_backfill_rerun_stores_nothing_new(priced_db):
    """The first stored close for a day wins forever, so history never
    silently shifts under a chart."""
    instrument_id = _btc(priced_db)
    provider = FakeCryptoPriceProvider("coingecko", closes_by_symbol={"BTC": _closes((5, "49000"))})
    args = {"instrument_id": instrument_id, "start": date(2026, 8, 5), "end": date(2026, 8, 5)}

    crypto_prices.backfill_daily_closes(priced_db, [provider], FakeReferenceRateSource(), **args)
    provider.closes_by_symbol = {"BTC": _closes((5, "999"))}
    rerun = crypto_prices.backfill_daily_closes(
        priced_db, [provider], FakeReferenceRateSource(), **args
    )

    assert rerun.stored == 0
    stored = stored_prices.daily_closes(
        priced_db, instrument_id, start=date(2026, 8, 5), end=date(2026, 8, 5)
    )
    assert stored[0].price_eur == Decimal("49000")


def test_a_backfill_falls_through_a_failing_provider_and_names_the_condition(priced_db):
    instrument_id = _btc(priced_db)
    limited = FakeCryptoPriceProvider("coingecko", fails_with=RateLimitedError())
    fallback = FakeCryptoPriceProvider(
        "defillama", closes_by_symbol={"BTC": _closes((5, "60000"), currency="USD")}
    )
    rate_source = FakeReferenceRateSource([ReferenceRate("USD", date(2026, 8, 5), Decimal("1.20"))])

    report = crypto_prices.backfill_daily_closes(
        priced_db,
        [limited, fallback],
        rate_source,
        instrument_id=instrument_id,
        start=date(2026, 8, 5),
        end=date(2026, 8, 5),
    )

    assert report.stored == 1
    assert report.source == "defillama"
    (condition,) = report.conditions
    assert condition == crypto_prices.ProviderCondition("coingecko", "rate_limited")
    stored = stored_prices.daily_closes(
        priced_db, instrument_id, start=date(2026, 8, 5), end=date(2026, 8, 5)
    )
    assert stored[0].price_eur == Decimal("50000")


def test_a_backfill_no_provider_answers_stores_nothing_and_names_no_source(priced_db):
    instrument_id = _btc(priced_db)
    down = FakeCryptoPriceProvider("coingecko", fails_with=ProviderOutageError())

    report = crypto_prices.backfill_daily_closes(
        priced_db,
        [down],
        FakeReferenceRateSource(),
        instrument_id=instrument_id,
        start=date(2026, 8, 5),
        end=date(2026, 8, 5),
    )

    assert report.stored == 0
    assert report.source is None
    assert report.conditions == (crypto_prices.ProviderCondition("coingecko", "outage"),)


# --- The CoinGecko implementation, against recorded responses -----------------


@dataclass(frozen=True)
class InstrumentRow:
    """The shape the repository answers priceable Instruments in."""

    id: int
    type: str
    symbol: str
    name: str
    chain: str | None
    contract_address: str | None


BTC_ROW = InstrumentRow(1, "native", "BTC", "Bitcoin", "bitcoin", None)
UNI_ROW = InstrumentRow(
    2, "token", "UNI", "Uniswap", "ethereum", "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984"
)
# A native coin CoinGecko has no id mapping for, and a token on a chain it has
# no platform mapping for — not covered, never an error.
UNMAPPED_NATIVE = InstrumentRow(3, "native", "XYZ", "Xyz", "xyzchain", None)
UNMAPPED_TOKEN = InstrumentRow(4, "token", "ABC", "Abc", "abcchain", "0xabc")

# Trimmed but structurally faithful answers, one per endpoint the provider
# uses. Prices decode through Decimal, never a float.
COINGECKO_SIMPLE_PRICE = '{"bitcoin":{"eur":51234.56,"last_updated_at":1786104000}}'
COINGECKO_TOKEN_PRICE = (
    '{"0x1f9840a85d5af5bf1d1762f925bdaddc4201f984":{"eur":6.78,"last_updated_at":1786104000}}'
)


def _coingecko(handler):
    from open_leprechaun.ports.coingecko import CoinGeckoProvider

    return CoinGeckoProvider(httpx.Client(transport=httpx.MockTransport(handler)))


def test_coingecko_answers_natives_and_tokens_by_its_own_identifiers():
    def handler(request):
        if request.url.path.endswith("/simple/price"):
            assert request.url.params["ids"] == "bitcoin"
            assert request.url.params["vs_currencies"] == "eur"
            return httpx.Response(200, text=COINGECKO_SIMPLE_PRICE)
        assert request.url.path.endswith("/simple/token_price/ethereum")
        assert (
            request.url.params["contract_addresses"] == "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984"
        )
        return httpx.Response(200, text=COINGECKO_TOKEN_PRICE)

    quotes = _coingecko(handler).quotes([BTC_ROW, UNI_ROW])

    assert Quote(1, Decimal("51234.56"), "EUR", datetime.fromtimestamp(1786104000, UTC)) in quotes
    assert Quote(2, Decimal("6.78"), "EUR", datetime.fromtimestamp(1786104000, UTC)) in quotes


def test_coingecko_leaves_an_instrument_it_cannot_map_uncovered_without_asking():
    """No provider-specific identifier being absent may exclude an Instrument
    from pricing — unmapped means uncovered here, and the chain moves on."""
    quotes = _coingecko(
        lambda request: (_ for _ in ()).throw(AssertionError("no identifier, no request"))
    ).quotes([UNMAPPED_NATIVE, UNMAPPED_TOKEN])

    assert quotes == []


def test_coingecko_surfaces_a_rate_limit_as_its_own_condition():
    with pytest.raises(RateLimitedError):
        _coingecko(lambda request: httpx.Response(429)).quotes([BTC_ROW])


def test_coingecko_surfaces_any_other_failure_as_an_outage():
    with pytest.raises(ProviderOutageError):
        _coingecko(lambda request: httpx.Response(503)).quotes([BTC_ROW])


def test_coingecko_reduces_chart_points_to_one_close_per_day():
    """The range endpoint answers finer-grained points for short ranges; the
    last point of each UTC day is that day's close."""
    chart = (
        '{"prices":['
        "[1785729600000,49000.1],[1785772800000,49100.2],"
        "[1785859200000,49500.3],[1785945600000,50000.4]]}"
    )

    def handler(request):
        assert request.url.path.endswith("/coins/bitcoin/market_chart/range")
        assert request.url.params["vs_currency"] == "eur"
        return httpx.Response(200, text=chart)

    closes = _coingecko(handler).daily_closes(BTC_ROW, date(2026, 8, 3), date(2026, 8, 5))

    assert closes == [
        DailyClose(date(2026, 8, 3), Decimal("49100.2"), "EUR"),
        DailyClose(date(2026, 8, 4), Decimal("49500.3"), "EUR"),
        DailyClose(date(2026, 8, 5), Decimal("50000.4"), "EUR"),
    ]


# --- The DefiLlama implementation, against recorded responses -----------------

DEFILLAMA_CURRENT = (
    '{"coins":{'
    '"coingecko:bitcoin":{"price":60000.5,"symbol":"BTC","timestamp":1786104000,'
    '"confidence":0.99},'
    '"ethereum:0x1f9840a85d5af5bf1d1762f925bdaddc4201f984":'
    '{"price":7.89,"symbol":"UNI","timestamp":1786104000,"confidence":0.98}}}'
)


def _defillama(handler):
    from open_leprechaun.ports.defillama import DefiLlamaProvider

    return DefiLlamaProvider(httpx.Client(transport=httpx.MockTransport(handler)))


def test_defillama_answers_usd_quotes_keyed_by_chain_and_contract():
    def handler(request):
        assert "/prices/current/" in request.url.path
        assert "coingecko:bitcoin" in request.url.path
        assert "ethereum:0x1f9840a85d5af5bf1d1762f925bdaddc4201f984" in request.url.path
        return httpx.Response(200, text=DEFILLAMA_CURRENT)

    quotes = _defillama(handler).quotes([BTC_ROW, UNI_ROW, UNMAPPED_NATIVE])

    assert Quote(1, Decimal("60000.5"), "USD", datetime.fromtimestamp(1786104000, UTC)) in quotes
    assert Quote(2, Decimal("7.89"), "USD", datetime.fromtimestamp(1786104000, UTC)) in quotes
    assert len(quotes) == 2


def test_defillama_asks_nothing_when_it_can_map_nothing():
    quotes = _defillama(
        lambda request: (_ for _ in ()).throw(AssertionError("no identifier, no request"))
    ).quotes([UNMAPPED_NATIVE, UNMAPPED_TOKEN])

    assert quotes == []


def test_defillama_surfaces_rate_limit_and_outage_distinctly():
    with pytest.raises(RateLimitedError):
        _defillama(lambda request: httpx.Response(429)).quotes([BTC_ROW])
    with pytest.raises(ProviderOutageError):
        _defillama(lambda request: httpx.Response(500)).quotes([BTC_ROW])


def test_defillama_answers_daily_closes_in_usd():
    chart = (
        '{"coins":{"coingecko:bitcoin":{"prices":'
        '[{"timestamp":1785772800,"price":58000.1},'
        '{"timestamp":1785859200,"price":58500.2}]}}}'
    )

    def handler(request):
        assert "/chart/coingecko:bitcoin" in request.url.path
        assert request.url.params["period"] == "1d"
        return httpx.Response(200, text=chart)

    closes = _defillama(handler).daily_closes(BTC_ROW, date(2026, 8, 3), date(2026, 8, 4))

    assert closes == [
        DailyClose(date(2026, 8, 3), Decimal("58000.1"), "USD"),
        DailyClose(date(2026, 8, 4), Decimal("58500.2"), "USD"),
    ]


# --- The API serves the report -----------------------------------------------


@pytest.fixture
def priced_client(priced_db):
    """The API bound to the test database and a chain of fakes the test can
    reconfigure through `priced_client.chain`."""
    from fastapi.testclient import TestClient

    from open_leprechaun.db import get_engine
    from open_leprechaun.main import create_app
    from open_leprechaun.prices import get_crypto_price_chain
    from open_leprechaun.rates import get_reference_rate_source

    chain: list = []
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: priced_db
    app.dependency_overrides[get_crypto_price_chain] = lambda: chain
    app.dependency_overrides[get_reference_rate_source] = FakeReferenceRateSource
    with TestClient(app) as client:
        client.chain = chain
        yield client


def test_the_api_serves_prices_with_staleness_and_conditions(priced_db, priced_client):
    """The response names what is stale and what condition each failing
    provider is in — decimal strings, never floats."""
    _btc(priced_db)
    kas_id = instruments.create_native_coin(priced_db, symbol="KAS", name="Kaspa", chain="kaspa")
    _insert_price(priced_db, kas_id, price_eur=Decimal("0.10"), source="defillama")
    priced_client.chain.append(
        FakeCryptoPriceProvider("coingecko", {"BTC": (Decimal("50000.5"), "EUR")})
    )
    priced_client.chain.append(FakeCryptoPriceProvider("defillama", fails_with=RateLimitedError()))

    response = priced_client.get("/api/prices/crypto")

    assert response.status_code == 200
    report = response.json()
    by_symbol = {entry["symbol"]: entry for entry in report["prices"]}
    assert by_symbol["BTC"]["status"] == "fresh"
    assert by_symbol["BTC"]["price_eur"] == "50000.5"
    assert by_symbol["KAS"]["status"] == "stale"
    assert by_symbol["KAS"]["price_eur"] == "0.10"
    assert by_symbol["KAS"]["source"] == "defillama"
    assert by_symbol["KAS"]["as_of"] is not None
    assert report["conditions"] == [{"provider": "defillama", "condition": "rate_limited"}]


def test_the_api_backfills_and_serves_daily_closes(priced_db, priced_client):
    instrument_id = _btc(priced_db)
    priced_client.chain.append(
        FakeCryptoPriceProvider(
            "coingecko", closes_by_symbol={"BTC": _closes((5, "49000"), (6, "49500"))}
        )
    )

    backfilled = priced_client.post(
        f"/api/prices/crypto/{instrument_id}/closes/backfill",
        json={"start": "2026-08-05", "end": "2026-08-06"},
    )

    assert backfilled.status_code == 200
    assert backfilled.json() == {"stored": 2, "source": "coingecko", "conditions": []}

    served = priced_client.get(
        f"/api/prices/crypto/{instrument_id}/closes",
        params={"start": "2026-08-01", "end": "2026-08-31"},
    )
    assert served.status_code == 200
    assert served.json() == [
        {"close_date": "2026-08-05", "price_eur": "49000", "source": "coingecko"},
        {"close_date": "2026-08-06", "price_eur": "49500", "source": "coingecko"},
    ]


def test_the_api_refuses_a_backfill_for_an_unknown_instrument(priced_client):
    response = priced_client.post(
        "/api/prices/crypto/424242/closes/backfill",
        json={"start": "2026-08-05", "end": "2026-08-06"},
    )

    assert response.status_code == 404


def test_the_api_refuses_a_backfill_range_that_ends_before_it_starts(priced_db, priced_client):
    instrument_id = _btc(priced_db)

    response = priced_client.post(
        f"/api/prices/crypto/{instrument_id}/closes/backfill",
        json={"start": "2026-08-06", "end": "2026-08-05"},
    )

    assert response.status_code == 422

"""Market data for securities (ticket 45): identity resolution and pricing
are separate ports — one maps an identifier to its Listings, the other
fetches quotes and daily closes for the Listing chosen as the price source —
and what a provider answers becomes the stored last-known price, served
clearly labelled stale when the provider fails and named unpriced where
nothing has ever priced the Instrument.

The seams are the schema over real Postgres, the pricing service driven
through fakes of both ports, the HTTP API, and the onvista implementation
against recorded responses.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from open_leprechaun.ports.crypto_prices import DailyClose, ProviderOutageError, RateLimitedError
from open_leprechaun.ports.reference_rates import ReferenceRate
from open_leprechaun.ports.security_prices import ListingQuote
from open_leprechaun.repositories import instruments
from open_leprechaun.repositories import security_prices as stored_prices
from open_leprechaun.services import security_prices

QUOTED_AT = datetime(2026, 8, 11, 15, 30, tzinfo=UTC)


class FakeSecurityPriceProvider:
    """The pricing port's fake: quotes keyed by ISIN, or a failure the test
    chooses — which is how the stale label and the named conditions are
    proven."""

    def __init__(self, name="onvista", quotes_by_isin=None, closes_by_isin=None, fails_with=None):
        self.name = name
        self.quotes_by_isin = quotes_by_isin or {}
        self.closes_by_isin = closes_by_isin or {}
        self.fails_with = fails_with
        self.asked_listings = []

    def quotes(self, listings):
        if self.fails_with is not None:
            raise self.fails_with
        self.asked_listings = list(listings)
        return [
            ListingQuote(
                instrument_id=listing.instrument_id,
                price=self.quotes_by_isin[listing.isin][0],
                currency=self.quotes_by_isin[listing.isin][1],
                venue=listing.venue,
                as_of=QUOTED_AT,
            )
            for listing in listings
            if listing.isin in self.quotes_by_isin
        ]

    def daily_closes(self, listing, start, end):
        if self.fails_with is not None:
            raise self.fails_with
        return [
            close
            for close in self.closes_by_isin.get(listing.isin, [])
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


def _share(engine, *, isin="DE0008404005", symbol="ALV", venue=None, quote_currency=None) -> int:
    return instruments.create_security(
        engine,
        symbol=symbol,
        name="Allianz",
        type="share",
        isin=isin,
        venue=venue,
        quote_currency=quote_currency,
    )


def _insert_price(engine, instrument_id, *, price_eur=Decimal("250"), source="onvista"):
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO security_price"
                " (instrument_id, price_eur, quote_currency, venue, source, as_of)"
                " VALUES (:instrument_id, :price_eur, 'EUR', 'gettex', :source, :as_of)"
            ),
            {
                "instrument_id": instrument_id,
                "price_eur": price_eur,
                "source": source,
                "as_of": QUOTED_AT,
            },
        )


def _insert_close(engine, instrument_id, *, close_date="2026-08-10", price_eur=Decimal("250")):
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO security_daily_close (instrument_id, close_date, price_eur, source)"
                " VALUES (:instrument_id, :close_date, :price_eur, 'onvista')"
            ),
            {
                "instrument_id": instrument_id,
                "close_date": close_date,
                "price_eur": price_eur,
            },
        )


# --- The schema is the arbiter ----------------------------------------------


def test_the_schema_holds_one_last_known_price_per_instrument(db):
    instrument_id = _share(db)
    _insert_price(db, instrument_id)
    with pytest.raises(IntegrityError):
        _insert_price(db, instrument_id, price_eur=Decimal("260"))


def test_the_schema_refuses_a_non_positive_price(db):
    with pytest.raises(IntegrityError):
        _insert_price(db, _share(db), price_eur=Decimal("0"))


def test_the_schema_refuses_a_price_for_no_instrument(db):
    with pytest.raises(IntegrityError):
        _insert_price(db, 424242)


def test_the_schema_holds_one_close_per_instrument_and_date(db):
    instrument_id = _share(db)
    _insert_close(db, instrument_id)
    with pytest.raises(IntegrityError):
        _insert_close(db, instrument_id, price_eur=Decimal("260"))


def test_the_schema_refuses_a_non_positive_close(db):
    with pytest.raises(IntegrityError):
        _insert_close(db, _share(db), price_eur=Decimal("-1"))


def test_the_schema_holds_one_price_source_listing_per_instrument(db):
    instrument_id = _share(db, venue="gettex", quote_currency="EUR")
    with db.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO listing (instrument_id, venue, quote_currency, price_source)"
                " VALUES (:instrument_id, 'Xetra', 'EUR', true)"
            ),
            {"instrument_id": instrument_id},
        )


# --- The provider prices, and what it learns is stored ------------------------


def test_a_fresh_quote_is_served_and_stored_with_its_venue_and_source(priced_db):
    instrument_id = _share(priced_db, venue="gettex", quote_currency="EUR")
    provider = FakeSecurityPriceProvider(quotes_by_isin={"DE0008404005": (Decimal("250.5"), "EUR")})

    report = security_prices.refresh_prices(priced_db, provider, FakeReferenceRateSource())

    (entry,) = report.prices
    assert entry.instrument_id == instrument_id
    assert entry.status == "fresh"
    assert entry.price_eur == Decimal("250.5")
    assert entry.source == "onvista"
    assert entry.as_of == QUOTED_AT
    assert report.conditions == ()

    stored = stored_prices.last_known(priced_db, instrument_id)
    assert stored.price_eur == Decimal("250.5")
    assert stored.quote_currency == "EUR"
    assert stored.venue == "gettex"
    assert stored.source == "onvista"
    assert stored.as_of == QUOTED_AT


def test_the_provider_is_asked_for_the_price_source_listing_alone(priced_db):
    """The pricing port takes the Listing chosen as the price source — one
    market's answer, not whichever the provider prefers."""
    instrument_id = _share(priced_db, venue="gettex", quote_currency="EUR")
    instruments.add_listing(priced_db, instrument_id, venue="Xetra", quote_currency="EUR")
    provider = FakeSecurityPriceProvider(quotes_by_isin={"DE0008404005": (Decimal("250"), "EUR")})

    security_prices.refresh_prices(priced_db, provider, FakeReferenceRateSource())

    (asked,) = provider.asked_listings
    assert asked.isin == "DE0008404005"
    assert asked.venue == "gettex"
    assert asked.quote_currency == "EUR"


def test_a_failing_provider_serves_the_store_stale_and_names_its_condition(priced_db):
    instrument_id = _share(priced_db, venue="gettex", quote_currency="EUR")
    _insert_price(priced_db, instrument_id, price_eur=Decimal("240"))
    provider = FakeSecurityPriceProvider(fails_with=RateLimitedError())

    report = security_prices.refresh_prices(priced_db, provider, FakeReferenceRateSource())

    (entry,) = report.prices
    assert entry.status == "stale"
    assert entry.price_eur == Decimal("240")
    assert entry.source == "onvista"
    assert report.conditions == (
        security_prices.ProviderCondition(provider="onvista", condition="rate_limited"),
    )


def test_an_outage_is_its_own_condition(priced_db):
    _share(priced_db, venue="gettex", quote_currency="EUR")
    provider = FakeSecurityPriceProvider(fails_with=ProviderOutageError())

    report = security_prices.refresh_prices(priced_db, provider, FakeReferenceRateSource())

    assert report.conditions == (
        security_prices.ProviderCondition(provider="onvista", condition="outage"),
    )


def test_a_security_nothing_ever_priced_is_named_unpriced_never_zero(priced_db):
    """The criterion: no coverage means a named admission, not a zero."""
    _share(priced_db, venue="gettex", quote_currency="EUR")
    provider = FakeSecurityPriceProvider()

    report = security_prices.refresh_prices(priced_db, provider, FakeReferenceRateSource())

    (entry,) = report.prices
    assert entry.status == "unpriced"
    assert entry.price_eur is None


def test_a_security_without_a_price_source_listing_is_still_reported_by_name(priced_db):
    """Manual creation without a Listing (ticket 44): nothing can vouch for a
    value, so the security appears unpriced by name rather than vanishing."""
    _share(priced_db)
    provider = FakeSecurityPriceProvider(quotes_by_isin={"DE0008404005": (Decimal("250"), "EUR")})

    report = security_prices.refresh_prices(priced_db, provider, FakeReferenceRateSource())

    assert provider.asked_listings == []
    (entry,) = report.prices
    assert entry.status == "unpriced"


def test_a_non_eur_quote_converts_by_the_reference_rate_of_its_event_date(priced_db):
    """A quote in USD converts by the euro reference rate of the quote's own
    date — the one rule every foreign-currency amount follows (ADR-0017)."""
    instrument_id = _share(
        priced_db, isin="IE00B4L5Y983", symbol="EUNL", venue="London", quote_currency="USD"
    )
    provider = FakeSecurityPriceProvider(quotes_by_isin={"IE00B4L5Y983": (Decimal("150"), "USD")})
    rate_source = FakeReferenceRateSource(
        [ReferenceRate(currency="USD", rate_date=QUOTED_AT.date(), rate=Decimal("1.25"))]
    )

    report = security_prices.refresh_prices(priced_db, provider, rate_source)

    (entry,) = report.prices
    assert entry.status == "fresh"
    assert entry.price_eur == Decimal("120")
    stored = stored_prices.last_known(priced_db, instrument_id)
    assert stored.price_eur == Decimal("120")
    assert stored.quote_currency == "USD"
    assert stored.venue == "London"


def test_an_unconvertible_quote_is_no_answer_and_the_store_speaks_instead(priced_db):
    instrument_id = _share(
        priced_db, isin="IE00B4L5Y983", symbol="EUNL", venue="London", quote_currency="USD"
    )
    _insert_price(priced_db, instrument_id, price_eur=Decimal("115"))
    provider = FakeSecurityPriceProvider(quotes_by_isin={"IE00B4L5Y983": (Decimal("150"), "USD")})

    report = security_prices.refresh_prices(priced_db, provider, FakeReferenceRateSource())

    (entry,) = report.prices
    assert entry.status == "stale"
    assert entry.price_eur == Decimal("115")


def test_a_dangerous_security_never_acquires_a_price(priced_db):
    """An ignored or dangerous Instrument is barred from ever acquiring a
    price source (ADR-0012) — it is absent from the report entirely."""
    instrument_id = _share(priced_db, venue="gettex", quote_currency="EUR")
    with priced_db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO instrument_stance (instrument_id, account_id, stance)"
                " VALUES (:instrument_id, NULL, 'dangerous')"
            ),
            {"instrument_id": instrument_id},
        )
    provider = FakeSecurityPriceProvider(quotes_by_isin={"DE0008404005": (Decimal("250"), "EUR")})

    report = security_prices.refresh_prices(priced_db, provider, FakeReferenceRateSource())

    assert report.prices == ()


# --- Daily closes ------------------------------------------------------------


def _closes(*days_and_prices, currency="EUR"):
    return [
        DailyClose(close_date=date(2026, 8, day), price=Decimal(price), currency=currency)
        for day, price in days_and_prices
    ]


def test_a_backfill_stores_the_range_and_first_stored_wins(priced_db):
    instrument_id = _share(priced_db, venue="gettex", quote_currency="EUR")
    _insert_close(priced_db, instrument_id, close_date="2026-08-05", price_eur=Decimal("240"))
    provider = FakeSecurityPriceProvider(
        closes_by_isin={"DE0008404005": _closes((5, "999"), (6, "251"), (7, "252"))}
    )

    report = security_prices.backfill_daily_closes(
        priced_db,
        provider,
        FakeReferenceRateSource(),
        instrument_id=instrument_id,
        start=date(2026, 8, 5),
        end=date(2026, 8, 7),
    )

    assert report.stored == 2
    assert report.source == "onvista"
    held = stored_prices.daily_closes(
        priced_db, instrument_id, start=date(2026, 8, 5), end=date(2026, 8, 7)
    )
    assert [(row.close_date, row.price_eur) for row in held] == [
        (date(2026, 8, 5), Decimal("240")),
        (date(2026, 8, 6), Decimal("251")),
        (date(2026, 8, 7), Decimal("252")),
    ]


def test_a_non_eur_close_converts_by_its_own_dates_rate(priced_db):
    instrument_id = _share(
        priced_db, isin="IE00B4L5Y983", symbol="EUNL", venue="London", quote_currency="USD"
    )
    provider = FakeSecurityPriceProvider(
        closes_by_isin={"IE00B4L5Y983": _closes((6, "150"), (7, "150"), currency="USD")}
    )
    rate_source = FakeReferenceRateSource(
        [
            ReferenceRate(currency="USD", rate_date=date(2026, 8, 6), rate=Decimal("1.25")),
            ReferenceRate(currency="USD", rate_date=date(2026, 8, 7), rate=Decimal("1.20")),
        ]
    )

    report = security_prices.backfill_daily_closes(
        priced_db,
        provider,
        rate_source,
        instrument_id=instrument_id,
        start=date(2026, 8, 6),
        end=date(2026, 8, 7),
    )

    assert report.stored == 2
    held = stored_prices.daily_closes(
        priced_db, instrument_id, start=date(2026, 8, 6), end=date(2026, 8, 7)
    )
    assert [(row.close_date, row.price_eur) for row in held] == [
        (date(2026, 8, 6), Decimal("120")),
        (date(2026, 8, 7), Decimal("125")),
    ]


def test_a_backfill_without_a_price_source_listing_is_refused(priced_db):
    instrument_id = _share(priced_db)

    report = security_prices.backfill_daily_closes(
        priced_db,
        FakeSecurityPriceProvider(),
        FakeReferenceRateSource(),
        instrument_id=instrument_id,
        start=date(2026, 8, 5),
        end=date(2026, 8, 7),
    )

    assert report is None


def test_a_rate_limited_backfill_names_its_condition(priced_db):
    instrument_id = _share(priced_db, venue="gettex", quote_currency="EUR")

    report = security_prices.backfill_daily_closes(
        priced_db,
        FakeSecurityPriceProvider(fails_with=RateLimitedError()),
        FakeReferenceRateSource(),
        instrument_id=instrument_id,
        start=date(2026, 8, 5),
        end=date(2026, 8, 7),
    )

    assert report.stored == 0
    assert report.conditions == (
        security_prices.ProviderCondition(provider="onvista", condition="rate_limited"),
    )


# --- The API: listings entered by hand or resolved from the provider ----------


class FakeResolution:
    """The resolution port's fake: listings keyed by identifier."""

    def __init__(self, listings_by_identifier=None, fails_with=None):
        self.name = "onvista"
        self.listings_by_identifier = listings_by_identifier or {}
        self.fails_with = fails_with

    def listings(self, identifier):
        if self.fails_with is not None:
            raise self.fails_with
        return self.listings_by_identifier.get(identifier, [])


@pytest.fixture
def market_client(priced_db):
    """The API bound to the test database and to fakes of both market-data
    ports the test can reconfigure."""
    from fastapi.testclient import TestClient

    from open_leprechaun.db import get_engine
    from open_leprechaun.main import create_app
    from open_leprechaun.market_data import get_security_prices, get_security_resolution
    from open_leprechaun.rates import get_reference_rate_source

    state = {"resolution": FakeResolution(), "prices": FakeSecurityPriceProvider()}
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: priced_db
    app.dependency_overrides[get_security_resolution] = lambda: state["resolution"]
    app.dependency_overrides[get_security_prices] = lambda: state["prices"]
    app.dependency_overrides[get_reference_rate_source] = FakeReferenceRateSource
    with TestClient(app) as client:
        client.state_of = state
        yield client


def test_the_api_resolves_an_identifier_to_candidate_listings(market_client):
    from open_leprechaun.ports.security_resolution import ResolvedListing

    market_client.state_of["resolution"] = FakeResolution(
        {
            "IE00B4L5Y983": [
                ResolvedListing(venue="Xetra", quote_currency="EUR"),
                ResolvedListing(venue="London Stock Exchange", quote_currency="USD"),
            ]
        }
    )

    response = market_client.get(
        "/api/securities/listings/resolve", params={"identifier": "IE00B4L5Y983"}
    )

    assert response.status_code == 200
    assert response.json() == [
        {"venue": "Xetra", "quote_currency": "EUR"},
        {"venue": "London Stock Exchange", "quote_currency": "USD"},
    ]


def test_a_rate_limited_resolution_names_its_condition(market_client):
    market_client.state_of["resolution"] = FakeResolution(fails_with=RateLimitedError("paused"))

    response = market_client.get(
        "/api/securities/listings/resolve", params={"identifier": "IE00B4L5Y983"}
    )

    assert response.status_code == 503


def test_a_listing_is_entered_by_hand_and_may_take_the_price_source(market_client, priced_db):
    """The criterion: where no provider resolves a listing, the Admin states
    venue and currency directly — and may hand the price source over in the
    same act, displacing the previous holder."""
    instrument_id = _share(priced_db, venue="gettex", quote_currency="EUR")

    response = market_client.post(
        f"/api/securities/{instrument_id}/listings",
        json={"venue": "Xetra", "quote_currency": "EUR", "price_source": True},
    )

    assert response.status_code == 201
    listings = {(row.venue, row.price_source) for row in _listings(priced_db, instrument_id)}
    assert listings == {("gettex", False), ("Xetra", True)}


def test_the_first_listing_of_a_bare_security_takes_the_price_source(market_client, priced_db):
    """The rule is the server's, not a client courtesy: a first Listing makes
    the security priceable whoever the caller is."""
    instrument_id = _share(priced_db)

    response = market_client.post(
        f"/api/securities/{instrument_id}/listings",
        json={"venue": "gettex", "quote_currency": "EUR"},
    )

    assert response.status_code == 201
    (listing,) = _listings(priced_db, instrument_id)
    assert listing.price_source


def test_a_duplicate_listing_is_a_conflict(market_client, priced_db):
    instrument_id = _share(priced_db, venue="gettex", quote_currency="EUR")

    response = market_client.post(
        f"/api/securities/{instrument_id}/listings",
        json={"venue": "gettex", "quote_currency": "EUR"},
    )

    assert response.status_code == 409


def test_a_listing_belongs_to_a_security(market_client, priced_db):
    from open_leprechaun.repositories import instruments as instruments_repository

    crypto_id = instruments_repository.create_native_coin(
        priced_db, symbol="BTC", name="Bitcoin", chain="bitcoin"
    )

    response = market_client.post(
        f"/api/securities/{crypto_id}/listings",
        json={"venue": "gettex", "quote_currency": "EUR"},
    )

    assert response.status_code == 404


def test_the_price_source_moves_to_a_chosen_listing(market_client, priced_db):
    instrument_id = _share(priced_db, venue="gettex", quote_currency="EUR")
    listing_id = instruments.add_listing(
        priced_db, instrument_id, venue="Xetra", quote_currency="EUR"
    )

    response = market_client.put(
        f"/api/securities/{instrument_id}/listings/{listing_id}/price-source"
    )

    assert response.status_code == 204
    listings = {(row.venue, row.price_source) for row in _listings(priced_db, instrument_id)}
    assert listings == {("gettex", False), ("Xetra", True)}


def test_the_price_source_cannot_move_to_another_instruments_listing(market_client, priced_db):
    instrument_id = _share(priced_db, venue="gettex", quote_currency="EUR")
    other_id = _share(
        priced_db, isin="IE00B4L5Y983", symbol="EUNL", venue="Xetra", quote_currency="EUR"
    )
    (other_listing,) = [row for row in _listings(priced_db, other_id)]

    response = market_client.put(
        f"/api/securities/{instrument_id}/listings/{other_listing.id}/price-source"
    )

    assert response.status_code == 404


def _listings(engine, instrument_id):
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT id, venue, quote_currency, price_source FROM listing"
                " WHERE instrument_id = :instrument_id ORDER BY id"
            ),
            {"instrument_id": instrument_id},
        ).all()


# --- The API serves the report -----------------------------------------------


def test_the_api_serves_security_prices_with_staleness_and_conditions(market_client, priced_db):
    _share(priced_db, venue="gettex", quote_currency="EUR")
    stale_id = _share(
        priced_db, isin="IE00B4L5Y983", symbol="EUNL", venue="Xetra", quote_currency="EUR"
    )
    _insert_price(priced_db, stale_id, price_eur=Decimal("115.5"))
    market_client.state_of["prices"] = FakeSecurityPriceProvider(
        quotes_by_isin={"DE0008404005": (Decimal("250.5"), "EUR")}
    )

    response = market_client.get("/api/prices/securities")

    assert response.status_code == 200
    report = response.json()
    by_symbol = {entry["symbol"]: entry for entry in report["prices"]}
    assert by_symbol["ALV"]["status"] == "fresh"
    assert by_symbol["ALV"]["price_eur"] == "250.5"
    assert by_symbol["EUNL"]["status"] == "stale"
    assert by_symbol["EUNL"]["price_eur"] == "115.5"
    assert by_symbol["EUNL"]["source"] == "onvista"
    assert report["conditions"] == []


def test_the_api_backfills_and_serves_security_closes(market_client, priced_db):
    instrument_id = _share(priced_db, venue="gettex", quote_currency="EUR")
    market_client.state_of["prices"] = FakeSecurityPriceProvider(
        closes_by_isin={"DE0008404005": _closes((5, "249"), (6, "251"))}
    )

    backfilled = market_client.post(
        f"/api/prices/securities/{instrument_id}/closes/backfill",
        json={"start": "2026-08-05", "end": "2026-08-07"},
    )

    assert backfilled.status_code == 200
    assert backfilled.json()["stored"] == 2

    served = market_client.get(
        f"/api/prices/securities/{instrument_id}/closes",
        params={"start": "2026-08-05", "end": "2026-08-07"},
    )
    assert [entry["price_eur"] for entry in served.json()] == ["249", "251"]


def test_the_api_refuses_a_backfill_without_a_price_source(market_client, priced_db):
    instrument_id = _share(priced_db)

    response = market_client.post(
        f"/api/prices/securities/{instrument_id}/closes/backfill",
        json={"start": "2026-08-05", "end": "2026-08-07"},
    )

    assert response.status_code == 404


def test_the_instruments_overview_shows_each_listing_with_its_price_source(
    market_client, priced_db
):
    instrument_id = _share(priced_db, venue="gettex", quote_currency="EUR")
    instruments.add_listing(priced_db, instrument_id, venue="Xetra", quote_currency="EUR")

    response = market_client.get("/api/instruments")

    (row,) = [entry for entry in response.json() if entry["id"] == instrument_id]
    by_venue = {listing["venue"]: listing for listing in row["listings"]}
    assert by_venue["gettex"]["price_source"] is True
    assert by_venue["Xetra"]["price_source"] is False
    assert all(isinstance(listing["id"], int) for listing in row["listings"])


# --- The onvista implementation, against recorded responses -------------------

# Trimmed but structurally faithful answers: the query endpoint that accepts
# ISIN, WKN, ticker and name alike; the snapshot whose quoteList carries every
# market with its currency and notation; and the eod_history whose parallel
# arrays carry one close per trading day.
ONVISTA_QUERY = """{"list": [
  {"entityType": "FUND", "entitySubType": "ETF", "entityValue": "25096683",
   "name": "iShares Core MSCI World UCITS ETF USD Acc.",
   "isin": "IE00B4L5Y983", "wkn": "A0RPWH", "symbol": "EUNL"}
]}"""

ONVISTA_SNAPSHOT = """{
  "quote": {"isoCurrency": "EUR", "last": 128.7,
            "datetimeLast": "2026-08-11T15:30:00.000+00:00",
            "market": {"name": "gettex", "idNotation": 253929827}},
  "quoteList": {"list": [
    {"isoCurrency": "EUR", "last": 128.75,
     "datetimeLast": "2026-08-11T15:31:00.000+00:00",
     "market": {"name": "Xetra", "idNotation": 108344843}},
    {"isoCurrency": "EUR", "last": 128.7,
     "datetimeLast": "2026-08-11T15:30:00.000+00:00",
     "market": {"name": "gettex", "idNotation": 253929827}},
    {"isoCurrency": "USD", "last": 148.47,
     "datetimeLast": "2026-08-11T15:29:00.000+00:00",
     "market": {"name": "London Stock Exchange", "idNotation": 31002528}}
  ]}
}"""

# 2026-08-05 and 2026-08-06, noon UTC, as unix seconds.
ONVISTA_EOD = """{
  "isoCurrency": "EUR", "idNotation": 108344843,
  "datetimeLast": [1785931200, 1786017600],
  "last": [128.05, 128.65]
}"""


def _onvista(handler):
    import httpx

    from open_leprechaun.ports.onvista_market_data import OnvistaMarketDataProvider

    return OnvistaMarketDataProvider(httpx.Client(transport=httpx.MockTransport(handler)))


def _market_handler(request):
    import httpx

    if request.url.path.endswith("/instruments/query"):
        if request.url.params["searchValue"] == "IE00B4L5Y983":
            return httpx.Response(200, text=ONVISTA_QUERY)
        return httpx.Response(200, text='{"list": []}')
    if request.url.path.endswith("/funds/25096683/snapshot"):
        return httpx.Response(200, text=ONVISTA_SNAPSHOT)
    assert request.url.path.endswith("/instruments/FUND/25096683/eod_history")
    assert request.url.params["idNotation"] == "108344843"
    return httpx.Response(200, text=ONVISTA_EOD)


class _Listing:
    def __init__(self, isin, venue, quote_currency, instrument_id=7):
        self.instrument_id = instrument_id
        self.isin = isin
        self.venue = venue
        self.quote_currency = quote_currency


def test_onvista_resolves_an_identifier_to_its_markets_deduplicated():
    from open_leprechaun.ports.security_resolution import ResolvedListing

    resolved = _onvista(_market_handler).listings("IE00B4L5Y983")

    assert resolved == [
        ResolvedListing(venue="Xetra", quote_currency="EUR"),
        ResolvedListing(venue="gettex", quote_currency="EUR"),
        ResolvedListing(venue="London Stock Exchange", quote_currency="USD"),
    ]


def test_onvista_answers_no_listings_for_an_unknown_identifier():
    assert _onvista(_market_handler).listings("XX0000000000") == []


def test_onvista_quotes_the_listings_market_alone():
    """The quote comes from the quoteList entry matching the Listing's venue
    and currency — one market's answer, not whichever onvista prefers."""
    quotes = _onvista(_market_handler).quotes([_Listing("IE00B4L5Y983", "Xetra", "EUR")])

    (quote,) = quotes
    assert quote.instrument_id == 7
    assert quote.price == Decimal("128.75")
    assert quote.currency == "EUR"
    assert quote.venue == "Xetra"
    assert quote.as_of == datetime(2026, 8, 11, 15, 31, tzinfo=UTC)


def test_onvista_matches_the_venue_case_insensitively():
    """A hand-entered "XETRA" must find onvista's "Xetra" — a casing
    difference silently never matching would leave a security unpriced with
    no visible reason."""
    quotes = _onvista(_market_handler).quotes([_Listing("IE00B4L5Y983", "XETRA", "EUR")])

    (quote,) = quotes
    assert quote.price == Decimal("128.75")


def test_onvista_passes_over_a_listing_it_cannot_match():
    """An unknown ISIN or a venue the snapshot does not carry is absent from
    the answer — not covered here is a normal answer, never an invention."""
    quotes = _onvista(_market_handler).quotes(
        [
            _Listing("XX0000000000", "Xetra", "EUR"),
            _Listing("IE00B4L5Y983", "NYSE", "USD"),
        ]
    )

    assert quotes == []


def test_onvista_fetches_daily_closes_by_the_listings_notation():
    closes = _onvista(_market_handler).daily_closes(
        _Listing("IE00B4L5Y983", "Xetra", "EUR"),
        date(2026, 8, 5),
        date(2026, 8, 6),
    )

    assert closes == [
        DailyClose(close_date=date(2026, 8, 5), price=Decimal("128.05"), currency="EUR"),
        DailyClose(close_date=date(2026, 8, 6), price=Decimal("128.65"), currency="EUR"),
    ]


def test_onvista_clips_closes_to_the_requested_range():
    closes = _onvista(_market_handler).daily_closes(
        _Listing("IE00B4L5Y983", "Xetra", "EUR"),
        date(2026, 8, 6),
        date(2026, 8, 6),
    )

    assert [close.close_date for close in closes] == [date(2026, 8, 6)]


def test_onvista_market_data_surfaces_a_rate_limit_as_its_own_condition():
    import httpx

    with pytest.raises(RateLimitedError):
        _onvista(lambda request: httpx.Response(429)).quotes(
            [_Listing("IE00B4L5Y983", "Xetra", "EUR")]
        )


def test_onvista_market_data_surfaces_any_other_failure_as_an_outage():
    import httpx

    with pytest.raises(ProviderOutageError):
        _onvista(lambda request: httpx.Response(500)).listings("IE00B4L5Y983")

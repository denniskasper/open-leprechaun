"""FX conversion by reference rate (ticket 17): every foreign-currency amount
converts to EUR by the euro reference rate of the event date, and the
conversion is reproducible years later because the rate and the date it
represents are stored and never overwritten.

The seams are the schema over real Postgres, the repository over the stored
rates, the conversion service driven through a fake of the reference-rate
port, and the ECB implementation against a recorded response.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from open_leprechaun.ports.ecb import EcbReferenceRateSource
from open_leprechaun.ports.reference_rates import ReferenceRate
from open_leprechaun.repositories import instruments, reference_rates
from open_leprechaun.services import fx


class FakeReferenceRateSource:
    """The port's fake: whatever rates the test hands it, answered per query
    window — and replaceable mid-test, which is how reproducibility is proven."""

    def __init__(self, rates=()):
        self.rates = list(rates)

    def daily_rates(self, currency, start, end):
        return [
            rate
            for rate in self.rates
            if rate.currency == currency and start <= rate.rate_date <= end
        ]


def _noon_utc(year, month, day):
    """An instant safely inside the same Berlin calendar date."""
    return datetime(year, month, day, 12, 0, tzinfo=UTC)


@pytest.fixture
def fx_db(db):
    """The migrated database with no stored rates — rates outlive the shared
    `db` fixture, which resets only the ledger's tables."""
    with db.begin() as connection:
        connection.execute(text("DELETE FROM reference_rate"))
    return db


def _insert_rate(engine, *, currency="USD", rate_date="2026-01-07", rate=Decimal("1.25")):
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO reference_rate (currency, rate_date, rate)"
                " VALUES (:currency, :rate_date, :rate)"
            ),
            {"currency": currency, "rate_date": rate_date, "rate": rate},
        )


# --- The schema is the arbiter ----------------------------------------------


def test_the_schema_refuses_a_non_positive_rate(fx_db):
    with pytest.raises(IntegrityError):
        _insert_rate(fx_db, rate=Decimal("0"))


def test_the_schema_holds_one_rate_per_currency_and_date(fx_db):
    _insert_rate(fx_db, rate=Decimal("1.25"))
    with pytest.raises(IntegrityError):
        _insert_rate(fx_db, rate=Decimal("1.30"))


def test_the_schema_refuses_a_rate_for_the_euro_itself(fx_db):
    with pytest.raises(IntegrityError):
        _insert_rate(fx_db, currency="EUR")


def test_the_schema_refuses_a_currency_that_is_not_an_uppercase_code(fx_db):
    with pytest.raises(IntegrityError):
        _insert_rate(fx_db, currency="usd")


def test_the_schema_keeps_the_peg_to_the_crypto_family(fx_db):
    with fx_db.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO instrument (family, type, symbol, name, pegged_currency)"
                " VALUES ('cash', 'fiat', 'USD', 'US Dollar', 'USD')"
            )
        )


def test_the_schema_refuses_a_peg_that_is_not_an_uppercase_code(fx_db):
    with fx_db.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO instrument"
                " (family, type, symbol, name, chain, contract_address, pegged_currency)"
                " VALUES ('crypto', 'token', 'USDT', 'Tether USD', 'ethereum', '0xdac1',"
                " 'usd')"
            )
        )


# --- Conversion uses the event date's rate ----------------------------------


def test_conversion_uses_the_rate_of_the_event_date_not_a_later_one(fx_db):
    """2026-01-07 was a Wednesday; a later rate exists, as it always will by
    report time, and must not be the one used."""
    source = FakeReferenceRateSource(
        [
            ReferenceRate("USD", date(2026, 1, 7), Decimal("1.25")),
            ReferenceRate("USD", date(2026, 1, 8), Decimal("2.00")),
        ]
    )

    converted = fx.convert(
        fx_db, source, amount=Decimal("100"), currency="USD", at=_noon_utc(2026, 1, 7)
    )

    assert converted.amount_eur == Decimal("80")
    assert converted.rate == Decimal("1.25")
    assert converted.rate_date == date(2026, 1, 7)


def test_a_weekend_date_resolves_to_the_most_recent_publication_before_it(fx_db):
    """2026-01-10 was a Saturday — no publication; Friday the 9th's rate is
    the documented resolution, and the stored rate_date says so honestly."""
    source = FakeReferenceRateSource(
        [
            ReferenceRate("USD", date(2026, 1, 8), Decimal("2.00")),
            ReferenceRate("USD", date(2026, 1, 9), Decimal("1.25")),
        ]
    )

    converted = fx.convert(
        fx_db, source, amount=Decimal("100"), currency="USD", at=_noon_utc(2026, 1, 10)
    )

    assert converted.amount_eur == Decimal("80")
    assert converted.rate_date == date(2026, 1, 9)


def test_a_stored_neighbouring_rate_does_not_stand_in_for_the_event_dates_own(fx_db):
    """A Thursday conversion leaves Thursday's rate in the store; a Friday
    event must still fetch and use Friday's own publication — the fallback is
    for dates with no publication, never a way to skip one that exists."""
    source = FakeReferenceRateSource([ReferenceRate("USD", date(2026, 1, 8), Decimal("2.00"))])
    fx.convert(fx_db, source, amount=Decimal("1"), currency="USD", at=_noon_utc(2026, 1, 8))

    source.rates.append(ReferenceRate("USD", date(2026, 1, 9), Decimal("1.25")))
    converted = fx.convert(
        fx_db, source, amount=Decimal("100"), currency="USD", at=_noon_utc(2026, 1, 9)
    )

    assert converted.amount_eur == Decimal("80")
    assert converted.rate_date == date(2026, 1, 9)


def test_a_resolved_absence_is_not_refetched(fx_db):
    """The first weekend conversion learns Saturday has no publication; the
    second answers from the store even if the source has since changed —
    reproducibility covers resolved absences too."""
    source = FakeReferenceRateSource([ReferenceRate("USD", date(2026, 1, 9), Decimal("1.25"))])
    fx.convert(fx_db, source, amount=Decimal("1"), currency="USD", at=_noon_utc(2026, 1, 10))

    source.rates = [ReferenceRate("USD", date(2026, 1, 10), Decimal("9.99"))]
    converted = fx.convert(
        fx_db, source, amount=Decimal("100"), currency="USD", at=_noon_utc(2026, 1, 10)
    )

    assert converted.amount_eur == Decimal("80")
    assert converted.rate_date == date(2026, 1, 9)


def test_a_gap_beyond_the_lookback_is_an_error_naming_currency_and_date(fx_db):
    source = FakeReferenceRateSource([ReferenceRate("USD", date(2026, 1, 10), Decimal("1.25"))])

    with pytest.raises(fx.RateUnavailableError, match=r"USD.*2026-01-20"):
        fx.convert(fx_db, source, amount=Decimal("100"), currency="USD", at=_noon_utc(2026, 1, 20))


def test_rerunning_a_conversion_reproduces_the_same_figure_exactly(fx_db):
    """Once a conversion has been made, the source may say anything — the
    stored rate answers, and the figure is bit-for-bit the same."""
    source = FakeReferenceRateSource([ReferenceRate("USD", date(2026, 1, 7), Decimal("1.17"))])
    first = fx.convert(
        fx_db, source, amount=Decimal("123.456789"), currency="USD", at=_noon_utc(2026, 1, 7)
    )

    source.rates = [ReferenceRate("USD", date(2026, 1, 7), Decimal("9.99"))]
    second = fx.convert(
        fx_db, source, amount=Decimal("123.456789"), currency="USD", at=_noon_utc(2026, 1, 7)
    )

    assert second == first


def test_the_event_date_is_the_berlin_date_of_the_instant(fx_db):
    """23:30 UTC on the 7th is already the 8th in Berlin — the same clock
    that buckets tax years decides which day's rate applies."""
    source = FakeReferenceRateSource(
        [
            ReferenceRate("USD", date(2026, 1, 7), Decimal("1.25")),
            ReferenceRate("USD", date(2026, 1, 8), Decimal("2.00")),
        ]
    )

    converted = fx.convert(
        fx_db,
        source,
        amount=Decimal("100"),
        currency="USD",
        at=datetime(2026, 1, 7, 23, 30, tzinfo=UTC),
    )

    assert converted.rate_date == date(2026, 1, 8)
    assert converted.amount_eur == Decimal("50")


def test_a_naive_instant_is_refused(fx_db):
    with pytest.raises(ValueError, match="timezone-aware"):
        fx.convert(
            fx_db,
            FakeReferenceRateSource(),
            amount=Decimal("1"),
            currency="USD",
            at=datetime(2026, 1, 7, 12, 0),
        )


def test_the_euro_converts_by_identity_without_a_source(fx_db):
    converted = fx.convert(
        fx_db,
        FakeReferenceRateSource(),
        amount=Decimal("42.42"),
        currency="EUR",
        at=_noon_utc(2026, 1, 10),
    )

    assert converted.amount_eur == Decimal("42.42")
    assert converted.rate == Decimal("1")


# --- Stablecoins route through the reference rate ----------------------------


def test_a_stablecoin_names_the_currency_whose_reference_rate_values_it(fx_db):
    instrument_id = instruments.create_crypto_token(
        fx_db,
        symbol="USDT",
        name="Tether USD",
        chain="ethereum",
        contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7",
        pegged_currency="USD",
    )
    row = instruments.get(fx_db, instrument_id)

    assert fx.reference_rate_currency(row) == "USD"


def test_an_unpegged_instrument_routes_to_no_reference_rate(fx_db):
    instrument_id = instruments.create_native_coin(
        fx_db, symbol="BTC", name="Bitcoin", chain="bitcoin"
    )
    row = instruments.get(fx_db, instrument_id)

    assert fx.reference_rate_currency(row) is None


def test_a_stablecoin_balance_gets_its_eur_value_from_the_daily_reference_rate(fx_db):
    """The whole point of the peg: value the balance through the pegged
    currency's reference rate, never a crypto price provider."""
    instrument_id = instruments.create_crypto_token(
        fx_db,
        symbol="USDT",
        name="Tether USD",
        chain="ethereum",
        contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7",
        pegged_currency="USD",
    )
    row = instruments.get(fx_db, instrument_id)
    source = FakeReferenceRateSource([ReferenceRate("USD", date(2026, 1, 7), Decimal("1.25"))])

    converted = fx.convert(
        fx_db,
        source,
        amount=Decimal("100"),
        currency=fx.reference_rate_currency(row),
        at=_noon_utc(2026, 1, 7),
    )

    assert converted.amount_eur == Decimal("80")


# --- The stored rates are immutable -----------------------------------------


def test_a_stored_rate_is_never_overwritten(fx_db):
    """Reproducibility rests here: once a rate has been used, no re-fetch —
    however the source has since revised itself — may change it."""
    reference_rates.store(fx_db, [ReferenceRate("USD", date(2026, 1, 7), Decimal("1.25"))])
    reference_rates.store(fx_db, [ReferenceRate("USD", date(2026, 1, 7), Decimal("9.99"))])

    row = reference_rates.latest_on_or_before(
        fx_db, currency="USD", on=date(2026, 1, 7), floor=date(2026, 1, 1)
    )
    assert row.rate == Decimal("1.25")
    assert row.rate_date == date(2026, 1, 7)


def test_the_lookup_answers_the_latest_rate_on_or_before_the_date(fx_db):
    reference_rates.store(
        fx_db,
        [
            ReferenceRate("USD", date(2026, 1, 8), Decimal("1.20")),
            ReferenceRate("USD", date(2026, 1, 9), Decimal("1.25")),
            ReferenceRate("USD", date(2026, 1, 12), Decimal("1.30")),
        ],
    )

    row = reference_rates.latest_on_or_before(
        fx_db, currency="USD", on=date(2026, 1, 11), floor=date(2026, 1, 4)
    )
    assert row.rate_date == date(2026, 1, 9)


def test_the_lookup_answers_none_below_the_floor(fx_db):
    reference_rates.store(fx_db, [ReferenceRate("USD", date(2026, 1, 2), Decimal("1.25"))])

    row = reference_rates.latest_on_or_before(
        fx_db, currency="USD", on=date(2026, 1, 11), floor=date(2026, 1, 4)
    )
    assert row is None


# --- The ECB implementation, against a recorded response ---------------------

# A trimmed but structurally faithful SDMX `csvdata` answer for
# EXR/D.USD.EUR.SP00.A — Friday the 9th, then Monday the 12th; the weekend
# simply has no rows, which is how the ECB says "no publication".
RECORDED_CSV = (
    "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"
    "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-01-08,1.1706\n"
    "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-01-09,1.1712\n"
    "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-01-12,1.1698\n"
)


def _ecb_source(handler):
    return EcbReferenceRateSource(httpx.Client(transport=httpx.MockTransport(handler)))


def test_the_ecb_source_answers_the_published_rates_as_published():
    def handler(request):
        assert request.url.path.endswith("/EXR/D.USD.EUR.SP00.A")
        assert request.url.params["startPeriod"] == "2026-01-08"
        assert request.url.params["endPeriod"] == "2026-01-12"
        return httpx.Response(200, text=RECORDED_CSV)

    rates = _ecb_source(handler).daily_rates("USD", date(2026, 1, 8), date(2026, 1, 12))

    assert rates == [
        ReferenceRate("USD", date(2026, 1, 8), Decimal("1.1706")),
        ReferenceRate("USD", date(2026, 1, 9), Decimal("1.1712")),
        ReferenceRate("USD", date(2026, 1, 12), Decimal("1.1698")),
    ]


def test_the_ecb_source_answers_nothing_when_the_period_has_no_data():
    """The data API says 404 for an empty result; that is an absence of
    publications, not an outage — the conversion service names the gap."""
    rates = _ecb_source(lambda request: httpx.Response(404)).daily_rates(
        "USD", date(2026, 1, 10), date(2026, 1, 11)
    )

    assert rates == []


def test_the_ecb_source_raises_on_an_outage():
    with pytest.raises(httpx.HTTPStatusError):
        _ecb_source(lambda request: httpx.Response(503)).daily_rates(
            "USD", date(2026, 1, 8), date(2026, 1, 12)
        )

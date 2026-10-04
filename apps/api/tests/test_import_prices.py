"""Historical price resolution on import (ticket 41): a committed row that
states no price of its own gets the close of its day through the provider
chain, stored with the provider that answered and the day it represents — and
a row nothing could price is listed in the import result, never valued at
zero.

The seams are the framework's own commit with fakes of the price and
reference-rate ports, the valuation rule the tax engines share
(`fx.value_eur`, read through the §22 year report), the input fingerprint,
and the HTTP commit endpoint.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.ports.crypto_prices import DailyClose, ProviderOutageError, RateLimitedError
from open_leprechaun.ports.reference_rates import ReferenceRate
from open_leprechaun.prices import get_crypto_price_chain
from open_leprechaun.rates import get_reference_rate_source
from open_leprechaun.repositories import crypto_prices as stored_prices
from open_leprechaun.repositories import fingerprints, instruments, platforms, stances
from open_leprechaun.services import import_prices, section22
from open_leprechaun.services.import_prices import PriceSources
from open_leprechaun.services.imports import ImportLeg, ImportRow, InstrumentSpec, commit
from open_leprechaun.services.price_reports import ProviderCondition

RECEIVED = datetime(2025, 3, 14, 12, 0, tzinfo=UTC)
DAY = RECEIVED.date()
SOURCE = "kraken-csv"

SOL = InstrumentSpec(kind="native", symbol="SOL", name="Solana", chain="solana")
ETH = InstrumentSpec(kind="native", symbol="ETH", name="Ether", chain="ethereum")


class FakeCryptoPriceProvider:
    """The port's fake: closes keyed by symbol, or a failure the test
    chooses. Every history request is kept, so a test can say what the
    resolution asked for — and what it never needed to."""

    def __init__(self, name, closes_by_symbol=None, fails_with=None):
        self.name = name
        self.closes_by_symbol = closes_by_symbol or {}
        self.fails_with = fails_with
        self.asked = []

    def quotes(self, instruments):
        return []

    def daily_closes(self, instrument, start, end):
        self.asked.append((instrument.symbol, start, end))
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


def _sources(*providers, rates=()):
    return PriceSources(providers=providers, rate_source=FakeReferenceRateSource(rates))


def _account(db):
    platform_id = platforms.create_platform(db, name="Kraken", kind="exchange")
    return platforms.create_account(db, platform_id, name="Main")


def _reward(external_id, spec=SOL, *, occurred_at=RECEIVED, quantity="2"):
    return ImportRow(
        external_id=external_id,
        type="staking_reward",
        occurred_at=occurred_at,
        legs=(ImportLeg(role="in", quantity=Decimal(quantity), instrument=spec),),
    )


def _commit(db, sources, account, rows):
    return commit(
        db, prices=sources, source=SOURCE, label="export.csv", account_id=account, rows=rows
    )


def _instrument_id(db, symbol):
    with db.connect() as connection:
        return connection.execute(
            text("SELECT id FROM instrument WHERE symbol = :symbol"), {"symbol": symbol}
        ).scalar_one()


def _closes(db, symbol):
    return [
        (row.close_date, row.price_eur, row.source)
        for row in stored_prices.daily_closes(
            db, _instrument_id(db, symbol), start=date(2000, 1, 1), end=date(2100, 1, 1)
        )
    ]


def _unpriced(committed):
    """The unpriced rows as (external id, symbols) — the ids are the
    database's to choose."""
    return [
        (row.external_id, [instrument.symbol for instrument in row.instruments])
        for row in committed.unpriced
    ]


def _eur_close(day, price):
    return DailyClose(close_date=day, price=Decimal(price), currency="EUR")


# --- Resolution on commit ----------------------------------------------------


def test_a_committed_row_gets_the_close_of_its_own_day(db):
    """The price that applied at the row's timestamp, not today's: the close
    of the day the event happened, kept with the provider that answered and
    the day it represents."""
    account = _account(db)
    provider = FakeCryptoPriceProvider("coingecko", {"SOL": [_eur_close(DAY, "120.50")]})

    committed = _commit(db, _sources(provider), account, [_reward("r-1")])

    assert committed.created == 1
    assert committed.unpriced == ()
    assert _closes(db, "SOL") == [(DAY, Decimal("120.50"), "coingecko")]


def test_a_row_stating_its_own_price_asks_no_provider(db):
    """A purchase for euros carries its price in its own legs: the
    reference-rate universe values the cash side, so nothing is fetched and
    nothing is flagged."""
    account = _account(db)
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    provider = FakeCryptoPriceProvider("coingecko")
    purchase = ImportRow(
        external_id="t-1",
        type="trade",
        occurred_at=RECEIVED,
        legs=(
            ImportLeg(role="out", quantity=Decimal("100"), instrument_id=eur),
            ImportLeg(role="in", quantity=Decimal("1"), instrument=SOL),
        ),
    )

    committed = _commit(db, _sources(provider), account, [purchase])

    assert provider.asked == []
    assert committed.unpriced == ()


def test_a_fee_paid_in_a_coin_wants_its_close_even_beside_a_stated_price(db):
    """The exchanged sides state their price, but the fee is a cost of its
    own in a coin only the chain can value."""
    account = _account(db)
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    provider = FakeCryptoPriceProvider("coingecko", {"ETH": [_eur_close(DAY, "1800")]})
    purchase = ImportRow(
        external_id="t-1",
        type="trade",
        occurred_at=RECEIVED,
        legs=(
            ImportLeg(role="out", quantity=Decimal("100"), instrument_id=eur),
            ImportLeg(role="in", quantity=Decimal("1"), instrument=SOL),
            ImportLeg(role="fee", quantity=Decimal("0.001"), instrument=ETH, charged_against=1),
        ),
    )

    committed = _commit(db, _sources(provider), account, [purchase])

    assert provider.asked == [("ETH", DAY, DAY)]
    assert committed.unpriced == ()
    assert _closes(db, "ETH") == [(DAY, Decimal("1800"), "coingecko")]


def test_a_crypto_for_crypto_trade_wants_both_closes(db):
    account = _account(db)
    provider = FakeCryptoPriceProvider(
        "coingecko", {"SOL": [_eur_close(DAY, "120")], "ETH": [_eur_close(DAY, "1800")]}
    )
    swap = ImportRow(
        external_id="t-1",
        type="trade",
        occurred_at=RECEIVED,
        legs=(
            ImportLeg(role="out", quantity=Decimal("15"), instrument=SOL),
            ImportLeg(role="in", quantity=Decimal("1"), instrument=ETH),
        ),
    )

    committed = _commit(db, _sources(provider), account, [swap])

    assert committed.unpriced == ()
    assert _closes(db, "SOL") == [(DAY, Decimal("120"), "coingecko")]
    assert _closes(db, "ETH") == [(DAY, Decimal("1800"), "coingecko")]


def test_a_row_nothing_prices_is_listed_and_never_valued_at_zero(db):
    """The gap is visible instead of wrong: the row lands, is named in the
    import result with the Instrument nothing priced, and no close — least of
    all a zero — is stored for it."""
    account = _account(db)
    provider = FakeCryptoPriceProvider("coingecko")

    committed = _commit(db, _sources(provider), account, [_reward("r-1"), _reward("r-2", ETH)])

    assert committed.created == 2
    assert _unpriced(committed) == [("r-1", ["SOL"]), ("r-2", ["ETH"])]
    assert committed.price_conditions == ()
    assert _closes(db, "SOL") == []


def test_a_provider_answering_zero_is_no_answer(db):
    """Some providers answer 0 for a dead token. Zero is a statement about
    value: the row is unknown, never immaterial — flagged, with no close."""
    account = _account(db)
    provider = FakeCryptoPriceProvider("defillama", {"SOL": [_eur_close(DAY, "0")]})

    committed = _commit(db, _sources(provider), account, [_reward("r-1")])

    assert _unpriced(committed) == [("r-1", ["SOL"])]
    assert _closes(db, "SOL") == []


def test_a_day_one_provider_leaves_open_falls_through_to_the_next(db):
    """The chain's rule, per day: the primary's history covers one of two
    days, and only the open day is asked of the fallback."""
    account = _account(db)
    later = datetime(2025, 3, 20, 9, 0, tzinfo=UTC)
    primary = FakeCryptoPriceProvider("coingecko", {"SOL": [_eur_close(DAY, "120")]})
    fallback = FakeCryptoPriceProvider(
        "defillama", {"SOL": [_eur_close(DAY, "999"), _eur_close(later.date(), "130")]}
    )

    committed = _commit(
        db,
        _sources(primary, fallback),
        account,
        [_reward("r-1"), _reward("r-2", occurred_at=later)],
    )

    assert committed.unpriced == ()
    assert primary.asked == [("SOL", DAY, later.date())]
    assert fallback.asked == [("SOL", later.date(), later.date())]
    assert _closes(db, "SOL") == [
        (DAY, Decimal("120"), "coingecko"),
        (later.date(), Decimal("130"), "defillama"),
    ]


def test_a_close_quoted_in_dollars_converts_by_its_own_days_reference_rate(db):
    account = _account(db)
    provider = FakeCryptoPriceProvider(
        "defillama", {"SOL": [DailyClose(close_date=DAY, price=Decimal("125"), currency="USD")]}
    )
    rates = [ReferenceRate(currency="USD", rate_date=DAY, rate=Decimal("1.25"))]

    committed = _commit(db, _sources(provider, rates=rates), account, [_reward("r-1")])

    assert committed.unpriced == ()
    assert _closes(db, "SOL") == [(DAY, Decimal("100"), "defillama")]


def test_the_event_day_is_the_utc_day_of_its_instant(db):
    """Providers bucket history by UTC day, so the close containing an event
    just after Berlin midnight is the previous UTC day's."""
    account = _account(db)
    berlin_small_hours = datetime(2025, 3, 14, 23, 30, tzinfo=UTC)
    provider = FakeCryptoPriceProvider("coingecko", {"SOL": [_eur_close(DAY, "120")]})

    committed = _commit(
        db, _sources(provider), account, [_reward("r-1", occurred_at=berlin_small_hours)]
    )

    assert provider.asked == [("SOL", DAY, DAY)]
    assert committed.unpriced == ()


def test_a_rate_limit_is_named_and_the_provider_is_not_asked_again(db):
    """A rate limit is the provider's word for the whole run and its own
    named condition; the import itself still lands whole."""
    account = _account(db)
    limited = FakeCryptoPriceProvider("coingecko", fails_with=RateLimitedError("pause"))
    fallback = FakeCryptoPriceProvider("defillama", {"SOL": [_eur_close(DAY, "120")]})

    committed = _commit(
        db, _sources(limited, fallback), account, [_reward("r-1"), _reward("r-2", ETH)]
    )

    assert committed.created == 2
    assert len(limited.asked) == 1
    assert committed.price_conditions == (ProviderCondition("coingecko", "rate_limited"),)
    assert _unpriced(committed) == [("r-2", ["ETH"])]


def test_an_outage_is_named_once_and_costs_no_import(db):
    account = _account(db)
    down = FakeCryptoPriceProvider("coingecko", fails_with=ProviderOutageError("down"))

    committed = _commit(db, _sources(down), account, [_reward("r-1"), _reward("r-2", ETH)])

    assert committed.created == 2
    assert committed.price_conditions == (ProviderCondition("coingecko", "outage"),)
    assert [row.external_id for row in committed.unpriced] == ["r-1", "r-2"]


def test_a_stored_close_is_not_fetched_again(db):
    """First stored wins: a day the store already answers costs no request,
    and cannot shift under a figure already stated."""
    account = _account(db)
    sol = instruments.create_native_coin(db, symbol="SOL", name="Solana", chain="solana")
    stored_prices.store_daily_closes(db, sol, source="coingecko", closes=[(DAY, Decimal("120"))])
    provider = FakeCryptoPriceProvider("defillama", {"SOL": [_eur_close(DAY, "999")]})

    committed = _commit(db, _sources(provider), account, [_reward("r-1")])

    assert provider.asked == []
    assert committed.unpriced == ()
    assert _closes(db, "SOL") == [(DAY, Decimal("120"), "coingecko")]


def test_what_the_chain_never_prices_is_neither_asked_nor_flagged(db):
    """A stablecoin is valued by its peg's reference rate (ADR-0017) and a
    dangerous Instrument may never acquire a price (ADR-0012): neither is a
    gap, so neither is listed."""
    account = _account(db)
    usdt = instruments.create_crypto_token(
        db,
        symbol="USDT",
        name="Tether",
        chain="ethereum",
        contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7",
        pegged_currency="USD",
    )
    scam = instruments.create_crypto_token(
        db, symbol="SCAM", name="Scam", chain="ethereum", contract_address="0xdead"
    )
    stances.classify(db, scam, stance="dangerous")
    provider = FakeCryptoPriceProvider("coingecko")
    rows = [
        ImportRow(
            external_id=f"r-{instrument}",
            type="transfer_in",
            occurred_at=RECEIVED,
            legs=(ImportLeg(role="in", quantity=Decimal("5"), instrument_id=instrument),),
        )
        for instrument in (usdt, scam)
    ]

    committed = _commit(db, _sources(provider), account, rows)

    assert committed.created == 2
    assert provider.asked == []
    assert committed.unpriced == ()


def test_a_pure_re_import_resolves_nothing(db):
    account = _account(db)
    provider = FakeCryptoPriceProvider("coingecko")
    _commit(db, _sources(provider), account, [_reward("r-1")])
    provider.asked.clear()

    again = _commit(db, _sources(provider), account, [_reward("r-1")])

    assert again.batch_id is None
    assert provider.asked == []
    assert again.unpriced == ()


def test_several_positions_bought_for_one_sum_want_their_closes(db):
    """One sum of euros against two coins states no price for either: the
    split needs their relative market values, so both are priced."""
    account = _account(db)
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    provider = FakeCryptoPriceProvider(
        "coingecko", {"SOL": [_eur_close(DAY, "120")], "ETH": [_eur_close(DAY, "1800")]}
    )
    basket = ImportRow(
        external_id="t-1",
        type="trade",
        occurred_at=RECEIVED,
        legs=(
            ImportLeg(role="out", quantity=Decimal("1920"), instrument_id=eur),
            ImportLeg(role="in", quantity=Decimal("1"), instrument=SOL),
            ImportLeg(role="in", quantity=Decimal("1"), instrument=ETH),
        ),
    )

    committed = _commit(db, _sources(provider), account, [basket])

    assert committed.unpriced == ()
    assert sorted(symbol for symbol, _, _ in provider.asked) == ["ETH", "SOL"]


def test_a_day_not_yet_over_has_no_close(db):
    """The first stored close wins forever, so a provider's latest intraday
    point must never be frozen as today's close: an event of today awaits."""
    account = _account(db)
    now = datetime.now(UTC)
    provider = FakeCryptoPriceProvider("coingecko", {"SOL": [_eur_close(now.date(), "120")]})

    committed = _commit(db, _sources(provider), account, [_reward("r-1", occurred_at=now)])

    assert _unpriced(committed) == [("r-1", ["SOL"])]
    assert _closes(db, "SOL") == []


def test_whatever_a_provider_raises_is_its_outage_never_the_imports(db):
    """The batch has landed by the time prices are asked for: a malformed
    answer leaves rows unpriced under a named condition, and the next
    provider is still asked."""
    account = _account(db)
    broken = FakeCryptoPriceProvider("coingecko", fails_with=KeyError("timestamp"))
    fallback = FakeCryptoPriceProvider("defillama", {"SOL": [_eur_close(DAY, "120")]})

    committed = _commit(db, _sources(broken, fallback), account, [_reward("r-1")])

    assert committed.created == 1
    assert committed.unpriced == ()
    assert committed.price_conditions == (ProviderCondition("coingecko", "outage"),)


def test_a_provider_that_keeps_failing_is_not_asked_for_every_instrument(db):
    """One failure may be an Instrument the provider does not know; a run of
    them is the provider being down, and costs no timeout per Instrument."""
    account = _account(db)
    down = FakeCryptoPriceProvider("coingecko", fails_with=ProviderOutageError("down"))
    rows = [
        _reward(
            f"r-{index}",
            InstrumentSpec(kind="native", symbol=f"C{index}", name=f"Coin {index}", chain="x"),
        )
        for index in range(5)
    ]

    committed = _commit(db, _sources(down), account, rows)

    assert len(committed.unpriced) == 5
    assert len(down.asked) == 3


def test_a_gap_an_import_left_is_settled_by_resolving_the_ledger(db):
    """The flag is the absence of a close: once a provider can answer, the
    same resolution over the whole ledger — what the scheduled price update
    runs — settles the row with nothing re-imported."""
    account = _account(db)
    limited = FakeCryptoPriceProvider("coingecko", fails_with=RateLimitedError("pause"))
    assert _unpriced(_commit(db, _sources(limited), account, [_reward("r-1")])) == [
        ("r-1", ["SOL"])
    ]
    recovered = FakeCryptoPriceProvider("coingecko", {"SOL": [_eur_close(DAY, "120")]})

    conditions = import_prices.resolve_ledger(db, _sources(recovered))

    assert conditions == ()
    assert _closes(db, "SOL") == [(DAY, Decimal("120"), "coingecko")]


# --- The resolved price is what values the event -----------------------------


def _kept_sol(db, account):
    sol = instruments.create_native_coin(db, symbol="SOL", name="Solana", chain="solana")
    stances.classify(db, sol, stance="kept", account_id=account)
    return sol


def test_imported_income_is_valued_at_the_price_of_its_own_day(db):
    """§22 income at market value on receipt: the quantity times the close
    of the day it arrived — real, rather than backfilled from today."""
    account = _account(db)
    _kept_sol(db, account)
    provider = FakeCryptoPriceProvider("coingecko", {"SOL": [_eur_close(DAY, "120.50")]})
    _commit(db, _sources(provider), account, [_reward("r-1", quantity="2")])

    report = section22.year_report(db, FakeReferenceRateSource(), year=2025)

    (event,) = report.incomes
    assert event.market_value_eur == Decimal("241.00")
    assert report.awaiting_valuation == ()
    assert report.total_income_eur == Decimal("241.00")


def test_income_nothing_prices_awaits_valuation_and_is_never_immaterial(db):
    """An inflow nothing prices is unknown: it stays in the year as an
    income awaiting valuation, and the year states no total around it —
    never a zero that would read as below any limit."""
    account = _account(db)
    _kept_sol(db, account)
    provider = FakeCryptoPriceProvider("coingecko", {"SOL": [_eur_close(DAY, "0")]})
    _commit(db, _sources(provider), account, [_reward("r-1")])

    report = section22.year_report(db, FakeReferenceRateSource(), year=2025)

    (event,) = report.incomes
    assert event.market_value_eur is None
    assert report.awaiting_valuation == (event.leg_id,)
    assert report.total_income_eur is None
    assert report.freigrenze is None


def test_a_close_an_event_rests_on_is_a_fingerprinted_input(db):
    """A close arriving for a day an event happened turns an awaited figure
    into a stated one, so everything stamped before it is detectably stale;
    a close for a day nothing happened on moves no figure and drifts
    nothing."""
    account = _account(db)
    sol = _kept_sol(db, account)
    _commit(db, _sources(FakeCryptoPriceProvider("coingecko")), account, [_reward("r-1")])
    with db.connect() as connection:
        before = fingerprints.current(connection)

    stored_prices.store_daily_closes(
        db, sol, source="coingecko", closes=[(date(2025, 1, 1), Decimal("90"))]
    )
    with db.connect() as connection:
        assert fingerprints.drifted(before, fingerprints.current(connection)) == []

    stored_prices.store_daily_closes(db, sol, source="coingecko", closes=[(DAY, Decimal("120"))])
    with db.connect() as connection:
        (drift,) = fingerprints.drifted(before, fingerprints.current(connection))
    assert drift.input_class == "rates"


# --- The import result over HTTP ----------------------------------------------


@pytest.fixture
def priced_client(db):
    """The API bound to the test database, prices through fakes of both
    ports — the chain is the list the test fills."""
    chain: list = []
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_crypto_price_chain] = lambda: chain
    app.dependency_overrides[get_reference_rate_source] = FakeReferenceRateSource
    with TestClient(app) as client:
        client.chain = chain
        yield client


def _reward_payload(external_id, symbol, name, chain):
    return {
        "external_id": external_id,
        "type": "staking_reward",
        "occurred_at": RECEIVED.isoformat(),
        "legs": [
            {
                "role": "in",
                "quantity": "2",
                "instrument": {"kind": "native", "symbol": symbol, "name": name, "chain": chain},
            }
        ],
    }


def test_the_import_result_lists_the_rows_nothing_priced(db, priced_client):
    """Unresolvable rows are listed in the import result — by the
    identifier the venue gave them and the Instrument nothing priced —
    beside what the failing provider's failure was."""
    account = _account(db)
    priced_client.chain += [
        FakeCryptoPriceProvider("coingecko", fails_with=RateLimitedError("pause")),
        FakeCryptoPriceProvider("defillama", {"SOL": [_eur_close(DAY, "120.50")]}),
    ]

    committed = priced_client.post(
        "/api/imports",
        json={
            "source": SOURCE,
            "account_id": account,
            "label": "export.csv",
            "rows": [
                _reward_payload("r-1", "SOL", "Solana", "solana"),
                _reward_payload("r-2", "ETH", "Ether", "ethereum"),
            ],
        },
    )

    assert committed.status_code == 201
    body = committed.json()
    assert body["created"] == 2
    assert body["unpriced"] == [
        {
            "external_id": "r-2",
            "instruments": [{"instrument_id": _instrument_id(db, "ETH"), "symbol": "ETH"}],
        }
    ]
    assert body["price_conditions"] == [{"provider": "coingecko", "condition": "rate_limited"}]

    closes = priced_client.get(
        f"/api/prices/crypto/{_instrument_id(db, 'SOL')}/closes",
        params={"start": DAY.isoformat(), "end": DAY.isoformat()},
    )
    assert closes.json() == [
        {"close_date": DAY.isoformat(), "price_eur": "120.50", "source": "defillama"}
    ]

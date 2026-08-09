"""Holdings (ticket 20): one view of everything held, its cost basis read
from the Tax Lot derivation — never summed from inflows — and its values
stated only where the store can state them: stored crypto prices and daily
reference rates, no provider I/O on the request path."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.ports.reference_rates import ReferenceRate
from open_leprechaun.rates import get_reference_rate_source
from open_leprechaun.repositories import crypto_prices as crypto_prices_repo
from open_leprechaun.repositories import (
    instruments,
    platforms,
    reference_rates,
    stances,
    transactions,
)
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.services import futures as futures_service
from open_leprechaun.services import fx, holdings
from open_leprechaun.services.futures import NormalizedFill

BOUGHT = datetime(2025, 3, 14, 12, 0, tzinfo=UTC)
LATER = datetime(2025, 6, 3, 12, 0, tzinfo=UTC)
QUOTED = datetime(2025, 7, 1, 9, 30, tzinfo=UTC)

TODAY = fx.event_date(datetime.now(UTC))


class FakeReferenceRateSource:
    """The reference-rate port's fake: whatever rates the test hands it,
    answered per query window."""

    def __init__(self, rates=()):
        self.rates = list(rates)

    def daily_rates(self, currency, start, end):
        return [
            rate
            for rate in self.rates
            if rate.currency == currency and start <= rate.rate_date <= end
        ]


def _todays_usd_rate(rate="1.10"):
    """A publication for today, so a display-rate fetch finds it."""
    return FakeReferenceRateSource([ReferenceRate("USD", TODAY, Decimal(rate))])


def _store_usd_rate(db, rate="1.10", on=TODAY):
    """A USD publication already in the store — the portfolio never fetches,
    so a test that wants a valued cash position seeds the store itself."""
    reference_rates.store(db, [ReferenceRate("USD", on, Decimal(rate))])


def _account(db, platform_name="Kraken", kind="exchange", name="Main", access_software=None):
    platform_id = platforms.create_platform(db, name=platform_name, kind=kind)
    created = platforms.create_account(db, platform_id, name=name, access_software=access_software)
    assert isinstance(created, int)
    return created


def _eur(db):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    return eur


def _btc(db):
    return instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")


def _keep(db, instrument, account):
    settled = stances.classify(db, instrument, stance="kept", account_id=account)
    assert not isinstance(settled, stances.Refusal)


def _buy(db, account, instrument, eur, *, quantity, cost, occurred_at=BOUGHT):
    created = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=occurred_at,
        note=None,
        legs=[
            Leg(
                account_id=account, instrument_id=instrument, role="in", quantity=Decimal(quantity)
            ),
            Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal(cost)),
        ],
    )
    assert isinstance(created, int)
    return created


def _sell(db, account, instrument, eur, *, quantity, proceeds, occurred_at=LATER):
    created = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=occurred_at,
        note=None,
        legs=[
            Leg(
                account_id=account, instrument_id=instrument, role="out", quantity=Decimal(quantity)
            ),
            Leg(account_id=account, instrument_id=eur, role="in", quantity=Decimal(proceeds)),
        ],
    )
    assert isinstance(created, int)
    return created


def _quote(db, instrument, price, *, as_of=QUOTED, source="coingecko"):
    crypto_prices_repo.store_quote(
        db, instrument_id=instrument, price_eur=Decimal(price), source=source, as_of=as_of
    )


def _position(portfolio, instrument, account):
    (position,) = [
        entry
        for entry in portfolio
        if entry.instrument_id == instrument and entry.account_id == account
    ]
    return position


# --- What a position states --------------------------------------------------


def test_a_kept_position_shows_quantity_basis_value_and_location(db):
    """Every position names its Instrument, family, quantity, average cost,
    current value, unrealised result and where it sits."""
    account = _account(db, platform_name="Ledger Nano", kind="cold_storage", name="Vault")
    eur, btc = _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur, quantity="2", cost="20000")
    _quote(db, btc, "15000")

    position = _position(holdings.portfolio(db), btc, account)

    assert position.symbol == "BTC"
    assert position.family == "crypto"
    assert position.platform_name == "Ledger Nano"
    assert position.platform_kind == "cold_storage"
    assert position.account_name == "Vault"
    assert position.quantity == Decimal("2")
    assert position.basis_eur == Decimal("20000")
    assert position.average_cost_eur == Decimal("10000.00")
    assert position.value_eur == Decimal("30000.00")
    assert position.unrealised_eur == Decimal("10000.00")
    assert position.marker is None
    assert position.basis_gap is None
    assert position.price_source == "coingecko"
    assert position.price_as_of == QUOTED


def test_cost_basis_is_read_from_the_lots_never_summed_from_inflows(db):
    """After a partial disposal the basis is what the remaining lots carry —
    FIFO consumed the oldest acquisition — not the sum of what ever flowed
    in."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur, quantity="1", cost="10000", occurred_at=BOUGHT)
    _buy(db, account, btc, eur, quantity="1", cost="30000", occurred_at=BOUGHT + timedelta(days=1))
    _sell(db, account, btc, eur, quantity="1", proceeds="35000")
    _quote(db, btc, "40000")

    position = _position(holdings.portfolio(db), btc, account)

    assert position.quantity == Decimal("1")
    # The first purchase was consumed; the second lot's basis remains.
    assert position.basis_eur == Decimal("30000")
    assert position.unrealised_eur == Decimal("10000.00")


def test_a_fully_disposed_position_does_not_appear(db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur, quantity="1", cost="10000")
    _sell(db, account, btc, eur, quantity="1", proceeds="12000")

    portfolio = holdings.portfolio(db)

    assert [entry for entry in portfolio if entry.instrument_id == btc] == []


# --- Cash --------------------------------------------------------------------


def test_cash_appears_as_its_own_line(db):
    """The numéraire balance left after a purchase is a position like any
    other: valued by identity, with no cost basis of its own."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    opening = transactions.create_transaction(
        db,
        type="opening_balance",
        occurred_at=BOUGHT - timedelta(days=1),
        note=None,
        reconstructed="basis",
        estimated_basis_eur=Decimal("15000"),
        legs=[Leg(account_id=account, instrument_id=eur, role="in", quantity=Decimal("15000"))],
    )
    assert isinstance(opening, int)
    _buy(db, account, btc, eur, quantity="1", cost="10000")

    position = _position(holdings.portfolio(db), eur, account)

    assert position.family == "cash"
    assert position.is_numeraire is True
    assert position.quantity == Decimal("5000")
    assert position.value_eur == Decimal("5000.00")
    assert position.basis_eur is None
    assert position.unrealised_eur is None
    assert position.marker is None
    assert position.basis_gap is None


def test_foreign_cash_is_valued_by_the_stored_reference_rate(db):
    account, eur = _account(db), _eur(db)
    usd = instruments.create_cash(db, symbol="USD", name="US Dollar")
    _keep(db, usd, account)
    _buy(db, account, usd, eur, quantity="1100", cost="1000")
    _store_usd_rate(db, "1.10")

    position = _position(holdings.portfolio(db), usd, account)

    assert position.value_eur == Decimal("1000.00")
    assert position.basis_eur == Decimal("1000")
    assert position.unrealised_eur == Decimal("0.00")
    assert position.price_source == "reference_rate"
    assert position.rate_date == TODAY


def test_the_portfolio_reads_the_store_and_never_fetches(db):
    """A quiet morning — today's rate not yet published — serves the latest
    stored publication with its date on display, costing no network call:
    portfolio() cannot fetch, by signature."""
    account, eur = _account(db), _eur(db)
    usd = instruments.create_cash(db, symbol="USD", name="US Dollar")
    _keep(db, usd, account)
    _buy(db, account, usd, eur, quantity="1100", cost="1000")
    _store_usd_rate(db, "1.10", on=TODAY - timedelta(days=3))

    position = _position(holdings.portfolio(db), usd, account)

    assert position.value_eur == Decimal("1000.00")
    assert position.rate_date == TODAY - timedelta(days=3)


def test_a_stablecoin_is_valued_by_its_peg_never_a_crypto_price(db):
    account, eur = _account(db), _eur(db)
    usdc = instruments.create_crypto_token(
        db,
        symbol="USDC",
        name="USD Coin",
        chain="ethereum",
        contract_address="0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        pegged_currency="USD",
    )
    _keep(db, usdc, account)
    _buy(db, account, usdc, eur, quantity="550", cost="500")
    # A crypto quote must not shadow the peg: even with one stored, the
    # reference rate answers.
    _quote(db, usdc, "2")
    _store_usd_rate(db, "1.10")

    position = _position(holdings.portfolio(db), usdc, account)

    assert position.value_eur == Decimal("500.00")
    assert position.price_source == "reference_rate"


# --- Markers and exclusions --------------------------------------------------


def test_a_crypto_position_no_store_has_priced_is_marked_unpriced(db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur, quantity="1", cost="10000")

    position = _position(holdings.portfolio(db), btc, account)

    assert position.marker == "unpriced"
    assert position.value_eur is None
    assert position.unrealised_eur is None
    assert position.basis_eur == Decimal("10000")


def test_foreign_cash_without_a_rate_in_reach_is_marked_unpriced(db):
    """No publication within the lookback: the position stands, marked — the
    portfolio never fails over one currency."""
    account, eur = _account(db), _eur(db)
    usd = instruments.create_cash(db, symbol="USD", name="US Dollar")
    _keep(db, usd, account)
    _buy(db, account, usd, eur, quantity="1100", cost="1000")

    position = _position(holdings.portfolio(db), usd, account)

    assert position.marker == "unpriced"
    assert position.value_eur is None


def test_ignored_and_dangerous_positions_are_marked_and_carry_no_basis(db):
    account = _account(db)
    _eur(db)
    dust = instruments.create_native_coin(db, symbol="DUST", name="Dust", chain="dustchain")
    scam = instruments.create_native_coin(db, symbol="EVIL", name="Evil", chain="evilchain")
    for instrument in (dust, scam):
        transactions.create_transaction(
            db,
            type="transfer_in",
            occurred_at=BOUGHT,
            note=None,
            legs=[
                Leg(account_id=account, instrument_id=instrument, role="in", quantity=Decimal(5))
            ],
        )
    stances.classify(db, dust, stance="ignored", account_id=account)
    stances.classify(db, scam, stance="dangerous", account_id=None)

    portfolio = holdings.portfolio(db)

    ignored = _position(portfolio, dust, account)
    dangerous = _position(portfolio, scam, account)
    assert ignored.marker == "ignored"
    assert dangerous.marker == "dangerous"
    assert ignored.quantity == Decimal("5")
    assert ignored.basis_eur is None
    assert dangerous.basis_eur is None


def test_an_unacknowledged_arrival_is_marked(db):
    account = _account(db)
    _eur(db)
    mystery = instruments.create_native_coin(db, symbol="WHAT", name="What", chain="somewhere")
    transactions.create_transaction(
        db,
        type="transfer_in",
        occurred_at=BOUGHT,
        note=None,
        legs=[Leg(account_id=account, instrument_id=mystery, role="in", quantity=Decimal(3))],
    )

    position = _position(holdings.portfolio(db), mystery, account)

    assert position.marker == "unacknowledged"
    assert position.quantity == Decimal("3")
    assert position.basis_eur is None


# --- A basis the ledger cannot state yet -------------------------------------


def test_a_basis_awaiting_valuation_is_stated_never_zero(db):
    """A crypto/crypto acquisition's basis needs a market value no rate can
    state — the position says so instead of summing what it knows as if the
    rest were zero."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    eth = instruments.create_native_coin(db, symbol="ETH", name="Ether", chain="ethereum")
    _keep(db, btc, account)
    _keep(db, eth, account)
    _buy(db, account, btc, eur, quantity="1", cost="10000")
    created = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=LATER,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=eth, role="in", quantity=Decimal("10")),
            Leg(account_id=account, instrument_id=btc, role="out", quantity=Decimal("0.5")),
        ],
    )
    assert isinstance(created, int)
    _quote(db, eth, "2000")

    position = _position(holdings.portfolio(db), eth, account)

    assert position.basis_eur is None
    assert position.basis_gap == "awaiting_valuation"
    assert position.average_cost_eur is None
    assert position.value_eur == Decimal("20000.00")
    assert position.unrealised_eur is None
    assert position.marker is None


def test_quantity_no_lot_vouches_for_leaves_the_basis_unvouched(db):
    """An unmatched transfer_in at a kept Account adds quantity but mints no
    lot: the basis covers less than the position holds, and says so."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur, quantity="1", cost="10000")
    transactions.create_transaction(
        db,
        type="transfer_in",
        occurred_at=LATER,
        note=None,
        legs=[Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("1"))],
    )
    _quote(db, btc, "15000")

    position = _position(holdings.portfolio(db), btc, account)

    assert position.quantity == Decimal("2")
    assert position.basis_eur is None
    assert position.basis_gap == "unvouched"
    assert position.value_eur == Decimal("30000.00")
    assert position.unrealised_eur is None


def test_a_kept_windfall_costs_a_round_zero(db):
    """A windfall's basis is zero by rule — its average is a plain 0.00, not
    a string of micro-price decimals."""
    account = _account(db)
    _eur(db)
    gift = instruments.create_native_coin(db, symbol="GIFT", name="Gift", chain="giftchain")
    _keep(db, gift, account)
    transactions.create_transaction(
        db,
        type="windfall",
        occurred_at=BOUGHT,
        note=None,
        legs=[Leg(account_id=account, instrument_id=gift, role="in", quantity=Decimal("1000"))],
    )
    _quote(db, gift, "0.5")

    position = _position(holdings.portfolio(db), gift, account)

    assert position.basis_eur == Decimal("0")
    assert position.average_cost_eur == Decimal("0.00")
    assert position.value_eur == Decimal("500.00")


# --- Location details --------------------------------------------------------


def test_access_software_travels_with_its_positions(db):
    account = _account(db, platform_name="BitBox", kind="cold_storage", access_software="BitBoxApp")
    eur, btc = _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur, quantity="1", cost="10000")
    _quote(db, btc, "15000")

    position = _position(holdings.portfolio(db), btc, account)

    assert position.access_software == "BitBoxApp"


def test_a_stored_price_serves_with_its_source_and_age(db):
    """Whatever the provider chain last knew values the position — the
    request path itself never calls a provider, it states the quote's age
    instead."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur, quantity="1", cost="10000")
    aged = datetime(2025, 1, 2, 3, 4, tzinfo=UTC)
    _quote(db, btc, "12345.67", as_of=aged, source="defillama")

    position = _position(holdings.portfolio(db), btc, account)

    assert position.value_eur == Decimal("12345.67")
    assert position.price_source == "defillama"
    assert position.price_as_of == aged


# --- The display rate --------------------------------------------------------


def test_the_display_rate_is_the_latest_published(db):
    stale = ReferenceRate("USD", TODAY - timedelta(days=3), Decimal("1.05"))
    fresh = ReferenceRate("USD", TODAY, Decimal("1.10"))

    rate = holdings.display_rate(db, FakeReferenceRateSource([stale, fresh]), currency="USD")

    assert rate.rate == Decimal("1.10")
    assert rate.rate_date == TODAY


def test_the_display_rate_for_the_euro_is_identity(db):
    rate = holdings.display_rate(db, FakeReferenceRateSource(), currency="EUR")

    assert rate.rate == Decimal(1)


def test_an_uncovered_display_currency_refuses_by_name(db):
    with pytest.raises(fx.RateUnavailableError):
        holdings.display_rate(db, FakeReferenceRateSource(), currency="XYZ")


# --- The API -----------------------------------------------------------------


def _client(db, source):
    """The API bound to the test database, rates through the given fake."""
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_reference_rate_source] = lambda: source
    return TestClient(app)


def test_the_api_serves_holdings_with_decimal_strings(db):
    account = _account(db, platform_name="Kraken", kind="exchange", name="Spot")
    eur, btc = _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur, quantity="1.5", cost="30000")
    _quote(db, btc, "25000")

    with _client(db, FakeReferenceRateSource()) as client:
        response = client.get("/api/holdings")

    assert response.status_code == 200
    (position,) = [row for row in response.json()["positions"] if row["symbol"] == "BTC"]
    assert position["quantity"] == "1.5"
    assert position["basis_eur"] == "30000"
    assert position["value_eur"] == "37500.00"
    assert position["unrealised_eur"] == "7500.00"
    assert position["platform_kind"] == "exchange"
    assert position["marker"] is None


def test_the_api_serves_a_display_rate_for_presentation_only(db):
    with _client(db, _todays_usd_rate("1.10")) as client:
        answered = client.get("/api/holdings/display-rate/USD")
        refused = client.get("/api/holdings/display-rate/XYZ")

    assert answered.status_code == 200
    assert answered.json()["rate"] == "1.10"
    assert answered.json()["currency"] == "USD"
    assert refused.status_code == 404


def test_a_coin_margined_close_puts_the_settlement_asset_in_the_portfolio(db):
    """Ticket 29: the coin a close settled is held — quantity grown by the
    net figure, its basis read from the settlement lot's queue, awaiting the
    market value at the close like any income-minted lot."""
    account, btc = _account(db, platform_name="OKX"), _btc(db)
    _keep(db, btc, account)
    futures_service.sync(
        db,
        source="okx:futures",
        fills=[
            NormalizedFill(
                external_id="open-1",
                account_id=account,
                symbol="BTCUSD-INVERSE",
                side="buy",
                price=Decimal("10000"),
                size=Decimal("1"),
                fee=Decimal("0.0001"),
                settlement_instrument_id=btc,
                occurred_at=BOUGHT,
                inverse=True,
            ),
            NormalizedFill(
                external_id="close-1",
                account_id=account,
                symbol="BTCUSD-INVERSE",
                side="sell",
                price=Decimal("11000"),
                size=Decimal("1"),
                fee=Decimal("0.0001"),
                settlement_instrument_id=btc,
                occurred_at=LATER,
                realized=Decimal("0.0092"),
                inverse=True,
            ),
        ],
    )

    (position,) = holdings.portfolio(db)

    assert position.instrument_id == btc
    assert position.account_id == account
    assert position.quantity == Decimal("0.0090")
    assert position.basis_gap == holdings.AWAITING_VALUATION

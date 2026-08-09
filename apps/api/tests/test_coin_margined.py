"""Coin-margined settlement (ticket 29): an inverse contract settles in the
coin, so closing one both realises capital income and puts an asset into the
books. End to end: a close produces exactly one Section 20 Event — converted
at the rate of the close (ticket 28's emitter) — and exactly one Tax Lot for
the settlement asset, whose basis is its EUR value at the close and whose
holding period starts there, consumed by a later §23 disposal like any other
acquisition."""

from datetime import UTC, datetime
from decimal import Decimal

from open_leprechaun.ports.reference_rates import ReferenceRate
from open_leprechaun.repositories import instruments, platforms, statutory, transactions
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.services import futures, lots, section20, section23
from open_leprechaun.services.futures import NormalizedFill, NormalizedFunding

OPENED = datetime(2031, 3, 2, 10, 0, tzinfo=UTC)
CLOSED = datetime(2031, 3, 2, 11, 0, tzinfo=UTC)
SOLD = datetime(2031, 6, 2, 11, 0, tzinfo=UTC)


class FakeReferenceRateSource:
    def __init__(self, rates=()):
        self.rates = list(rates)

    def daily_rates(self, currency, start, end):
        return [
            rate
            for rate in self.rates
            if rate.currency == currency and start <= rate.rate_date <= end
        ]


def _rates():
    """One USD publication per date a conversion will ask for."""
    return FakeReferenceRateSource([ReferenceRate("USD", CLOSED.date(), Decimal("1.25"))])


def _account(db):
    platform_id = platforms.create_platform(db, name="OKX", kind="exchange")
    created = platforms.create_account(db, platform_id, name="Futures")
    assert isinstance(created, int)
    return created


def _eur(db):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    return eur


def _usdt(db):
    """A stablecoin settlement asset: a Kryptowert like any other, valued by
    its peg's daily reference rate — so the close's figures are statable
    without a crypto price."""
    return instruments.create_crypto_token(
        db,
        symbol="USDT",
        name="Tether",
        chain="ethereum",
        contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7",
        pegged_currency="USD",
    )


def _statutes(db, *, year):
    for key, value in (
        ("saver_allowance_single", "1000"),
        ("flat_rate", "0.25"),
        ("solidarity_surcharge_rate", "0.055"),
        ("private_sale_exemption_limit", "1000"),
    ):
        statutory.upsert_value(db, year=year, key=key, value=Decimal(value), source="a test value")


def _close_coin_margined(db, account, usdt):
    """One inverse position opened and closed, its result venue-stated, plus
    an attributed funding payment: net 100 USDT settled at the close."""
    synced = futures.sync(
        db,
        source="okx:futures",
        fills=[
            NormalizedFill(
                external_id="open-1",
                account_id=account,
                symbol="BTC-USDT-INVERSE",
                side="buy",
                price=Decimal("10000"),
                size=Decimal("1"),
                fee=Decimal("1"),
                settlement_instrument_id=usdt,
                occurred_at=OPENED,
                inverse=True,
            ),
            NormalizedFill(
                external_id="close-1",
                account_id=account,
                symbol="BTC-USDT-INVERSE",
                side="sell",
                price=Decimal("11000"),
                size=Decimal("1"),
                fee=Decimal("1"),
                settlement_instrument_id=usdt,
                occurred_at=CLOSED,
                realized=Decimal("98"),
                inverse=True,
            ),
        ],
        funding=[
            NormalizedFunding(
                external_id="funding-1",
                account_id=account,
                symbol="BTC-USDT-INVERSE",
                amount=Decimal("4"),
                settlement_instrument_id=usdt,
                occurred_at=OPENED,
            )
        ],
    )
    assert synced.derivation.issues == ()


def test_a_close_produces_exactly_one_capital_income_event_and_exactly_one_lot(db):
    """The two consequences of one close, and no more: the net figure —
    98 - 2 + 4 = 100 USDT — enters the Termingeschäfte pot converted at the
    close date's rate, and the same 100 USDT stand as one lot acquired at
    the close, at market value there."""
    _statutes(db, year=2031)
    account, usdt = _account(db), _usdt(db)
    _eur(db)
    _close_coin_margined(db, account, usdt)

    report = section20.year_report(db, _rates(), year=2031)

    assert report.awaiting_valuation == ()
    pots = {balance.category: balance for balance in report.balances}
    (entry,) = pots["termingeschaefte"].entries
    # 100 USDT at 1.25 USD per EUR.
    assert entry.event.gross_eur == Decimal("80")
    assert entry.event.date == CLOSED.date()
    assert pots["aktien"].entries == ()
    assert pots["sonstige"].entries == ()

    (lot,) = lots.fresh_lots(db)
    assert lot.leg_id is None
    assert lot.instrument_id == usdt
    assert lot.quantity == Decimal("100")
    assert lot.acquired_at == CLOSED
    assert lot.basis_source == "market_value"


def test_a_later_disposal_consumes_the_settlement_lot_from_the_close(db):
    """The settled coin is an ordinary asset from the close on: selling it
    within the year is a §23 private sale whose basis is the coin's EUR
    value at the close — the same figure the Section 20 Event stated — and
    whose holding period runs from the close, not from the position's
    opening."""
    _statutes(db, year=2031)
    account, usdt = _account(db), _usdt(db)
    eur = _eur(db)
    _close_coin_margined(db, account, usdt)
    created = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=SOLD,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=usdt, role="out", quantity=Decimal("100")),
            Leg(account_id=account, instrument_id=eur, role="in", quantity=Decimal("90")),
        ],
    )
    assert isinstance(created, int)

    report = section23.year_report(db, _rates(), year=2031)

    (disposal,) = report.disposals
    (consumption,) = disposal.consumptions
    assert consumption.acquired_at == CLOSED
    assert consumption.basis_eur == Decimal("80")
    assert consumption.holding_days == (SOLD - CLOSED).days
    assert not consumption.long_term
    assert consumption.gain_eur == Decimal("10")
    assert report.total_gain_eur == Decimal("10")

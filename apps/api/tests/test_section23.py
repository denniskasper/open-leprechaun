"""§23 EStG private sales — the disposal engine (ticket 21). Crypto (and
foreign-cash) disposals consume Tax Lots FIFO within their Account and
Instrument, the Haltefrist decides exemption between absolute instants, and
the annual Freigrenze is read per year from the statutory store, never from a
constant in logic.

The seams are the engine's one public read — `section23.year_report`, driven
over real Postgres with the ledger built through the repositories and rates
through a fake of the reference-rate port — and its named refusals.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from open_leprechaun.ports.reference_rates import ReferenceRate
from open_leprechaun.repositories import (
    instruments,
    platforms,
    stances,
    statutory,
    transactions,
    transfer_matches,
)
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.services import section23

BOUGHT = datetime(2025, 3, 14, 12, 0, tzinfo=UTC)
SOLD = datetime(2025, 6, 3, 12, 0, tzinfo=UTC)


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


def _account(db, platform_name="Kraken", kind="exchange", name="Main"):
    platform_id = platforms.create_platform(db, name=platform_name, kind=kind)
    created = platforms.create_account(db, platform_id, name=name)
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


def _buy(db, account, instrument, eur, *, quantity, cost, occurred_at):
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


def _sell(db, account, instrument, eur, *, quantity, proceeds, occurred_at):
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


# --- Consuming lots FIFO ----------------------------------------------------


def test_a_sale_within_a_year_is_a_taxable_private_sale(db):
    """§23 Abs. 1 Satz 1 Nr. 2 EStG: a disposal of a Kryptowert held not more
    than one year is a private sale — its consumption records quantity, basis,
    proceeds, holding period and the long-term flag."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur, quantity="1", cost="10000", occurred_at=BOUGHT)
    _sell(db, account, btc, eur, quantity="1", proceeds="12000", occurred_at=SOLD)

    report = section23.year_report(db, FakeReferenceRateSource(), year=2025)

    (disposal,) = report.disposals
    assert disposal.instrument_id == btc
    assert disposal.account_id == account
    assert disposal.disposed_at == SOLD
    assert disposal.quantity == Decimal("1")
    assert disposal.proceeds_eur == Decimal("12000")
    (consumption,) = disposal.consumptions
    assert consumption.quantity == Decimal("1")
    assert consumption.acquired_at == BOUGHT
    assert consumption.basis_eur == Decimal("10000")
    assert consumption.proceeds_eur == Decimal("12000")
    assert consumption.holding_days == 81
    assert consumption.long_term is False
    assert consumption.gain_eur == Decimal("2000")
    assert report.total_gain_eur == Decimal("2000")
    assert report.awaiting_valuation == ()


def test_a_disposal_consumes_the_oldest_acquisition_first(db):
    """FIFO per Account and Instrument (BMF letter of 10.05.2022 on virtual
    currencies): the first lot is consumed whole, the second pro-rata, each
    consumption wearing its own acquisition's basis and instant."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    first = datetime(2025, 1, 10, 12, 0, tzinfo=UTC)
    second = datetime(2025, 2, 10, 12, 0, tzinfo=UTC)
    _buy(db, account, btc, eur, quantity="1", cost="10000", occurred_at=first)
    _buy(db, account, btc, eur, quantity="1", cost="20000", occurred_at=second)
    _sell(db, account, btc, eur, quantity="1.5", proceeds="45000", occurred_at=SOLD)

    report = section23.year_report(db, FakeReferenceRateSource(), year=2025)

    (disposal,) = report.disposals
    oldest, split = disposal.consumptions
    assert oldest.acquired_at == first
    assert oldest.quantity == Decimal("1")
    assert oldest.basis_eur == Decimal("10000")
    assert oldest.proceeds_eur == Decimal("30000")
    assert split.acquired_at == second
    assert split.quantity == Decimal("0.5")
    assert split.basis_eur == Decimal("10000")
    assert split.proceeds_eur == Decimal("15000")
    assert report.total_gain_eur == Decimal("25000")


def test_fifo_is_bounded_by_the_account_that_held_the_lots(db):
    """§23 matching happens within the Account that held the coins: a lot at
    another Account never fills a disposal here, however identical the
    Instrument — the shortfall is an error, not a cross-account borrow."""
    exchange, eur, btc = _account(db), _eur(db), _btc(db)
    vault = _account(db, platform_name="Ledger", kind="cold_storage", name="Vault")
    _keep(db, btc, exchange)
    _keep(db, btc, vault)
    _buy(db, exchange, btc, eur, quantity="1", cost="10000", occurred_at=BOUGHT)
    _buy(db, vault, btc, eur, quantity="5", cost="50000", occurred_at=BOUGHT)
    _sell(db, exchange, btc, eur, quantity="2", proceeds="24000", occurred_at=SOLD)

    with pytest.raises(section23.LotShortfallError):
        section23.year_report(db, FakeReferenceRateSource(), year=2025)


def test_a_disposal_exceeding_available_lots_names_the_shortfall(db):
    """Never a silent zero-basis fill: the error names the missing quantity,
    so the Admin knows which acquisition the ledger lacks."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur, quantity="1", cost="10000", occurred_at=BOUGHT)
    _sell(db, account, btc, eur, quantity="1.25", proceeds="15000", occurred_at=SOLD)

    with pytest.raises(section23.LotShortfallError, match=r"0\.25 BTC"):
        section23.year_report(db, FakeReferenceRateSource(), year=2025)


# --- The Haltefrist ---------------------------------------------------------


def test_held_exactly_one_year_is_still_taxable(db):
    """§23 Abs. 1 Satz 1 Nr. 2 EStG taxes a period of 'nicht mehr als ein
    Jahr' — exactly one year is not more than one year. A summer round trip,
    so the German clock is CEST on both ends."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(
        db,
        account,
        btc,
        eur,
        quantity="1",
        cost="10000",
        occurred_at=datetime(2025, 6, 10, 12, 0, tzinfo=UTC),
    )
    _sell(
        db,
        account,
        btc,
        eur,
        quantity="1",
        proceeds="15000",
        occurred_at=datetime(2026, 6, 10, 12, 0, tzinfo=UTC),
    )

    report = section23.year_report(db, FakeReferenceRateSource(), year=2026)

    (consumption,) = report.disposals[0].consumptions
    assert consumption.holding_days == 365
    assert consumption.long_term is False
    assert report.total_gain_eur == Decimal("5000")


@pytest.mark.parametrize(
    "bought",
    [
        pytest.param(datetime(2025, 3, 14, 12, 0, tzinfo=UTC), id="winter"),
        pytest.param(datetime(2024, 6, 10, 12, 0, tzinfo=UTC), id="summer"),
    ],
)
def test_the_haltefrist_boundary_is_judged_to_the_second(db, bought):
    """§23 Abs. 1 Satz 1 Nr. 2 EStG at the threshold: a second below one
    year and the year itself are taxable, a second beyond is exempt — on
    both sides of the anniversary under the winter clock (CET) and under the
    summer clock (CEST)."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur, quantity="3", cost="30000", occurred_at=bought)
    anniversary = bought.replace(year=bought.year + 1)
    for offset, proceeds in ((-1, "11000"), (0, "12000"), (1, "13000")):
        _sell(
            db,
            account,
            btc,
            eur,
            quantity="1",
            proceeds=proceeds,
            occurred_at=anniversary + timedelta(seconds=offset),
        )

    report = section23.year_report(db, FakeReferenceRateSource(), year=anniversary.year)

    below, at, above = sorted(report.disposals, key=lambda disposal: disposal.disposed_at)
    assert below.consumptions[0].long_term is False
    assert at.consumptions[0].long_term is False
    assert above.consumptions[0].long_term is True
    assert report.total_gain_eur == Decimal("3000")


def test_a_leap_day_acquisition_completes_its_year_on_28_february(db):
    """The anniversary month has no 29th, so the Haltefrist completes with
    28 February (§188 Abs. 3 BGB analog) — taxable through that instant,
    exempt beyond it."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(
        db,
        account,
        btc,
        eur,
        quantity="2",
        cost="20000",
        occurred_at=datetime(2024, 2, 29, 12, 0, tzinfo=UTC),
    )
    completes = datetime(2025, 2, 28, 12, 0, tzinfo=UTC)
    _sell(db, account, btc, eur, quantity="1", proceeds="12000", occurred_at=completes)
    _sell(
        db,
        account,
        btc,
        eur,
        quantity="1",
        proceeds="13000",
        occurred_at=completes + timedelta(seconds=1),
    )

    report = section23.year_report(db, FakeReferenceRateSource(), year=2025)

    at, beyond = sorted(report.disposals, key=lambda disposal: disposal.disposed_at)
    assert at.consumptions[0].long_term is False
    assert beyond.consumptions[0].long_term is True
    assert report.total_gain_eur == Decimal("2000")


def test_held_beyond_one_year_is_exempt_but_stays_visible(db):
    """§23 Abs. 1 Satz 1 Nr. 2 EStG: one second beyond the year exempts the
    disposal — excluded from the total, stated in full in the detail. A
    winter acquisition, so the German clock is CET on both ends."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    bought = datetime(2024, 12, 20, 12, 0, tzinfo=UTC)
    _buy(db, account, btc, eur, quantity="1", cost="10000", occurred_at=bought)
    _sell(
        db,
        account,
        btc,
        eur,
        quantity="1",
        proceeds="15000",
        occurred_at=datetime(2025, 12, 20, 12, 0, 1, tzinfo=UTC),
    )

    report = section23.year_report(db, FakeReferenceRateSource(), year=2025)

    (disposal,) = report.disposals
    (consumption,) = disposal.consumptions
    assert consumption.long_term is True
    assert consumption.basis_eur == Decimal("10000")
    assert consumption.proceeds_eur == Decimal("15000")
    assert consumption.gain_eur == Decimal("5000")
    assert report.total_gain_eur == Decimal("0")
    assert report.freigrenze is not None
    assert report.freigrenze.tax_free is True


def test_the_holding_period_runs_between_absolute_instants(db):
    """Bought in the last UTC half-hour of a year — already New Year in
    Berlin. By Berlin calendar dates the round trip below is exactly one
    year (taxable); between instants it is a year and a quarter-hour —
    exempt. The instants decide."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    bought = datetime(2024, 12, 31, 23, 30, tzinfo=UTC)
    _buy(db, account, btc, eur, quantity="1", cost="10000", occurred_at=bought)
    _sell(
        db,
        account,
        btc,
        eur,
        quantity="1",
        proceeds="15000",
        occurred_at=datetime(2025, 12, 31, 23, 45, tzinfo=UTC),
    )

    report = section23.year_report(db, FakeReferenceRateSource(), year=2026)

    (disposal,) = report.disposals
    assert disposal.tax_year == 2026
    (consumption,) = disposal.consumptions
    assert consumption.long_term is True


def test_a_self_transfer_does_not_restart_the_holding_period(db):
    """A confirmed self-transfer (ticket 16) carries the acquisition instant
    across, so coins bought, moved to cold storage months later and sold
    just past the year are exempt — the Haltefrist ran from the purchase,
    not the move."""
    exchange, eur, btc = _account(db), _eur(db), _btc(db)
    vault = _account(db, platform_name="Ledger", kind="cold_storage", name="Vault")
    _keep(db, btc, exchange)
    _buy(db, exchange, btc, eur, quantity="1", cost="10000", occurred_at=BOUGHT)
    out_transaction = transactions.create_transaction(
        db,
        type="transfer_out",
        occurred_at=datetime(2025, 9, 1, 12, 0, tzinfo=UTC),
        note=None,
        legs=[Leg(account_id=exchange, instrument_id=btc, role="out", quantity=Decimal("1"))],
    )
    in_transaction = transactions.create_transaction(
        db,
        type="transfer_in",
        occurred_at=datetime(2025, 9, 1, 13, 0, tzinfo=UTC),
        note=None,
        legs=[Leg(account_id=vault, instrument_id=btc, role="in", quantity=Decimal("1"))],
    )
    with db.connect() as connection:
        out_leg, in_leg = (
            connection.execute(
                text("SELECT id FROM transaction_leg WHERE transaction_id = :id"),
                {"id": transaction_id},
            ).scalar_one()
            for transaction_id in (out_transaction, in_transaction)
        )
    decided = transfer_matches.decide(db, out_leg_id=out_leg, in_leg_id=in_leg, verdict="confirmed")
    assert isinstance(decided, int)
    _sell(
        db,
        vault,
        btc,
        eur,
        quantity="1",
        proceeds="15000",
        occurred_at=datetime(2026, 3, 20, 12, 0, tzinfo=UTC),
    )

    report = section23.year_report(db, FakeReferenceRateSource(), year=2026)

    (disposal,) = report.disposals
    assert disposal.account_id == vault
    (consumption,) = disposal.consumptions
    assert consumption.acquired_at == BOUGHT
    assert consumption.long_term is True
    assert report.total_gain_eur == Decimal("0")


# --- The Freigrenze ---------------------------------------------------------


def test_a_total_below_the_limit_is_entirely_free_with_its_headroom_stated(db):
    """§23 Abs. 3 Satz 5 EStG: a Gesamtgewinn below the Freigrenze is wholly
    tax-free. The limit is the statutory store's per-year value, and the
    headroom is stated, not left to arithmetic."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur, quantity="1", cost="10000", occurred_at=BOUGHT)
    _sell(db, account, btc, eur, quantity="1", proceeds="10999.99", occurred_at=SOLD)

    report = section23.year_report(db, FakeReferenceRateSource(), year=2025)

    verdict = report.freigrenze
    assert verdict.limit_eur == Decimal("1000")
    assert verdict.total_gain_eur == Decimal("999.99")
    assert verdict.tax_free is True
    assert verdict.taxable_gain_eur == Decimal("0")
    assert verdict.headroom_eur == Decimal("0.01")
    assert verdict.overshoot_eur is None


def test_a_total_at_the_limit_is_entirely_taxable(db):
    """§23 Abs. 3 Satz 5 EStG says 'weniger als': exactly the limit is not
    below it, so the full amount is taxable — not just the excess — and the
    overshoot is stated as zero."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur, quantity="1", cost="10000", occurred_at=BOUGHT)
    _sell(db, account, btc, eur, quantity="1", proceeds="11000", occurred_at=SOLD)

    report = section23.year_report(db, FakeReferenceRateSource(), year=2025)

    verdict = report.freigrenze
    assert verdict.tax_free is False
    assert verdict.taxable_gain_eur == Decimal("1000")
    assert verdict.overshoot_eur == Decimal("0")
    assert verdict.headroom_eur is None


def test_a_total_just_above_the_limit_is_entirely_taxable(db):
    """One cent above the Freigrenze taxes the whole Gesamtgewinn."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur, quantity="1", cost="10000", occurred_at=BOUGHT)
    _sell(db, account, btc, eur, quantity="1", proceeds="11000.01", occurred_at=SOLD)

    report = section23.year_report(db, FakeReferenceRateSource(), year=2025)

    verdict = report.freigrenze
    assert verdict.tax_free is False
    assert verdict.taxable_gain_eur == Decimal("1000.01")
    assert verdict.overshoot_eur == Decimal("0.01")


def test_losses_net_against_gains_within_the_year(db):
    """The Freigrenze judges the Gesamtgewinn — gains and losses of the year
    netted — so a gain over the limit shielded by a loss stays free."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    eth = instruments.create_native_coin(db, symbol="ETH", name="Ether", chain="ethereum")
    _keep(db, btc, account)
    _keep(db, eth, account)
    _buy(db, account, btc, eur, quantity="1", cost="10000", occurred_at=BOUGHT)
    _buy(db, account, eth, eur, quantity="10", cost="20000", occurred_at=BOUGHT)
    _sell(db, account, btc, eur, quantity="1", proceeds="11500", occurred_at=SOLD)
    _sell(db, account, eth, eur, quantity="10", proceeds="19000", occurred_at=SOLD)

    report = section23.year_report(db, FakeReferenceRateSource(), year=2025)

    assert report.total_gain_eur == Decimal("500")
    assert report.freigrenze.tax_free is True
    assert report.freigrenze.taxable_gain_eur == Decimal("0")


def test_the_limit_is_the_years_own_configured_value(db):
    """A future legislature moves the Freigrenze by an UPDATE, not a code
    change: a year configured to 600 € taxes a 700 € Gesamtgewinn that the
    seeded years would have let through."""
    with db.begin() as connection:
        connection.execute(text("DELETE FROM statutory_value WHERE year >= 2030"))
    statutory.upsert_value(
        db,
        year=2031,
        key="private_sale_exemption_limit",
        value=Decimal("600"),
        source="a future amendment",
    )
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(
        db,
        account,
        btc,
        eur,
        quantity="1",
        cost="10000",
        occurred_at=datetime(2031, 3, 14, 12, 0, tzinfo=UTC),
    )
    _sell(
        db,
        account,
        btc,
        eur,
        quantity="1",
        proceeds="10700",
        occurred_at=datetime(2031, 6, 3, 12, 0, tzinfo=UTC),
    )

    report = section23.year_report(db, FakeReferenceRateSource(), year=2031)

    verdict = report.freigrenze
    assert verdict.limit_eur == Decimal("600")
    assert verdict.tax_free is False
    assert verdict.taxable_gain_eur == Decimal("700")
    assert verdict.overshoot_eur == Decimal("100")


def test_a_year_without_its_limit_refuses_to_compute(db):
    """The Freigrenze is per-year configuration (ticket 09); a year with no
    value set is refused by name, never defaulted."""
    with pytest.raises(section23.StatutoryValueUnsetError, match="2019"):
        section23.year_report(db, FakeReferenceRateSource(), year=2019)


# --- The Tax Year boundary --------------------------------------------------


def test_the_tax_year_follows_the_berlin_local_date(db):
    """A sale in the last UTC hour of December already belongs to the new
    German year (CET is an hour ahead), while one two hours earlier stays in
    the old one — the instant is absolute, only its bucketing is local."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur, quantity="2", cost="20000", occurred_at=BOUGHT)
    _sell(
        db,
        account,
        btc,
        eur,
        quantity="1",
        proceeds="12000",
        occurred_at=datetime(2025, 12, 31, 22, 30, tzinfo=UTC),
    )
    _sell(
        db,
        account,
        btc,
        eur,
        quantity="1",
        proceeds="14000",
        occurred_at=datetime(2025, 12, 31, 23, 30, tzinfo=UTC),
    )

    old_year = section23.year_report(db, FakeReferenceRateSource(), year=2025)
    new_year = section23.year_report(db, FakeReferenceRateSource(), year=2026)

    (stayed,) = old_year.disposals
    assert stayed.tax_year == 2025
    assert stayed.proceeds_eur == Decimal("12000")
    (crossed,) = new_year.disposals
    assert crossed.tax_year == 2026
    assert crossed.proceeds_eur == Decimal("14000")


# --- What stands outside §23 ------------------------------------------------


def test_an_ignored_holding_never_becomes_a_private_sale(db):
    """An ignored position never entered the cost basis (ADR-0012); its
    outflow stays a ledger entry rather than erroring over lots that were
    never minted."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    settled = stances.classify(db, btc, stance="ignored", account_id=account)
    assert not isinstance(settled, stances.Refusal)
    _buy(db, account, btc, eur, quantity="1", cost="10000", occurred_at=BOUGHT)
    _sell(db, account, btc, eur, quantity="1", proceeds="15000", occurred_at=SOLD)

    report = section23.year_report(db, FakeReferenceRateSource(), year=2025)

    assert report.disposals == ()
    assert report.total_gain_eur == Decimal("0")


def test_a_kept_windfall_disposal_falls_outside_the_paragraph(db):
    """No Anschaffungsvorgang, no private sale (BMF letter of 10.05.2022):
    what a kept windfall realises is excluded from the §23 total — while the
    consumption stays visible, wearing its provenance."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    created = transactions.create_transaction(
        db,
        type="windfall",
        occurred_at=BOUGHT,
        note=None,
        legs=[Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("1"))],
    )
    assert isinstance(created, int)
    _sell(db, account, btc, eur, quantity="1", proceeds="15000", occurred_at=SOLD)

    report = section23.year_report(db, FakeReferenceRateSource(), year=2025)

    (disposal,) = report.disposals
    (consumption,) = disposal.consumptions
    assert consumption.basis_source == "without_consideration"
    assert consumption.basis_eur == Decimal("0")
    assert consumption.proceeds_eur == Decimal("15000")
    assert consumption.gain_eur is None
    assert report.total_gain_eur == Decimal("0")
    assert report.awaiting_valuation == ()
    assert report.freigrenze.tax_free is True


def test_a_disposal_consuming_an_opening_balance_is_flagged_as_resting_on_an_estimate(db):
    """An Opening Balance (ticket 15) declares its basis reconstructed, and
    every figure resting on it says so instead of wearing the confidence of
    a documented purchase."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    created = transactions.create_transaction(
        db,
        type="opening_balance",
        occurred_at=BOUGHT,
        note=None,
        reconstructed="basis",
        estimated_basis_eur=Decimal("8000"),
        legs=[Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("1"))],
    )
    assert isinstance(created, int)
    _sell(db, account, btc, eur, quantity="1", proceeds="15000", occurred_at=SOLD)

    report = section23.year_report(db, FakeReferenceRateSource(), year=2025)

    (disposal,) = report.disposals
    assert disposal.rests_on_estimate is True
    (consumption,) = disposal.consumptions
    assert consumption.basis_source == "estimate"
    assert consumption.gain_eur == Decimal("7000")


# --- Valuation by the reference rate ----------------------------------------


def test_proceeds_in_foreign_cash_convert_by_the_reference_rate(db):
    """Selling crypto for dollars states the Veräußerungspreis by the euro
    reference rate of the event date (ADR-0017) — the disposal of a foreign
    currency being itself a later private sale."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    usd = instruments.create_cash(db, symbol="USD", name="US Dollar")
    _keep(db, btc, account)
    _keep(db, usd, account)
    _buy(db, account, btc, eur, quantity="1", cost="10000", occurred_at=BOUGHT)
    _sell(db, account, btc, usd, quantity="1", proceeds="13750", occurred_at=SOLD)
    source = FakeReferenceRateSource(
        [ReferenceRate(currency="USD", rate_date=SOLD.date(), rate=Decimal("1.25"))]
    )

    report = section23.year_report(db, source, year=2025)

    (disposal,) = report.disposals
    assert disposal.proceeds_eur == Decimal("11000")
    assert report.total_gain_eur == Decimal("1000")


def test_a_spent_stablecoin_is_valued_by_its_pegged_currency(db):
    """Spending a stablecoin is a disposal like any other Kryptowert, and its
    EUR value comes from the pegged currency's daily reference rate — never
    a crypto price provider."""
    account, eur = _account(db), _eur(db)
    usdt = instruments.create_crypto_token(
        db,
        symbol="USDT",
        name="Tether",
        chain="ethereum",
        contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7",
        pegged_currency="USD",
    )
    _keep(db, usdt, account)
    _buy(db, account, usdt, eur, quantity="1000", cost="950", occurred_at=BOUGHT)
    created = transactions.create_transaction(
        db,
        type="spend",
        occurred_at=SOLD,
        note=None,
        legs=[Leg(account_id=account, instrument_id=usdt, role="out", quantity=Decimal("1000"))],
    )
    assert isinstance(created, int)
    source = FakeReferenceRateSource(
        [ReferenceRate(currency="USD", rate_date=SOLD.date(), rate=Decimal("1.25"))]
    )

    report = section23.year_report(db, source, year=2025)

    (disposal,) = report.disposals
    assert disposal.proceeds_eur == Decimal("800")
    (consumption,) = disposal.consumptions
    assert consumption.gain_eur == Decimal("-150")
    assert report.total_gain_eur == Decimal("-150")
    assert report.freigrenze.tax_free is True
    assert report.freigrenze.taxable_gain_eur == Decimal("0")


def test_a_crypto_crypto_trade_awaits_valuation(db):
    """A Veräußerungspreis needing a crypto price (ticket 18) is never
    guessed: the disposal is named as awaiting valuation, and the year
    states no total and no Freigrenze verdict over the unknown."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    eth = instruments.create_native_coin(db, symbol="ETH", name="Ether", chain="ethereum")
    _keep(db, btc, account)
    _keep(db, eth, account)
    _buy(db, account, btc, eur, quantity="1", cost="10000", occurred_at=BOUGHT)
    created = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=SOLD,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=btc, role="out", quantity=Decimal("1")),
            Leg(account_id=account, instrument_id=eth, role="in", quantity=Decimal("15")),
        ],
    )
    assert isinstance(created, int)

    report = section23.year_report(db, FakeReferenceRateSource(), year=2025)

    (disposal,) = report.disposals
    assert disposal.proceeds_eur is None
    (consumption,) = disposal.consumptions
    assert consumption.gain_eur is None
    assert report.awaiting_valuation == (disposal.leg_id,)
    assert report.total_gain_eur is None
    assert report.freigrenze is None


def test_an_exempt_market_value_consumption_costs_no_rate_lookup(db):
    """A Haltefrist-exempt consumption is excluded from the total, so its
    market-value basis (ticket 22) is never valued for it: a rate gap at the
    old acquisition date cannot crash — or block — a year the slice is
    excluded from. The basis stays unstated in the detail, like any figure
    nothing can vouch for."""
    account, eur = _account(db), _eur(db)
    usdt = instruments.create_crypto_token(
        db,
        symbol="USDT",
        name="Tether",
        chain="ethereum",
        contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7",
        pegged_currency="USD",
    )
    _keep(db, usdt, account)
    created = transactions.create_transaction(
        db,
        type="staking_reward",
        occurred_at=datetime(2024, 3, 14, 12, 0, tzinfo=UTC),
        note=None,
        legs=[Leg(account_id=account, instrument_id=usdt, role="in", quantity=Decimal("1000"))],
    )
    assert isinstance(created, int)
    _sell(db, account, usdt, eur, quantity="1000", proceeds="810", occurred_at=SOLD)

    report = section23.year_report(db, FakeReferenceRateSource(), year=2025)

    (disposal,) = report.disposals
    (consumption,) = disposal.consumptions
    assert consumption.long_term is True
    assert consumption.basis_source == "market_value"
    assert consumption.basis_eur is None
    assert consumption.gain_eur is None
    assert report.awaiting_valuation == ()
    assert report.total_gain_eur == Decimal("0")
    assert report.freigrenze is not None


def test_an_exempt_disposal_awaiting_valuation_blocks_nothing(db):
    """A long-term crypto-crypto trade cannot move the total it is excluded
    from, so the year still states its total and verdict."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    eth = instruments.create_native_coin(db, symbol="ETH", name="Ether", chain="ethereum")
    _keep(db, btc, account)
    _keep(db, eth, account)
    _buy(
        db,
        account,
        btc,
        eur,
        quantity="1",
        cost="10000",
        occurred_at=datetime(2024, 1, 10, 12, 0, tzinfo=UTC),
    )
    created = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=SOLD,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=btc, role="out", quantity=Decimal("1")),
            Leg(account_id=account, instrument_id=eth, role="in", quantity=Decimal("15")),
        ],
    )
    assert isinstance(created, int)

    report = section23.year_report(db, FakeReferenceRateSource(), year=2025)

    (disposal,) = report.disposals
    assert disposal.consumptions[0].long_term is True
    assert report.awaiting_valuation == ()
    assert report.total_gain_eur == Decimal("0")
    assert report.freigrenze is not None


def test_a_fee_charged_against_the_disposal_is_its_cost(db):
    """ADR-0011: charged against the disposal leg, a fee is that disposal's
    own cost — it reduces the gain and never enters any basis."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _buy(db, account, btc, eur, quantity="1", cost="10000", occurred_at=BOUGHT)
    created = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=SOLD,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=btc, role="out", quantity=Decimal("1")),
            Leg(account_id=account, instrument_id=eur, role="in", quantity=Decimal("12000")),
            Leg(
                account_id=account,
                instrument_id=eur,
                role="fee",
                quantity=Decimal("25"),
                charged_against=0,
            ),
        ],
    )
    assert isinstance(created, int)

    report = section23.year_report(db, FakeReferenceRateSource(), year=2025)

    (disposal,) = report.disposals
    assert disposal.proceeds_eur == Decimal("12000")
    assert disposal.costs_eur == Decimal("25")
    (consumption,) = disposal.consumptions
    assert consumption.gain_eur == Decimal("1975")
    assert report.total_gain_eur == Decimal("1975")

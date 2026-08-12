"""Securities disposals (ticket 46): share and fund sales consume Tax Lots
FIFO within the Depot that held them, no holding period ever exempts them,
the gain is stated in EUR at the rates of its own event dates, fund gains
carry their Teilfreistellung, and every disposal reduces to one Section 20
Event routed to the pot its instrument type demands — computing no tax of
its own (ADR-0013).

The seams are the §20 engine's one public read — `section20.year_report`,
driven over real Postgres with the ledger built through the repositories and
rates through a fake of the reference-rate port — the producer's own detail
read (`security_disposals.disposals_through`) where a test asserts the
pairing itself, and the named refusals.
"""

from datetime import UTC, date, datetime
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
from open_leprechaun.services import disposals, section20, security_disposals
from open_leprechaun.services.disposals import LotShortfallError
from open_leprechaun.services.statutory import StatutoryValueUnsetError

BOUGHT = datetime(2031, 2, 10, 12, 0, tzinfo=UTC)
SOLD = datetime(2031, 6, 3, 12, 0, tzinfo=UTC)


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


@pytest.fixture
def store(db):
    """The migrated database with this file's statutory mutation years wiped —
    statutory rows outlive the shared `db` fixture, which resets only the
    ledger's tables."""
    with db.begin() as connection:
        connection.execute(text("DELETE FROM statutory_value WHERE year >= 2030"))
    return db


def _statutes(store, *, year=2031):
    """The values the §20 assessment reads for a year no migration seeds."""
    for key, value in (
        ("saver_allowance_single", "1000"),
        ("flat_rate", "0.25"),
        ("solidarity_surcharge_rate", "0.055"),
    ):
        statutory.upsert_value(
            store, year=year, key=key, value=Decimal(value), source="a test value"
        )


def _exemption_rates(store, *, year=2031):
    """The Teilfreistellung rates as §20 InvStG states them, entered for the
    test year the way the migration enters them for the deliverable years."""
    for key, value in (
        ("partial_exemption_aktienfonds", "0.30"),
        ("partial_exemption_mischfonds", "0.15"),
        ("partial_exemption_immobilienfonds", "0.60"),
        ("partial_exemption_auslands_immobilienfonds", "0.80"),
        ("partial_exemption_sonstige", "0"),
    ):
        statutory.upsert_value(
            store, year=year, key=key, value=Decimal(value), source="§ 20 InvStG"
        )


def _depot(db, platform_name="Scalable Capital", name="Depot"):
    """A Depot: an Account under a broker Platform whose withholding
    behaviour is set — ticket 43 refuses a position against an unknown."""
    platform_id = platforms.create_platform(db, name=platform_name, kind="broker")
    assert platforms.set_withholding(db, platform_id, behaviour="none") is None
    created = platforms.create_account(db, platform_id, name=name)
    assert isinstance(created, int)
    return created


def _eur(db):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    return eur


def _usd(db):
    return instruments.create_cash(db, symbol="USD", name="US Dollar")


def _share(db, symbol="SAP", isin="DE0007164600"):
    return instruments.create_security(db, symbol=symbol, name=symbol, type="share", isin=isin)


def _fund(db, *, category, symbol="IWDA", isin="IE00B4L5Y983", type="etf"):
    """A fund; None leaves it unclassified — no category, and therefore no
    source to pair with it (the schema CHECK-pairs the two)."""
    return instruments.create_security(
        db,
        symbol=symbol,
        name=symbol,
        type=type,
        isin=isin,
        fund_category=category,
        fund_category_source="provider" if category is not None else None,
        distribution_policy="accumulating" if category is not None else None,
    )


def _keep(db, instrument, account):
    settled = stances.classify(db, instrument, stance="kept", account_id=account)
    assert not isinstance(settled, stances.Refusal)


def _buy(db, account, instrument, cash, *, quantity, cost, fee=None, occurred_at=BOUGHT):
    """A purchase; a fee is charged against the acquired position — an
    Anschaffungsnebenkost, part of the basis (services/lots)."""
    legs = [
        Leg(account_id=account, instrument_id=instrument, role="in", quantity=Decimal(quantity)),
        Leg(account_id=account, instrument_id=cash, role="out", quantity=Decimal(cost)),
    ]
    if fee is not None:
        legs.append(
            Leg(
                account_id=account,
                instrument_id=cash,
                role="fee",
                quantity=Decimal(fee),
                charged_against=0,
            )
        )
    created = transactions.create_transaction(
        db, type="trade", occurred_at=occurred_at, note=None, legs=legs
    )
    assert isinstance(created, int)
    return created


def _sell(db, account, instrument, cash, *, quantity, proceeds, fee=None, occurred_at=SOLD):
    """A sale; a fee is charged against the disposed position — a
    Veräußerungskost, never part of any basis (ADR-0011)."""
    legs = [
        Leg(account_id=account, instrument_id=instrument, role="out", quantity=Decimal(quantity)),
        Leg(account_id=account, instrument_id=cash, role="in", quantity=Decimal(proceeds)),
    ]
    if fee is not None:
        legs.append(
            Leg(
                account_id=account,
                instrument_id=cash,
                role="fee",
                quantity=Decimal(fee),
                charged_against=0,
            )
        )
    created = transactions.create_transaction(
        db, type="trade", occurred_at=occurred_at, note=None, legs=legs
    )
    assert isinstance(created, int)
    return created


def _pots(report):
    return {balance.category: balance for balance in report.balances}


def _the_disposal(store, source=None, *, through_year=2031):
    (disposal,) = security_disposals.disposals_through(
        store, source or FakeReferenceRateSource(), through_year=through_year
    )
    return disposal


# --- The gain and its pot ----------------------------------------------------


def test_a_share_sale_gain_is_capital_income_in_the_aktien_pot(store):
    """§20 Abs. 2 Satz 1 Nr. 1 EStG: the sale of a share is capital income,
    and its gain belongs to the share-sale pot alone (§20 Abs. 6 Satz 4
    EStG) — reduced to one Section 20 Event that carries the disposing leg
    and computes no tax of its own (ADR-0013)."""
    _statutes(store)
    depot, eur = _depot(store), _eur(store)
    share = _share(store)
    _keep(store, share, depot)
    _buy(store, depot, share, eur, quantity="10", cost="1000")
    _sell(store, depot, share, eur, quantity="10", proceeds="1500")

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    assert report.awaiting_valuation == ()
    pots = _pots(report)
    assert pots["aktien"].balance_eur == Decimal("500")
    assert pots["sonstige"].balance_eur == Decimal("0")
    (entry,) = pots["aktien"].entries
    event = entry.event
    assert event.category == "aktien"
    assert event.gross_eur == Decimal("500")
    assert event.exemption_rate == Decimal(0)
    assert event.german_withholding == section20.NO_GERMAN_WITHHOLDING
    assert event.foreign_withholding is None
    assert event.date == date(2031, 6, 3)
    assert event.source.startswith("leg:")


def test_the_gain_is_proceeds_less_basis_less_transaction_costs(store):
    """§20 Abs. 4 Satz 1 EStG: the gain is the proceeds less the
    Anschaffungskosten — a purchase fee among them — less the costs standing
    in direct material connection with the sale."""
    depot, eur = _depot(store), _eur(store)
    share = _share(store)
    _keep(store, share, depot)
    _buy(store, depot, share, eur, quantity="10", cost="1000", fee="5")
    _sell(store, depot, share, eur, quantity="10", proceeds="1500", fee="10")

    disposal = _the_disposal(store)

    assert disposal.proceeds_eur == Decimal("1500")
    assert disposal.costs_eur == Decimal("10")
    (consumption,) = disposal.consumptions
    assert consumption.basis_eur == Decimal("1005")
    assert consumption.gain_eur == Decimal("485")
    assert disposal.gain_eur == Decimal("485")


def test_the_holding_period_never_exempts_a_securities_gain(store):
    """Securities have no Haltefrist: §20 Abs. 2 EStG knows no holding
    period — the §23 exemption is confined to other Wirtschaftsgüter (§23
    Abs. 2 EStG gives §20 precedence), so a share held for years is taxable
    in full on sale."""
    _statutes(store)
    depot, eur = _depot(store), _eur(store)
    share = _share(store)
    _keep(store, share, depot)
    _buy(
        store,
        depot,
        share,
        eur,
        quantity="10",
        cost="1000",
        occurred_at=datetime(2030, 1, 10, 12, 0, tzinfo=UTC),
    )
    _sell(store, depot, share, eur, quantity="10", proceeds="1500")

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    assert _pots(report)["aktien"].balance_eur == Decimal("500")


# --- FIFO within the Depot ---------------------------------------------------


def test_fifo_within_the_depot_consumes_the_oldest_acquisition_first(store):
    """§20 Abs. 4 Satz 7 EStG: for securities held in collective custody the
    first acquired are deemed first sold — the sale consumes the oldest lot's
    basis, and a partially consumed lot keeps its remaining basis
    proportionally."""
    depot, eur = _depot(store), _eur(store)
    share = _share(store)
    _keep(store, share, depot)
    _buy(store, depot, share, eur, quantity="10", cost="1000", occurred_at=BOUGHT)
    later = datetime(2031, 3, 1, 12, 0, tzinfo=UTC)
    _buy(store, depot, share, eur, quantity="10", cost="2000", occurred_at=later)
    _sell(store, depot, share, eur, quantity="15", proceeds="3000")

    disposal = _the_disposal(store)

    first, second = disposal.consumptions
    assert first.acquired_at == BOUGHT
    assert first.quantity == Decimal("10")
    assert first.basis_eur == Decimal("1000")
    assert second.acquired_at == later
    assert second.quantity == Decimal("5")
    # Half of the second lot: half its basis travels, half remains behind.
    assert second.basis_eur == Decimal("1000")
    assert disposal.gain_eur == Decimal("1000")


def test_fifo_is_bounded_by_the_depot_that_held_the_shares(store):
    """§20 Abs. 4 Satz 7 EStG, depotbezogen: FIFO runs within one Depot and
    Instrument — a sale from the second Depot consumes its own lot, never the
    older one resting in the first."""
    depot, eur = _depot(store), _eur(store)
    other = _depot(store, platform_name="Trade Republic", name="Zweitdepot")
    share = _share(store)
    _keep(store, share, depot)
    _keep(store, share, other)
    _buy(store, depot, share, eur, quantity="10", cost="1000", occurred_at=BOUGHT)
    later = datetime(2031, 3, 1, 12, 0, tzinfo=UTC)
    _buy(store, other, share, eur, quantity="10", cost="2000", occurred_at=later)
    _sell(store, other, share, eur, quantity="10", proceeds="2500")

    disposal = _the_disposal(store)

    assert disposal.account_id == other
    (consumption,) = disposal.consumptions
    assert consumption.acquired_at == later
    assert consumption.basis_eur == Decimal("2000")
    assert disposal.gain_eur == Decimal("500")


def test_a_partially_consumed_lot_keeps_its_remaining_basis_proportionally(store):
    """§20 Abs. 4 Satz 1 EStG, anteilige Anschaffungskosten: the first sale
    takes its share of the lot's basis, and the second consumes exactly what
    remained — no cent invented or lost across the two halves."""
    depot, eur = _depot(store), _eur(store)
    share = _share(store)
    _keep(store, share, depot)
    _buy(store, depot, share, eur, quantity="10", cost="1000")
    _sell(store, depot, share, eur, quantity="4", proceeds="600")
    _sell(
        store,
        depot,
        share,
        eur,
        quantity="6",
        proceeds="900",
        occurred_at=datetime(2031, 7, 1, 12, 0, tzinfo=UTC),
    )

    first, second = security_disposals.disposals_through(
        store, FakeReferenceRateSource(), through_year=2031
    )

    (taken,) = first.consumptions
    assert taken.basis_eur == Decimal("400")
    assert first.gain_eur == Decimal("200")
    (remained,) = second.consumptions
    assert remained.basis_eur == Decimal("600")
    assert second.gain_eur == Decimal("300")


# --- EUR at the rates of the respective event dates --------------------------


def test_currency_movement_on_the_security_is_part_of_the_gain(store):
    """§20 Abs. 4 Satz 1 EStG: acquisition cost and proceeds each convert at
    their own event date's reference rate, so a position flat in its foreign
    currency still gains what the currency moved — inside the securities
    gain, never a separate item."""
    depot, eur, usd = _depot(store), _eur(store), _usd(store)
    share = _share(store, symbol="AAPL", isin="US0378331005")
    _keep(store, share, depot)
    _keep(store, usd, depot)
    funding = datetime(2031, 2, 3, 12, 0, tzinfo=UTC)
    _buy(store, depot, usd, eur, quantity="1000", cost="800", occurred_at=funding)
    _buy(store, depot, share, usd, quantity="10", cost="1000", occurred_at=BOUGHT)
    _sell(store, depot, share, usd, quantity="10", proceeds="1000", occurred_at=SOLD)
    source = FakeReferenceRateSource(
        rates=[
            ReferenceRate("USD", date(2031, 2, 10), Decimal("1.25")),
            ReferenceRate("USD", date(2031, 6, 3), Decimal("1.00")),
        ]
    )

    disposals = security_disposals.disposals_through(store, source, through_year=2031)

    (disposal,) = disposals
    # 1000 USD at 1.25 on the acquisition date, 1000 USD at 1.00 on the sale.
    assert disposal.proceeds_eur == Decimal("1000")
    (consumption,) = disposal.consumptions
    assert consumption.basis_eur == Decimal("800")
    assert disposal.gain_eur == Decimal("200")


def test_a_foreign_currency_basis_pro_rates_over_partial_consumptions(store):
    """§20 Abs. 4 Satz 1 EStG: a basis stated at report time from a
    foreign-currency purchase pro-rates over partial sales like any other —
    the two halves together consume exactly the acquisition's EUR cost."""
    depot, eur, usd = _depot(store), _eur(store), _usd(store)
    share = _share(store, symbol="AAPL", isin="US0378331005")
    _keep(store, share, depot)
    _keep(store, usd, depot)
    funding = datetime(2031, 2, 3, 12, 0, tzinfo=UTC)
    _buy(store, depot, usd, eur, quantity="1000", cost="800", occurred_at=funding)
    _buy(store, depot, share, usd, quantity="10", cost="1000", occurred_at=BOUGHT)
    _sell(store, depot, share, usd, quantity="4", proceeds="400", occurred_at=SOLD)
    _sell(
        store,
        depot,
        share,
        usd,
        quantity="6",
        proceeds="600",
        occurred_at=datetime(2031, 7, 1, 12, 0, tzinfo=UTC),
    )
    source = FakeReferenceRateSource(
        rates=[
            ReferenceRate("USD", date(2031, 2, 10), Decimal("1.25")),
            ReferenceRate("USD", date(2031, 6, 3), Decimal("1.00")),
            ReferenceRate("USD", date(2031, 7, 1), Decimal("1.00")),
        ]
    )

    first, second = security_disposals.disposals_through(store, source, through_year=2031)

    (taken,) = first.consumptions
    (remained,) = second.consumptions
    # 1000 USD at 1.25 cost 800 EUR; the halves split it 320 / 480 exactly.
    assert taken.basis_eur == Decimal("320")
    assert remained.basis_eur == Decimal("480")
    assert taken.basis_eur + remained.basis_eur == Decimal("800")


# --- Teilfreistellung and routing --------------------------------------------


def test_a_fund_gain_is_reduced_by_its_partial_exemption(store):
    """§20 Abs. 1 Satz 1 InvStG: thirty percent of an Aktienfonds gain is
    exempt. The disposal states the gross gain and the rate; the engine
    exempts before the event enters its pot (ADR-0013)."""
    _statutes(store)
    _exemption_rates(store)
    depot, eur = _depot(store), _eur(store)
    fund = _fund(store, category="aktienfonds")
    _keep(store, fund, depot)
    _buy(store, depot, fund, eur, quantity="10", cost="1000")
    _sell(store, depot, fund, eur, quantity="10", proceeds="2000")

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    pots = _pots(report)
    (entry,) = pots["sonstige"].entries
    assert entry.event.gross_eur == Decimal("1000")
    assert entry.event.exemption_rate == Decimal("0.30")
    assert entry.counted_eur == Decimal("700")
    assert pots["sonstige"].balance_eur == Decimal("700")


def test_each_fund_category_wears_its_own_statutory_rate(store):
    """§20 Abs. 3 Satz 1 Nr. 2 InvStG: an Auslands-Immobilienfonds is exempt
    at eighty percent — the rate is the category's per-year configuration,
    never a constant in logic."""
    _statutes(store)
    _exemption_rates(store)
    depot, eur = _depot(store), _eur(store)
    fund = _fund(store, category="auslands_immobilienfonds", symbol="REIT", isin="LU0489337690")
    _keep(store, fund, depot)
    _buy(store, depot, fund, eur, quantity="10", cost="1000")
    _sell(store, depot, fund, eur, quantity="10", proceeds="2000")

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    (entry,) = _pots(report)["sonstige"].entries
    assert entry.event.exemption_rate == Decimal("0.80")
    assert entry.counted_eur == Decimal("200")


def test_share_gains_route_to_aktien_and_every_other_type_to_sonstige(store):
    """§20 Abs. 6 Satz 4 EStG: the share pot holds share sales alone — fund,
    bond and certificate gains are general capital income, each type routed
    by what the instrument is, never by what any producer decides."""
    _statutes(store)
    _exemption_rates(store)
    depot, eur = _depot(store), _eur(store)
    share = _share(store)
    fund = _fund(store, category="sonstige", symbol="MMF", isin="LU0904783114", type="fund")
    bond = instruments.create_security(
        store, symbol="BUND", name="Bund 2035", type="bond", isin="DE0001102341"
    )
    certificate = instruments.create_security(
        store, symbol="TURBO", name="A certificate", type="certificate", isin="DE000VU12345"
    )
    for security in (share, fund, bond, certificate):
        _keep(store, security, depot)
        _buy(store, depot, security, eur, quantity="1", cost="100")
        _sell(store, depot, security, eur, quantity="1", proceeds="150")

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    pots = _pots(report)
    assert pots["aktien"].balance_eur == Decimal("50")
    assert pots["sonstige"].balance_eur == Decimal("150")
    assert {entry.event.category for entry in pots["sonstige"].entries} == {"sonstige"}


def test_a_fund_loss_is_reduced_by_the_same_exemption(store):
    """§21 InvStG: the Teilfreistellung exempts losses exactly as it exempts
    income — a fund loss enters its pot reduced, symmetrically."""
    _statutes(store)
    _exemption_rates(store)
    depot, eur = _depot(store), _eur(store)
    fund = _fund(store, category="aktienfonds")
    _keep(store, fund, depot)
    _buy(store, depot, fund, eur, quantity="10", cost="2000")
    _sell(store, depot, fund, eur, quantity="10", proceeds="1000")

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    (entry,) = _pots(report)["sonstige"].entries
    assert entry.event.gross_eur == Decimal("-1000")
    assert entry.counted_eur == Decimal("-700")


# --- A transfer between the Admin's own Depots -------------------------------


def test_a_depot_transfer_preserves_lot_identity_and_acquisition_dates(store):
    """§43 Abs. 1 Satz 5 EStG: a transfer between the Admin's own Depots is
    no disposal — the confirmed match (ticket 16) carries the lots across
    with their acquisition instants and bases, so the later sale consumes the
    original acquisition, FIFO in the receiving Depot."""
    depot, eur = _depot(store), _eur(store)
    other = _depot(store, platform_name="Trade Republic", name="Zweitdepot")
    share = _share(store)
    _keep(store, share, depot)
    _buy(store, depot, share, eur, quantity="10", cost="1000", occurred_at=BOUGHT)
    out_transaction = transactions.create_transaction(
        store,
        type="transfer_out",
        occurred_at=datetime(2031, 4, 1, 12, 0, tzinfo=UTC),
        note=None,
        legs=[Leg(account_id=depot, instrument_id=share, role="out", quantity=Decimal("10"))],
    )
    in_transaction = transactions.create_transaction(
        store,
        type="transfer_in",
        occurred_at=datetime(2031, 4, 1, 13, 0, tzinfo=UTC),
        note=None,
        legs=[Leg(account_id=other, instrument_id=share, role="in", quantity=Decimal("10"))],
    )
    with store.connect() as connection:
        out_leg, in_leg = (
            connection.execute(
                text("SELECT id FROM transaction_leg WHERE transaction_id = :id"),
                {"id": transaction_id},
            ).scalar_one()
            for transaction_id in (out_transaction, in_transaction)
        )
    decided = transfer_matches.decide(
        store, out_leg_id=out_leg, in_leg_id=in_leg, verdict="confirmed"
    )
    assert isinstance(decided, int)
    _sell(store, other, share, eur, quantity="10", proceeds="1500")

    disposal = _the_disposal(store)

    assert disposal.account_id == other
    (consumption,) = disposal.consumptions
    assert consumption.acquired_at == BOUGHT
    assert consumption.basis_eur == Decimal("1000")
    assert disposal.gain_eur == Decimal("500")


# --- The named refusals ------------------------------------------------------


def test_an_unclassified_fund_disposal_refuses_by_name(store):
    """A fund with no Teilfreistellung classification blocks rather than
    silently assuming a rate (CONTEXT.md, ticket 44) — the refusal names the
    fund so the Admin knows what to classify."""
    _statutes(store)
    _exemption_rates(store)
    depot, eur = _depot(store), _eur(store)
    fund = _fund(store, category=None)
    _keep(store, fund, depot)
    _buy(store, depot, fund, eur, quantity="10", cost="1000")
    _sell(store, depot, fund, eur, quantity="10", proceeds="2000")

    with pytest.raises(security_disposals.UnclassifiedSecurityError, match="IWDA"):
        section20.year_report(store, FakeReferenceRateSource(), year=2031)


def test_a_security_still_typed_unknown_refuses_by_name(store):
    """A security typed `unknown` cannot say which pot its gain belongs to,
    let alone whether a Teilfreistellung applies — its disposal refuses until
    the review (ticket 44) settles what the thing actually is."""
    _statutes(store)
    depot, eur = _depot(store), _eur(store)
    mystery = instruments.create_security(
        store,
        symbol="XX123",
        name="XX123",
        type="unknown",
        isin="XS0000000001",
        needs_review=True,
    )
    _keep(store, mystery, depot)
    _buy(store, depot, mystery, eur, quantity="10", cost="1000")
    _sell(store, depot, mystery, eur, quantity="10", proceeds="2000")

    with pytest.raises(security_disposals.UnclassifiedSecurityError, match="XX123"):
        section20.year_report(store, FakeReferenceRateSource(), year=2031)


def test_a_missing_partial_exemption_rate_refuses_by_name(store):
    """§20 InvStG rates are per-year configuration with a cited source — a
    year whose rate is unset refuses by name instead of defaulting, exactly
    as every statutory value does (ticket 09)."""
    _statutes(store)
    depot, eur = _depot(store), _eur(store)
    fund = _fund(store, category="aktienfonds")
    _keep(store, fund, depot)
    _buy(store, depot, fund, eur, quantity="10", cost="1000")
    _sell(store, depot, fund, eur, quantity="10", proceeds="2000")

    with pytest.raises(StatutoryValueUnsetError, match="partial_exemption_aktienfonds"):
        section20.year_report(store, FakeReferenceRateSource(), year=2031)


def test_a_disposal_exceeding_the_depot_s_lots_is_a_hard_error(store):
    """A securities disposal no lots vouch for is a missing acquisition —
    refused by name, never a silent zero-basis fill."""
    _statutes(store)
    depot, eur = _depot(store), _eur(store)
    share = _share(store)
    _keep(store, share, depot)
    _sell(store, depot, share, eur, quantity="10", proceeds="1500")

    with pytest.raises(LotShortfallError, match="SAP"):
        section20.year_report(store, FakeReferenceRateSource(), year=2031)

    # The same gap is enumerated for the pre-flight (ticket 25): the shared
    # walk covers securities like every lot-consuming family, so the blocker
    # names it instead of failing on the first.
    assert disposals.lot_shortfalls(store, through_year=2031) == ["SAP"]


def test_a_basis_no_rule_can_state_leaves_the_year_awaiting(store):
    """Splitting one consideration across two positions needs their relative
    market values (services/lots) — the disposal waits for a valuation by
    name, never guesses one (ADR-0017)."""
    _statutes(store)
    depot, eur = _depot(store), _eur(store)
    share = _share(store)
    other = _share(store, symbol="BMW", isin="DE0005190003")
    _keep(store, share, depot)
    _keep(store, other, depot)
    bundle = transactions.create_transaction(
        store,
        type="trade",
        occurred_at=BOUGHT,
        note=None,
        legs=[
            Leg(account_id=depot, instrument_id=share, role="in", quantity=Decimal("10")),
            Leg(account_id=depot, instrument_id=other, role="in", quantity=Decimal("10")),
            Leg(account_id=depot, instrument_id=eur, role="out", quantity=Decimal("2000")),
        ],
    )
    assert isinstance(bundle, int)
    _sell(store, depot, share, eur, quantity="10", proceeds="1500")

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    assert report.balances is None
    assert report.assessment is None
    assert len(report.awaiting_valuation) == 1
    assert report.awaiting_valuation[0].startswith("leg:")


# --- The vocabulary holds together -------------------------------------------


def test_the_producer_speaks_the_engine_s_categories():
    """The pots are the engine's vocabulary (ADR-0013) — the producer routes
    into them and must never invent one of its own."""
    assert security_disposals.SHARE_CATEGORY in section20.CATEGORIES
    assert security_disposals.OTHER_CATEGORY in section20.CATEGORIES

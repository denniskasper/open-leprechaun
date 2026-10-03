"""The Vorabpauschale (ticket 53, §18 InvStG): the annual advance lump sum
on a fund, per fund per year, declared in the year after the one it derives
from and deducted from the eventual sale (§19 Abs. 1 Satz 3 InvStG).

Nothing can accrue one until a fund has been held across a year boundary, so
every figure asserted here was computed by hand from the statute and the
Anlage KAP-INV's own calculation block (docs/research/tax-form-lines.md,
lines 33-45) — never by the code under test. Each rule has a fixture that
fails if the rule is dropped.

The seams: the pure per-unit rule and its calendar (`per_unit`,
`twelfths_held`, `accrual_date`); the producer's read
(`advance_lump_sums.accruals_through`) and the §20 engine's one public read
(`section20.year_report`) over real Postgres; the securities producer's
detail read where a test asserts the deduction itself; the pre-flight
registry; and the HTTP API for the entered values.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.rates import get_reference_rate_source
from open_leprechaun.repositories import (
    fund_redemption_values,
    instruments,
    platforms,
    security_prices,
    stances,
    statutory,
    transactions,
    transfer_matches,
)
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.services import advance_lump_sums, preflight, section20, security_disposals
from open_leprechaun.services.advance_lump_sums import FundValueUnsetError
from open_leprechaun.services.rounding import cents
from open_leprechaun.services.statutory import StatutoryValueUnsetError

IN_JANUARY = datetime(2031, 1, 15, 12, 0, tzinfo=UTC)
IN_MARCH = datetime(2031, 3, 10, 12, 0, tzinfo=UTC)
IN_JUNE = datetime(2031, 6, 3, 12, 0, tzinfo=UTC)
NEXT_MARCH = datetime(2032, 3, 1, 12, 0, tzinfo=UTC)
NEXT_SEPTEMBER = datetime(2032, 9, 1, 12, 0, tzinfo=UTC)

# --- The rule, per unit (§18 Abs. 1 InvStG) ---------------------------------


def _per_unit(*, start="100", end="110", distributions="0", base_rate="0.02", factor="0.7"):
    return advance_lump_sums.per_unit(
        start_of_year_eur=Decimal(start),
        end_of_year_eur=Decimal(end),
        distributions_eur=Decimal(distributions),
        base_rate=Decimal(base_rate),
        factor=Decimal(factor),
    )


def test_the_base_yield_is_the_start_value_times_the_base_rate_times_the_factor():
    """§18 Abs. 1 Satz 2 InvStG: 100.00 x 2 % x 70 % = 1.40 per unit — and a
    fund that rose by more and distributed nothing accrues exactly that."""
    computed = _per_unit()

    assert computed.base_yield_eur == Decimal("1.40")
    assert computed.amount_eur == Decimal("1.40")


def test_the_years_distributions_reduce_the_amount():
    """§18 Abs. 1 Satz 1 InvStG: the Vorabpauschale is what the distributions
    fall short of the base yield by — 1.40 less 0.50 distributed is 0.90."""
    assert _per_unit(distributions="0.50").amount_eur == Decimal("0.90")


def test_distributions_above_the_base_yield_floor_the_amount_at_zero():
    """A fund that distributed 2.00 against a base yield of 1.40 accrues
    nothing — never a negative amount."""
    assert _per_unit(distributions="2.00").amount_eur == Decimal("0")


def test_the_amount_is_capped_at_the_years_increase_in_redemption_value():
    """§18 Abs. 1 Satz 3 InvStG: a fund that rose by 0.60 accrues no more
    than 0.60, whatever its base yield of 1.40."""
    assert _per_unit(end="100.60").amount_eur == Decimal("0.60")


def test_distributions_are_deducted_before_the_cap_applies():
    """The order decides: base yield 1.40 less 0.50 distributed is 0.90, then
    capped at the 0.60 the redemption value rose — 0.60. Capping first and
    deducting second would state 0.10. (The statute's Mehrbetrag adds the
    distributions back to the rise, 1.10, before deducting them — the same
    0.60.)"""
    assert _per_unit(end="100.60", distributions="0.50").amount_eur == Decimal("0.60")


def test_a_fund_whose_value_fell_over_the_year_produces_zero():
    """A loss never becomes deemed income: 100.00 down to 95.00 accrues
    nothing, though the base yield stands at 1.40."""
    computed = _per_unit(end="95")

    assert computed.base_yield_eur == Decimal("1.40")
    assert computed.amount_eur == Decimal("0")


# --- The calendar (§18 Abs. 2 und 3 InvStG) ---------------------------------


def test_one_twelfth_goes_for_each_full_month_preceding_the_month_of_acquisition():
    """§18 Abs. 2 InvStG: bought in March, January and February precede —
    ten twelfths remain. Bought in January nothing precedes; bought in
    December eleven months do. The day of the month plays no part."""
    assert advance_lump_sums.twelfths_held(date(2031, 3, 31), year=2031) == 10
    assert advance_lump_sums.twelfths_held(date(2031, 1, 15), year=2031) == 12
    assert advance_lump_sums.twelfths_held(date(2031, 12, 1), year=2031) == 1


def test_a_unit_acquired_in_an_earlier_year_accrues_the_whole_year():
    assert advance_lump_sums.twelfths_held(date(2029, 11, 5), year=2031) == 12


def test_accrual_is_the_first_banking_day_of_the_following_year():
    """§18 Abs. 3 InvStG: the amount derived from 2031 accrues on 2 January
    2032, a Friday. New Year's Day never is one; where 2 January falls on a
    weekend the Monday after is — 4 January 2027 for 2026, 3 January 2028
    for 2027."""
    assert advance_lump_sums.accrual_date(2031) == date(2032, 1, 2)
    assert advance_lump_sums.accrual_date(2026) == date(2027, 1, 4)
    assert advance_lump_sums.accrual_date(2027) == date(2028, 1, 3)


# --- The ledger under the rule ----------------------------------------------


class FakeReferenceRateSource:
    """The reference-rate port's fake — every fixture here is in EUR, so it
    is never asked for a rate."""

    def daily_rates(self, currency, start, end):
        return []


@pytest.fixture
def client(db):
    """The API bound to the migrated test database, rates through the fake."""
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_reference_rate_source] = FakeReferenceRateSource
    with TestClient(app) as client:
        yield client


@pytest.fixture
def store(db):
    """The migrated database with this file's statutory mutation years wiped —
    statutory rows outlive the shared `db` fixture, which resets only the
    ledger's tables."""
    with db.begin() as connection:
        connection.execute(text("DELETE FROM statutory_value WHERE year >= 2030"))
    return db


def _statutes(store, *, year):
    """What the §20 assessment and the fund's Teilfreistellung read for a
    year no migration seeds."""
    for key, value in (
        ("saver_allowance_single", "1000"),
        ("flat_rate", "0.25"),
        ("solidarity_surcharge_rate", "0.055"),
        ("partial_exemption_aktienfonds", "0.30"),
    ):
        statutory.upsert_value(
            store, year=year, key=key, value=Decimal(value), source="a test value"
        )


def _rates(store, *, year=2031, base_rate="0.02", factor="0.7"):
    """The Basiszins and the factor for the year an amount derives from —
    2 % x 70 %, so one unit starting the year at 100.00 has a base yield of
    1.40."""
    for key, value in (
        ("advance_lump_sum_base_rate", base_rate),
        ("advance_lump_sum_factor", factor),
    ):
        statutory.upsert_value(
            store, year=year, key=key, value=Decimal(value), source="a test value"
        )


def _values(store, fund, *, year=2031, start="100", end="110", distributions="0"):
    fund_redemption_values.upsert_value(
        store,
        instrument_id=fund,
        year=year,
        start_of_year_eur=Decimal(start),
        end_of_year_eur=Decimal(end),
        distributions_eur=Decimal(distributions),
        source="the fund's annual report",
    )


def _depot(db, platform_name="Scalable Capital", name="Depot"):
    platform_id = platforms.create_platform(db, name=platform_name, kind="broker")
    assert platforms.set_withholding(db, platform_id, behaviour="none") is None
    created = platforms.create_account(db, platform_id, name=name)
    assert isinstance(created, int)
    return created


def _eur(db):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    return eur


def _fund(db, depot, *, symbol="IWDA", isin="IE00B4L5Y983"):
    """An accumulating Aktienfonds, kept in the Depot."""
    fund = instruments.create_security(
        db,
        symbol=symbol,
        name=symbol,
        type="etf",
        isin=isin,
        fund_category="aktienfonds",
        fund_category_source="provider",
        distribution_policy="accumulating",
    )
    settled = stances.classify(db, fund, stance="kept", account_id=depot)
    assert not isinstance(settled, stances.Refusal)
    return fund


def _trade(db, account, *, gives, receives, occurred_at):
    created = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=occurred_at,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=gives[0], role="out", quantity=Decimal(gives[1])),
            Leg(
                account_id=account,
                instrument_id=receives[0],
                role="in",
                quantity=Decimal(receives[1]),
            ),
        ],
    )
    assert isinstance(created, int)
    return created


def _buy(db, account, fund, eur, *, quantity, cost, occurred_at=IN_JANUARY):
    return _trade(
        db, account, gives=(eur, cost), receives=(fund, quantity), occurred_at=occurred_at
    )


def _sell(db, account, fund, eur, *, quantity, proceeds, occurred_at):
    return _trade(
        db, account, gives=(fund, quantity), receives=(eur, proceeds), occurred_at=occurred_at
    )


def _held_across_2031(store, *, quantity="10", cost="1000", occurred_at=IN_JANUARY):
    """A fund bought in 2031 and still held when 2032 begins, with every
    input the 2031 amount needs entered: 1.40 per unit."""
    depot, eur = _depot(store), _eur(store)
    fund = _fund(store, depot)
    _buy(store, depot, fund, eur, quantity=quantity, cost=cost, occurred_at=occurred_at)
    _rates(store)
    _values(store, fund)
    return depot, eur, fund


def _report(store, *, year):
    _statutes(store, year=year)
    return section20.year_report(store, FakeReferenceRateSource(), year=year)


# --- Accrual: who held what, when --------------------------------------------


def test_a_fund_held_across_the_year_boundary_accrues_per_unit_times_units(store):
    """Ten units held through all of 2031 at 1.40 per unit: 14.00."""
    depot, _, fund = _held_across_2031(store)

    (accrued,) = advance_lump_sums.accruals_through(store, through_year=2032)

    assert (accrued.account_id, accrued.instrument_id) == (depot, fund)
    assert accrued.per_unit.amount_eur == Decimal("1.40")
    assert accrued.quantity == Decimal("10")
    assert accrued.amount_eur == Decimal("14.00")
    assert accrued.values_source == "the fund's annual report"


def test_the_year_it_derives_from_and_the_year_it_is_declared_in_are_distinct(store):
    """§18 Abs. 3 InvStG: the amount computed from 2031's prices counts as
    received on 2 January 2032 — it belongs in the 2032 return and in no
    part of the 2031 one."""
    _held_across_2031(store)

    assert advance_lump_sums.accruals_through(store, through_year=2031) == ()
    (accrued,) = advance_lump_sums.accruals_through(store, through_year=2032)
    assert accrued.derived_year == 2031
    assert accrued.declared_year == 2032
    assert accrued.accrued_on == date(2032, 1, 2)


def test_a_fund_sold_during_the_year_produces_none(store):
    """Not held at the accrual moment, no Vorabpauschale — and none of the
    year's inputs is even asked for."""
    depot, eur = _depot(store), _eur(store)
    fund = _fund(store, depot)
    _buy(store, depot, fund, eur, quantity="10", cost="1000")
    _sell(store, depot, fund, eur, quantity="10", proceeds="1100", occurred_at=IN_JUNE)

    assert advance_lump_sums.accruals_through(store, through_year=2032) == ()
    assert advance_lump_sums.missing_inputs(store, through_year=2032) == []


def test_only_the_units_still_held_at_the_accrual_accrue(store):
    """Four of ten units sold in June: the six that crossed into 2032 accrue
    6 x 1.40 = 8.40."""
    depot, eur, fund = _held_across_2031(store)
    _sell(store, depot, fund, eur, quantity="4", proceeds="440", occurred_at=IN_JUNE)

    (accrued,) = advance_lump_sums.accruals_through(store, through_year=2032)

    assert accrued.quantity == Decimal("6")
    assert accrued.amount_eur == Decimal("8.40")


def test_a_lot_bought_mid_year_accrues_only_its_twelfths(store):
    """§18 Abs. 2 InvStG: six units bought in March keep ten twelfths —
    6 x 1.40 x 10/12 = 7.00, not the 8.40 a full year would state."""
    _held_across_2031(store, quantity="6", cost="600", occurred_at=IN_MARCH)

    (accrued,) = advance_lump_sums.accruals_through(store, through_year=2032)

    (lot,) = accrued.lots
    assert lot.twelfths == 10
    assert accrued.amount_eur == Decimal("7.00")


def test_the_twelfths_reduce_the_amount_after_the_cap_not_the_base_yield_before_it(store):
    """§18 Abs. 2 InvStG reduces the *Vorabpauschale*, and the Anlage KAP-INV
    reduces its line 41 — the figure after the cap — in line 42. A fund that
    rose by 0.60 per unit: 6 units x 0.60 x 10/12 = 3.00. Reducing the base
    yield first (1.40 x 10/12 = 1.1667, still capped at 0.60) would state
    3.60."""
    depot, eur = _depot(store), _eur(store)
    fund = _fund(store, depot)
    _buy(store, depot, fund, eur, quantity="6", cost="600", occurred_at=IN_MARCH)
    _rates(store)
    _values(store, fund, end="100.60")

    (accrued,) = advance_lump_sums.accruals_through(store, through_year=2032)

    assert accrued.amount_eur == Decimal("3.00")


def test_each_lot_wears_its_own_acquisition_month(store):
    """Ten units from January and six from March in one Depot: 14.00 + 7.00,
    tracked lot by lot."""
    depot, eur, fund = _held_across_2031(store)
    _buy(store, depot, fund, eur, quantity="6", cost="630", occurred_at=IN_MARCH)

    (accrued,) = advance_lump_sums.accruals_through(store, through_year=2032)

    assert [(lot.quantity, lot.twelfths, lot.amount_eur) for lot in accrued.lots] == [
        (Decimal("10"), 12, Decimal("14.00")),
        (Decimal("6"), 10, Decimal("7.00")),
    ]
    assert accrued.amount_eur == Decimal("21.00")


def test_a_lot_carried_between_depots_keeps_its_acquisition_month(store):
    """A confirmed Depotübertrag is no acquisition: six units bought in
    January and moved in March accrue the whole year, 8.40, in the Depot that
    holds them at the accrual."""
    depot, eur = _depot(store), _eur(store)
    other = _depot(store, platform_name="Trade Republic", name="Zweitdepot")
    fund = _fund(store, depot)
    _buy(store, depot, fund, eur, quantity="6", cost="600")
    out_transaction = transactions.create_transaction(
        store,
        type="transfer_out",
        occurred_at=IN_MARCH,
        note=None,
        legs=[Leg(account_id=depot, instrument_id=fund, role="out", quantity=Decimal("6"))],
    )
    in_transaction = transactions.create_transaction(
        store,
        type="transfer_in",
        occurred_at=IN_MARCH,
        note=None,
        legs=[Leg(account_id=other, instrument_id=fund, role="in", quantity=Decimal("6"))],
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
    _rates(store)
    _values(store, fund)

    (accrued,) = advance_lump_sums.accruals_through(store, through_year=2032)

    assert accrued.account_id == other
    assert accrued.amount_eur == Decimal("8.40")


# --- Refusal: nothing is approximated ---------------------------------------


def test_a_year_with_no_redemption_values_refuses_by_name(store):
    """The app refuses to compute rather than substituting a market close."""
    depot, eur = _depot(store), _eur(store)
    fund = _fund(store, depot)
    _buy(store, depot, fund, eur, quantity="10", cost="1000")
    _rates(store)
    # Market closes on both edges of the year are right there — and unused.
    security_prices.store_daily_closes(
        store,
        fund,
        source="a test close",
        closes=[(date(2031, 1, 2), Decimal("100")), (date(2031, 12, 30), Decimal("110"))],
    )

    with pytest.raises(FundValueUnsetError, match="2031 redemption values of IWDA"):
        _report(store, year=2032)


@pytest.mark.parametrize("key", ["advance_lump_sum_base_rate", "advance_lump_sum_factor"])
def test_a_year_with_no_base_rate_or_factor_refuses_by_name(store, key):
    """The Basiszins and the factor are the derived year's configuration,
    never constants in code."""
    _held_across_2031(store)
    statutory.delete_value(store, year=2031, key=key)

    with pytest.raises(StatutoryValueUnsetError, match=f"2031 value for {key}"):
        _report(store, year=2032)


def test_an_unset_input_is_a_finalisation_blocker_until_it_is_entered(store):
    """The 2032 report rests on 2031's inputs: each one unset is named by the
    pre-flight, and entering them clears it."""
    depot, eur = _depot(store), _eur(store)
    fund = _fund(store, depot)
    _buy(store, depot, fund, eur, quantity="10", cost="1000")

    (blocker,) = [
        found
        for found in preflight.blockers(store, year=2032)
        if found.kind == "missing_advance_lump_sum_inputs"
    ]
    assert blocker.count == 3
    assert "advance_lump_sum_base_rate 2031" in blocker.detail
    assert "advance_lump_sum_factor 2031" in blocker.detail
    assert "IWDA redemption values 2031" in blocker.detail
    assert blocker.resolve_path == "/settings/statutory"

    _rates(store)
    _values(store, fund)

    assert "missing_advance_lump_sum_inputs" not in {
        found.kind for found in preflight.blockers(store, year=2032)
    }
    # The 2031 report rests on none of them: nothing accrued before 2031.
    statutory.delete_value(store, year=2031, key="advance_lump_sum_base_rate")
    assert "missing_advance_lump_sum_inputs" not in {
        found.kind for found in preflight.blockers(store, year=2031)
    }


# --- The Section 20 Event ----------------------------------------------------


def test_the_amount_is_a_section_20_event_in_the_other_income_pot_less_teilfreistellung(store):
    """§16 Abs. 1 Nr. 2, §20 Abs. 1 InvStG: the 14.00 accrued on an
    Aktienfonds enters the Sonstige pot of 2032 less its 30 % partial
    exemption — 9.80 — as one event dated at the accrual."""
    depot, _, fund = _held_across_2031(store)

    report = _report(store, year=2032)

    pots = {balance.category: balance for balance in report.balances}
    (entry,) = pots["sonstige"].entries
    assert entry.event.date == date(2032, 1, 2)
    assert entry.event.gross_eur == Decimal("14.00")
    assert entry.event.exemption_rate == Decimal("0.30")
    assert entry.event.source == f"advance_lump_sum:2031:account:{depot}:instrument:{fund}"
    assert entry.counted_eur == Decimal("9.80")
    assert pots["sonstige"].balance_eur == Decimal("9.80")
    assert pots["aktien"].entries == ()
    (stated,) = report.advance_lump_sums
    assert (stated.derived_year, stated.declared_year) == (2031, 2032)


def test_the_year_it_derives_from_states_no_event(store):
    _held_across_2031(store)

    report = _report(store, year=2031)

    assert all(balance.entries == () for balance in report.balances)
    assert report.advance_lump_sums == ()


# --- Deduction at sale (§19 Abs. 1 Satz 3 InvStG) ----------------------------


def test_the_accumulated_amount_is_deducted_from_the_gain_on_sale(store):
    """Bought for 1000, sold for 1200 after 14.00 was accrued: the gain is
    200 less 14 is 186, so the 14.00 already taxed is never taxed again. In the
    2032 pot: 9.80 accrued plus 186 x 70 % = 130.20 — 140.00, exactly what
    the untouched 200 gain would have counted."""
    depot, eur, fund = _held_across_2031(store)
    _sell(store, depot, fund, eur, quantity="10", proceeds="1200", occurred_at=NEXT_MARCH)

    report = _report(store, year=2032)

    (disposal,) = report.disposals
    assert disposal.advance_lump_sums_eur == Decimal("14.00")
    assert disposal.gain_eur == Decimal("186.00")
    pots = {balance.category: balance for balance in report.balances}
    assert pots["sonstige"].balance_eur == Decimal("140.00")


def test_a_sale_before_the_accrual_deducts_nothing(store):
    """Sold in June 2031, before anything accrued: the gain stands whole."""
    depot, eur, fund = _held_across_2031(store)
    _statutes(store, year=2031)
    _sell(store, depot, fund, eur, quantity="10", proceeds="1200", occurred_at=IN_JUNE)

    (disposal,) = security_disposals.disposals_through(
        store, FakeReferenceRateSource(), through_year=2032
    )

    assert disposal.advance_lump_sums_eur == Decimal("0")
    assert disposal.gain_eur == Decimal("200")


def test_the_accrual_date_itself_decides_who_held_the_fund(store):
    """§18 Abs. 3 InvStG: a sale on New Year's Day 2032 precedes the accrual
    of 2 January — nothing accrued, nothing to deduct. A sale on 2 January
    itself was held at the accrual: 14.00 accrues and the same 14.00 comes
    off the gain."""
    depot, eur, fund = _held_across_2031(store)
    other = _fund(store, depot, symbol="VWRL", isin="IE00B3RBWM25")
    _buy(store, depot, other, eur, quantity="10", cost="1000")
    _values(store, other)
    _statutes(store, year=2032)
    _sell(
        store,
        depot,
        fund,
        eur,
        quantity="10",
        proceeds="1200",
        occurred_at=datetime(2032, 1, 1, 12, 0, tzinfo=UTC),
    )
    _sell(
        store,
        depot,
        other,
        eur,
        quantity="10",
        proceeds="1200",
        occurred_at=datetime(2032, 1, 2, 12, 0, tzinfo=UTC),
    )

    (accrued,) = advance_lump_sums.accruals_through(store, through_year=2032)
    before, on = security_disposals.disposals_through(
        store, FakeReferenceRateSource(), through_year=2032
    )

    assert accrued.instrument_id == other
    assert (before.advance_lump_sums_eur, before.gain_eur) == (Decimal("0"), Decimal("200"))
    assert (on.advance_lump_sums_eur, on.gain_eur) == (Decimal("14.00"), Decimal("186.00"))


def test_every_year_a_lot_was_held_across_accumulates_on_it(store):
    """Held across 2031 and 2032, sold in 2033: 14.00 from 2031, and from
    2032 — 110.00 at the start, 2 % x 70 % of it 1.54 a unit, the fund up to
    120.00 — another 15.40. The sale deducts 29.40."""
    depot, eur, fund = _held_across_2031(store)
    _rates(store, year=2032)
    _values(store, fund, year=2032, start="110", end="120")
    _statutes(store, year=2033)
    _sell(
        store,
        depot,
        fund,
        eur,
        quantity="10",
        proceeds="1300",
        occurred_at=datetime(2033, 3, 1, 12, 0, tzinfo=UTC),
    )

    first, second = advance_lump_sums.accruals_through(store, through_year=2033)
    (disposal,) = security_disposals.disposals_through(
        store, FakeReferenceRateSource(), through_year=2033
    )

    assert (first.derived_year, first.amount_eur) == (2031, Decimal("14.00"))
    assert (second.derived_year, second.amount_eur) == (2032, Decimal("15.40"))
    # 1 January 2033 is a Saturday: the Monday after is the first banking day.
    assert second.accrued_on == date(2033, 1, 3)
    assert disposal.advance_lump_sums_eur == Decimal("29.40")
    assert disposal.gain_eur == Decimal("270.60")


def test_a_partially_consumed_lot_keeps_its_accumulation_proportionally(store):
    """Ten units carrying 14.00: selling four deducts 5.60 and leaves 8.40 on
    the six that remain, deducted when they are sold — 14.00 in all, no cent
    invented or lost."""
    depot, eur, fund = _held_across_2031(store)
    _sell(store, depot, fund, eur, quantity="4", proceeds="480", occurred_at=NEXT_MARCH)
    _sell(store, depot, fund, eur, quantity="6", proceeds="720", occurred_at=NEXT_SEPTEMBER)
    _statutes(store, year=2032)

    first, second = security_disposals.disposals_through(
        store, FakeReferenceRateSource(), through_year=2032
    )

    assert first.advance_lump_sums_eur == Decimal("5.60")
    assert first.gain_eur == Decimal("480") - Decimal("400") - Decimal("5.60")
    assert second.advance_lump_sums_eur == Decimal("8.40")
    assert second.gain_eur == Decimal("720") - Decimal("600") - Decimal("8.40")


def test_each_consumed_lot_deducts_its_own_accumulation(store):
    """FIFO over a January lot (10 units, 14.00) and a March lot (6 units,
    7.00): selling twelve consumes all of the first and two of the second —
    14.00 + 2 x 1.40 x 10/12 = 16.33⅓."""
    depot, eur, fund = _held_across_2031(store)
    _buy(store, depot, fund, eur, quantity="6", cost="600", occurred_at=IN_MARCH)
    _sell(store, depot, fund, eur, quantity="12", proceeds="1440", occurred_at=NEXT_MARCH)
    _statutes(store, year=2032)

    (disposal,) = security_disposals.disposals_through(
        store, FakeReferenceRateSource(), through_year=2032
    )

    whole, part = disposal.consumptions
    assert whole.advance_lump_sums_eur == Decimal("14.00")
    assert cents(part.advance_lump_sums_eur) == Decimal("2.33")
    assert cents(disposal.advance_lump_sums_eur) == Decimal("16.33")


# --- Entering the inputs, with their source ----------------------------------


def test_the_api_enters_corrects_and_unsets_a_funds_values_with_their_source(store, client):
    """The redemption values are per-year configuration with the source
    shown: entered, read back verbatim beside the fund they belong to,
    corrected in place, and unset again."""
    fund = _fund(store, _depot(store))
    body = {
        "start_of_year_eur": "100.00",
        "end_of_year_eur": "110.00",
        "distributions_eur": "0",
        "source": "the fund's annual report",
    }

    assert client.put(f"/api/fund-redemption-values/{fund}/2031", json=body).status_code == 204
    listed = client.get("/api/fund-redemption-values").json()
    assert [(row["instrument_id"], row["symbol"]) for row in listed["funds"]] == [(fund, "IWDA")]
    assert listed["values"] == [{"instrument_id": fund, "year": 2031, **body}]

    corrected = {**body, "end_of_year_eur": "111.50", "source": "the corrected report"}
    assert client.put(f"/api/fund-redemption-values/{fund}/2031", json=corrected).status_code == 204
    (row,) = client.get("/api/fund-redemption-values").json()["values"]
    assert (row["end_of_year_eur"], row["source"]) == ("111.50", "the corrected report")

    assert client.delete(f"/api/fund-redemption-values/{fund}/2031").status_code == 204
    assert client.get("/api/fund-redemption-values").json()["values"] == []
    assert client.delete(f"/api/fund-redemption-values/{fund}/2031").status_code == 404


def test_the_api_refuses_values_that_are_uncited_incomplete_or_not_a_funds(store, client):
    """A citation is not optional, distributions are stated rather than
    assumed, an amount is a decimal string, and only a fund has a redemption
    price."""
    depot = _depot(store)
    fund = _fund(store, depot)
    share = instruments.create_security(
        store, symbol="SAP", name="SAP", type="share", isin="DE0007164600"
    )
    body = {
        "start_of_year_eur": "100",
        "end_of_year_eur": "110",
        "distributions_eur": "0",
        "source": "the fund's annual report",
    }

    def put(instrument, year=2031, **changes):
        changed = {key: value for key, value in {**body, **changes}.items() if value is not None}
        return client.put(f"/api/fund-redemption-values/{instrument}/{year}", json=changed)

    assert put(fund, source="  ").status_code == 422
    assert put(fund, distributions_eur=None).status_code == 422
    assert put(fund, start_of_year_eur=100).status_code == 422
    assert put(fund, end_of_year_eur="-1").status_code == 422
    assert put(fund, year=1999).status_code == 422
    assert put(share).status_code == 404
    assert client.get("/api/fund-redemption-values").json()["values"] == []


def test_generating_a_report_over_an_unset_value_refuses_with_the_sentence(store, client):
    """The refusal reaches the Admin as a 409 naming the fund and the year."""
    depot, eur = _depot(store), _eur(store)
    fund = _fund(store, depot)
    _buy(store, depot, fund, eur, quantity="10", cost="1000")
    _rates(store)
    _statutes(store, year=2032)
    for key, value in (
        ("private_sale_exemption_limit", "1000"),
        ("other_income_exemption_limit", "256"),
    ):
        statutory.upsert_value(
            store, year=2032, key=key, value=Decimal(value), source="a test value"
        )

    refused = client.post("/api/reports", json={"year": 2032})

    assert refused.status_code == 409
    assert "2031 redemption values of IWDA" in refused.json()["detail"]

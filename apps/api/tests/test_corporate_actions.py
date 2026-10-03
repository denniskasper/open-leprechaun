"""Corporate Actions (ticket 52): issuer events that change a holding without
a trade. A split rescales open lots with no taxable event, a capital return
takes basis off them instead of booking income, a spin-off or merger moves
basis by the ratio the Admin supplies and waits flagged for manual review;
every one previews before it is applied and is reversed by removing it —
the lots are derived, so there is nothing else to undo (ADR-0014).

The seam is the HTTP API over real Postgres: an event is previewed, applied
and removed through `/api/corporate-actions`, and its effect is read where
the Admin reads it — the Holdings view — and, for what a later sale states,
through the §20 producer's own read with rates from a fake of the
reference-rate port.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from open_leprechaun.ports.reference_rates import ReferenceRate
from open_leprechaun.repositories import (
    fund_redemption_values,
    instruments,
    platforms,
    stances,
    statutory,
    transactions,
    transfer_matches,
)
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.services import advance_lump_sums, lots, security_disposals
from open_leprechaun.services.preflight import blockers

BOUGHT = datetime(2031, 2, 10, 12, 0, tzinfo=UTC)
BOUGHT_AGAIN = datetime(2031, 3, 10, 12, 0, tzinfo=UTC)
EFFECTIVE = "2031-05-02T00:00:00Z"
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


def _share(db, symbol="SAP", isin="DE0007164600"):
    created = instruments.create_security(db, symbol=symbol, name=symbol, type="share", isin=isin)
    assert created is not None
    return created


def _keep(db, instrument, account):
    settled = stances.classify(db, instrument, stance="kept", account_id=account)
    assert not isinstance(settled, stances.Refusal)


def _buy(db, account, instrument, cash, *, quantity, cost, occurred_at=BOUGHT):
    created = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=occurred_at,
        note=None,
        legs=[
            Leg(
                account_id=account, instrument_id=instrument, role="in", quantity=Decimal(quantity)
            ),
            Leg(account_id=account, instrument_id=cash, role="out", quantity=Decimal(cost)),
        ],
    )
    assert isinstance(created, int)
    return created


def _sell(db, account, instrument, cash, *, quantity, proceeds, occurred_at=SOLD):
    created = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=occurred_at,
        note=None,
        legs=[
            Leg(
                account_id=account, instrument_id=instrument, role="out", quantity=Decimal(quantity)
            ),
            Leg(account_id=account, instrument_id=cash, role="in", quantity=Decimal(proceeds)),
        ],
    )
    assert isinstance(created, int)
    return created


def _held(db, instrument, *, eur):
    """A Depot holding the Instrument in two lots: 10 for 1000 EUR, then 30
    for 6000 EUR."""
    depot = _depot(db)
    _keep(db, instrument, depot)
    _buy(db, depot, instrument, eur, quantity="10", cost="1000")
    _buy(db, depot, instrument, eur, quantity="30", cost="6000", occurred_at=BOUGHT_AGAIN)
    return depot


def _split(instrument, *, new="2", old="1", effective_at=EFFECTIVE):
    return {
        "kind": "split",
        "instrument_id": instrument,
        "effective_at": effective_at,
        "units_new": new,
        "units_old": old,
    }


def _apply(client, action):
    response = client.post("/api/corporate-actions", json=action)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _position(client, instrument, account):
    positions = client.get("/api/holdings").json()["positions"]
    matching = [
        entry
        for entry in positions
        if entry["instrument_id"] == instrument and entry["account_id"] == account
    ]
    return matching[0] if matching else None


def _the_disposal(db, source=None):
    (disposal,) = security_disposals.disposals_through(
        db, source or FakeReferenceRateSource(), through_year=2031
    )
    return disposal


# --- Split and reverse split -------------------------------------------------


def test_a_split_rescales_quantity_and_leaves_the_total_basis(db, client):
    """Two for one: the position holds twice the units at half the per-unit
    cost — the total basis is what it was."""
    eur, sap = _eur(db), _share(db)
    depot = _held(db, sap, eur=eur)

    _apply(client, _split(sap))

    position = _position(client, sap, depot)
    assert position["quantity"] == "80"
    assert position["basis_eur"] == "7000"
    assert position["average_cost_eur"] == "87.50"
    assert position["basis_gap"] is None


def test_a_split_changes_no_acquisition_date_and_books_nothing_taxable(db, client):
    """The applied split names each lot it rescaled under its original
    acquisition instant, and the ledger gained no transaction — there is no
    event for any tax engine to find."""
    eur, sap = _eur(db), _share(db)
    depot = _held(db, sap, eur=eur)
    before = client.get("/api/transactions").json()

    _apply(client, _split(sap))

    (action,) = client.get("/api/corporate-actions").json()
    assert action["kind"] == "split"
    assert action["needs_review"] is False
    assert [
        (lot["account_id"], lot["acquired_at"], lot["before"], lot["after"])
        for lot in action["lots"]
    ] == [
        (
            depot,
            "2031-02-10T12:00:00Z",
            {"instrument_id": sap, "quantity": "10", "basis_eur": "1000"},
            [{"instrument_id": sap, "quantity": "20", "basis_eur": "1000"}],
        ),
        (
            depot,
            "2031-03-10T12:00:00Z",
            {"instrument_id": sap, "quantity": "30", "basis_eur": "6000"},
            [{"instrument_id": sap, "quantity": "60", "basis_eur": "6000"}],
        ),
    ]
    assert client.get("/api/transactions").json() == before
    assert (
        security_disposals.disposals_through(db, FakeReferenceRateSource(), through_year=2031) == ()
    )


def test_a_sale_after_a_split_consumes_the_rescaled_lots(db, client):
    """Selling 20 of the new units consumes exactly the first lot — its whole
    1000 EUR basis under its original acquisition date."""
    eur, sap = _eur(db), _share(db)
    depot = _held(db, sap, eur=eur)
    _apply(client, _split(sap))
    _sell(db, depot, sap, eur, quantity="20", proceeds="2500")

    disposal = _the_disposal(db)

    (consumption,) = disposal.consumptions
    assert consumption.quantity == Decimal("20")
    assert consumption.acquired_at == BOUGHT
    assert consumption.basis_eur == Decimal("1000")
    assert disposal.gain_eur == Decimal("1500")


def test_a_reverse_split_rescales_the_other_way(db, client):
    """One for ten: a tenth of the units, the total basis untouched."""
    eur, sap = _eur(db), _share(db)
    depot = _held(db, sap, eur=eur)

    _apply(client, _split(sap, new="1", old="10"))

    position = _position(client, sap, depot)
    assert position["quantity"] == "4"
    assert position["basis_eur"] == "7000"
    assert position["average_cost_eur"] == "1750.00"


def test_a_ratio_that_does_not_divide_evenly_leaves_the_position_vouched(db, client):
    """One for three over lots of 10 and 30: the quantity on the books is the
    sum of the rescaled lots, so the basis stays stated rather than reading
    as quantity no lot vouches for."""
    eur, sap = _eur(db), _share(db)
    depot = _held(db, sap, eur=eur)

    _apply(client, _split(sap, new="1", old="3"))

    position = _position(client, sap, depot)
    assert position["basis_gap"] is None
    assert position["basis_eur"] == "7000"
    assert Decimal(position["quantity"]).quantize(Decimal("0.0001")) == Decimal("13.3333")


def test_a_split_reaches_only_what_was_held_at_its_instant(db, client):
    """A purchase after the effective instant is already stated in the new
    units, and a lot sold before it is not reopened."""
    eur, sap = _eur(db), _share(db)
    depot = _held(db, sap, eur=eur)
    _sell(
        db,
        depot,
        sap,
        eur,
        quantity="10",
        proceeds="1200",
        occurred_at=datetime(2031, 4, 1, 12, 0, tzinfo=UTC),
    )
    _buy(db, depot, sap, eur, quantity="5", cost="600", occurred_at=SOLD)

    _apply(client, _split(sap))

    position = _position(client, sap, depot)
    assert position["quantity"] == "65"
    assert position["basis_eur"] == "6600"
    (action,) = client.get("/api/corporate-actions").json()
    assert [lot["before"]["quantity"] for lot in action["lots"]] == ["30"]


def test_a_basis_awaiting_valuation_survives_a_split(db, client):
    """A share bought in USD states its basis only at report time, from the
    purchase's own legs. After a two-for-one split a sale of half the new
    units states half the purchase cost — the share of the purchase judged
    in the units it was bought in."""
    eur, sap = _eur(db), _share(db)
    usd = instruments.create_cash(db, symbol="USD", name="US Dollar")
    depot = _depot(db)
    _keep(db, sap, depot)
    _buy(db, depot, sap, usd, quantity="10", cost="1100")
    _apply(client, _split(sap))
    _sell(db, depot, sap, eur, quantity="10", proceeds="800")
    rates = FakeReferenceRateSource([ReferenceRate("USD", date(2031, 2, 10), Decimal("1.10"))])

    disposal = _the_disposal(db, rates)

    (consumption,) = disposal.consumptions
    assert consumption.basis_eur == Decimal("500")
    assert disposal.gain_eur == Decimal("300")


# --- Preview and reversal ----------------------------------------------------


def test_a_preview_shows_the_lots_before_and_after_and_writes_nothing(db, client):
    eur, sap = _eur(db), _share(db)
    depot = _held(db, sap, eur=eur)

    response = client.post("/api/corporate-actions/preview", json=_split(sap))

    assert response.status_code == 200
    preview = response.json()
    assert preview["id"] is None
    assert [
        (lot["before"]["quantity"], lot["after"][0]["quantity"]) for lot in preview["lots"]
    ] == [
        ("10", "20"),
        ("30", "60"),
    ]
    assert client.get("/api/corporate-actions").json() == []
    assert _position(client, sap, depot)["quantity"] == "40"


def test_removing_a_corporate_action_reverses_it(db, client):
    """Reversal is the removal of the event: the next read derives the lots
    without it, and the position stands as it stood before."""
    eur, sap = _eur(db), _share(db)
    depot = _held(db, sap, eur=eur)
    before = _position(client, sap, depot)
    action_id = _apply(client, _split(sap))
    assert _position(client, sap, depot) != before

    response = client.delete(f"/api/corporate-actions/{action_id}")

    assert response.status_code == 204
    assert _position(client, sap, depot) == before
    assert client.get("/api/corporate-actions").json() == []
    assert client.delete(f"/api/corporate-actions/{action_id}").status_code == 404


def test_a_corporate_action_marks_the_lot_materialisation_stale(db, client):
    """Corporate Actions are an input class of every materialisation
    (ADR-0014): recording one, and removing one, is drift named as such."""
    eur, sap = _eur(db), _share(db)
    _held(db, sap, eur=eur)
    lots.rebuild(db)
    assert lots.drift(db) == []

    action_id = _apply(client, _split(sap))
    assert [drifted.input_class for drifted in lots.drift(db)] == ["corporate_actions"]

    lots.rebuild(db)
    client.delete(f"/api/corporate-actions/{action_id}")
    assert [drifted.input_class for drifted in lots.drift(db)] == ["corporate_actions"]


def test_a_split_reaches_the_lots_a_transfer_has_in_transit(db, client):
    """A Depotübertrag that left before the split and arrived after it is
    booked in the new units at the destination — the carried lots arrive
    rescaled, with their basis and acquisition date."""
    eur, sap = _eur(db), _share(db)
    source = _depot(db)
    destination = _depot(db, platform_name="Trade Republic")
    _keep(db, sap, source)
    _buy(db, source, sap, eur, quantity="10", cost="1000")
    outgoing = transactions.create_transaction(
        db,
        type="transfer_out",
        occurred_at=datetime(2031, 4, 30, 12, 0, tzinfo=UTC),
        note=None,
        legs=[Leg(account_id=source, instrument_id=sap, role="out", quantity=Decimal("10"))],
    )
    incoming = transactions.create_transaction(
        db,
        type="transfer_in",
        occurred_at=datetime(2031, 5, 5, 12, 0, tzinfo=UTC),
        note=None,
        legs=[Leg(account_id=destination, instrument_id=sap, role="in", quantity=Decimal("20"))],
    )
    with db.connect() as connection:
        out_leg, in_leg = (
            connection.execute(
                text("SELECT id FROM transaction_leg WHERE transaction_id = :id"), {"id": moved}
            ).scalar_one()
            for moved in (outgoing, incoming)
        )
    decided = transfer_matches.decide(db, out_leg_id=out_leg, in_leg_id=in_leg, verdict="confirmed")
    assert isinstance(decided, int)

    _apply(client, _split(sap))

    position = _position(client, sap, destination)
    assert position["quantity"] == "20"
    assert position["basis_eur"] == "1000"
    assert position["basis_gap"] is None


# --- Capital return ----------------------------------------------------------


def _capital_return(instrument, *, amount, effective_at=EFFECTIVE):
    return {
        "kind": "capital_return",
        "instrument_id": instrument,
        "effective_at": effective_at,
        "amount_per_unit_eur": amount,
    }


def test_a_capital_return_reduces_the_basis_of_open_lots_instead_of_booking_income(db, client):
    """5 EUR per unit over lots of 10 and 30 takes 50 and 150 off their
    bases. The quantity stands, and the ledger gained no income — there is
    no transaction for an income engine to find."""
    eur, sap = _eur(db), _share(db)
    depot = _held(db, sap, eur=eur)
    before = client.get("/api/transactions").json()

    _apply(client, _capital_return(sap, amount="5"))

    position = _position(client, sap, depot)
    assert position["quantity"] == "40"
    assert position["basis_eur"] == "6800.00"
    assert client.get("/api/transactions").json() == before


def test_a_capital_return_is_reported_as_a_basis_reduction_per_lot(db, client):
    eur, sap = _eur(db), _share(db)
    _held(db, sap, eur=eur)

    _apply(client, _capital_return(sap, amount="5"))

    (action,) = client.get("/api/corporate-actions").json()
    assert action["kind"] == "capital_return"
    assert action["amount_per_unit_eur"] == "5"
    assert action["needs_review"] is False
    assert [
        (lot["before"]["basis_eur"], lot["after"][0]["basis_eur"], lot["excess_eur"])
        for lot in action["lots"]
    ] == [("1000", "950.00", "0"), ("6000", "5850.00", "0")]


def test_a_later_sale_states_its_gain_against_the_reduced_basis(db, client):
    eur, sap = _eur(db), _share(db)
    depot = _held(db, sap, eur=eur)
    _apply(client, _capital_return(sap, amount="5"))
    _sell(db, depot, sap, eur, quantity="10", proceeds="1500")

    disposal = _the_disposal(db)

    assert disposal.consumptions[0].basis_eur == Decimal("950")
    assert disposal.gain_eur == Decimal("550")


def test_a_capital_return_beyond_a_lots_basis_stops_at_zero_and_is_flagged(db, client):
    """150 EUR per unit exceeds the first lot's 100 EUR per unit: its basis
    stops at zero, the 500 EUR excess is named, and the event waits for
    manual review — what the excess is taxed as is not asserted."""
    eur, sap = _eur(db), _share(db)
    depot = _held(db, sap, eur=eur)

    _apply(client, _capital_return(sap, amount="150"))

    (action,) = client.get("/api/corporate-actions").json()
    assert [(lot["after"][0]["basis_eur"], lot["excess_eur"]) for lot in action["lots"]] == [
        ("0", "500.00"),
        ("1500.00", "0"),
    ]
    assert action["needs_review"] is True
    assert _position(client, sap, depot)["basis_eur"] == "1500.00"


# --- Spin-off and merger -----------------------------------------------------


def _spin_off(instrument, target, *, new="1", old="4", basis_share="0.2"):
    return {
        "kind": "spin_off",
        "instrument_id": instrument,
        "target_instrument_id": target,
        "effective_at": EFFECTIVE,
        "units_new": new,
        "units_old": old,
        "basis_share": basis_share,
    }


def _merger(instrument, target, *, new="1", old="2"):
    return {
        "kind": "merger",
        "instrument_id": instrument,
        "target_instrument_id": target,
        "effective_at": EFFECTIVE,
        "units_new": new,
        "units_old": old,
    }


def test_a_spin_off_splits_the_basis_by_the_ratio_the_admin_supplies(db, client):
    """One new share for every four held, carrying 20 % of the basis: the
    parent keeps its quantity and 80 % of each lot's basis, the spun-off
    Instrument holds a quarter of the units at the remaining 20 %."""
    eur, parent, child = _eur(db), _share(db), _share(db, "SHL", "DE000SHL1006")
    depot = _held(db, parent, eur=eur)

    _apply(client, _spin_off(parent, child))

    kept, spun = _position(client, parent, depot), _position(client, child, depot)
    assert (kept["quantity"], kept["basis_eur"]) == ("40", "5600.00")
    assert (Decimal(spun["quantity"]), spun["basis_eur"]) == (Decimal("10"), "1400.00")
    assert spun["basis_gap"] is None


def test_spun_off_lots_keep_the_acquisition_dates_of_the_lots_they_left(db, client):
    eur, parent, child = _eur(db), _share(db), _share(db, "SHL", "DE000SHL1006")
    depot = _held(db, parent, eur=eur)
    _apply(client, _spin_off(parent, child))
    _sell(db, depot, child, eur, quantity="2.5", proceeds="300")

    disposal = _the_disposal(db)

    (consumption,) = disposal.consumptions
    assert consumption.acquired_at == BOUGHT
    assert consumption.basis_eur == Decimal("200")
    assert disposal.gain_eur == Decimal("100")


def test_a_merger_moves_every_lot_into_the_target_at_the_exchange_ratio(db, client):
    """One target share for every two held: the old position is gone, the
    target holds half the units with the whole basis."""
    eur, old, new = _eur(db), _share(db), _share(db, "NEW", "DE000NEW0001")
    depot = _held(db, old, eur=eur)

    _apply(client, _merger(old, new))

    assert _position(client, old, depot) is None
    position = _position(client, new, depot)
    assert (position["quantity"], position["basis_eur"]) == ("20", "7000")
    (action,) = client.get("/api/corporate-actions").json()
    assert [
        (lot["acquired_at"], lot["before"]["instrument_id"], lot["after"]) for lot in action["lots"]
    ] == [
        (
            "2031-02-10T12:00:00Z",
            old,
            [{"instrument_id": new, "quantity": "5", "basis_eur": "1000"}],
        ),
        (
            "2031-03-10T12:00:00Z",
            old,
            [{"instrument_id": new, "quantity": "15", "basis_eur": "6000"}],
        ),
    ]


def test_a_basis_awaiting_valuation_follows_a_capital_return_and_a_spin_off(db, client):
    """A share bought for 1100 USD at 1.10 cost 1000 EUR, a figure only a
    report can state. A 10 EUR capital return per unit and a spin-off moving
    a quarter of the basis since leave (1000 - 100) x 75 % = 675 with the
    parent and 225 with the spun-off lot."""
    eur, parent, child = _eur(db), _share(db), _share(db, "SHL", "DE000SHL1006")
    usd = instruments.create_cash(db, symbol="USD", name="US Dollar")
    depot = _depot(db)
    _keep(db, parent, depot)
    _buy(db, depot, parent, usd, quantity="10", cost="1100")
    _apply(client, _capital_return(parent, amount="10", effective_at="2031-04-01T00:00:00Z"))
    _apply(client, _spin_off(parent, child, new="1", old="1", basis_share="0.25"))
    _sell(db, depot, parent, eur, quantity="10", proceeds="1000")
    _sell(db, depot, child, eur, quantity="10", proceeds="400")
    rates = FakeReferenceRateSource([ReferenceRate("USD", date(2031, 2, 10), Decimal("1.10"))])

    sold = security_disposals.disposals_through(db, rates, through_year=2031)

    basis = {disposal.instrument_id: disposal.consumptions[0].basis_eur for disposal in sold}
    assert basis == {parent: Decimal("675"), child: Decimal("225")}


@pytest.mark.parametrize("stated", [_spin_off, _merger])
def test_a_spin_off_or_merger_is_flagged_for_manual_review(db, client, stated):
    """The treatment is fact-specific, so the event waits flagged — in its
    preview, in the list, and as a pre-flight blocker on every report year
    it is in effect for — until the Admin marks it reviewed. Reviewing
    asserts nothing: no figure moves."""
    eur, parent, child = _eur(db), _share(db), _share(db, "SHL", "DE000SHL1006")
    depot = _held(db, parent, eur=eur)
    action = stated(parent, child)

    assert client.post("/api/corporate-actions/preview", json=action).json()["needs_review"]
    action_id = _apply(client, action)
    (recorded,) = client.get("/api/corporate-actions").json()
    assert recorded["needs_review"] is True
    assert "unreviewed_corporate_actions" not in _blocker_kinds(db, year=2030)
    assert "unreviewed_corporate_actions" in _blocker_kinds(db, year=2031)
    holding = _position(client, child, depot)
    lots.rebuild(db)

    response = client.put(f"/api/corporate-actions/{action_id}/review")

    assert response.status_code == 204
    (recorded,) = client.get("/api/corporate-actions").json()
    assert recorded["needs_review"] is False
    assert recorded["reviewed_at"] is not None
    assert "unreviewed_corporate_actions" not in _blocker_kinds(db, year=2031)
    assert _position(client, child, depot) == holding
    assert lots.drift(db) == []


def _blocker_kinds(db, *, year):
    return {blocker.kind for blocker in blockers(db, year=year)}


# --- What may be recorded ----------------------------------------------------


def test_cash_has_no_corporate_action(db, client):
    eur = _eur(db)
    usd = instruments.create_cash(db, symbol="USD", name="US Dollar")

    for cash in (eur, usd):
        response = client.post("/api/corporate-actions", json=_split(cash))
        assert response.status_code == 422
        assert "security or a crypto asset" in response.json()["detail"]


def test_an_unknown_instrument_is_refused(db, client):
    sap = _share(db)

    assert client.post("/api/corporate-actions", json=_split(sap + 1000)).status_code == 422
    merger = client.post("/api/corporate-actions/preview", json=_merger(sap, sap + 1000))
    assert merger.status_code == 422


@pytest.mark.parametrize(
    "malformed",
    [
        # A split with no ratio, and one with half of one.
        {"units_new": None, "units_old": None},
        {"units_old": None},
        # A split naming a target, a basis share or an amount.
        {"target_instrument_id": 1},
        {"basis_share": "0.5"},
        {"amount_per_unit_eur": "5"},
        # A ratio that is not positive, and one that crossed as a float.
        {"units_new": "0"},
        {"units_new": 2},
    ],
)
def test_an_event_carries_exactly_its_kinds_fields(db, client, malformed):
    sap = _share(db)

    response = client.post("/api/corporate-actions", json={**_split(sap), **malformed})

    assert response.status_code == 422
    assert client.get("/api/corporate-actions").json() == []


def test_a_spin_off_must_move_a_share_strictly_between_nothing_and_everything(db, client):
    parent, child = _share(db), _share(db, "SHL", "DE000SHL1006")

    for share in ("0", "1", "1.5"):
        response = client.post(
            "/api/corporate-actions", json=_spin_off(parent, child, basis_share=share)
        )
        assert response.status_code == 422
    assert client.post("/api/corporate-actions", json=_merger(parent, parent)).status_code == 422


# --- The Vorabpauschale under a split ----------------------------------------


@pytest.fixture
def store(db):
    """The migrated database with this file's statutory mutation years wiped —
    statutory rows outlive the shared `db` fixture."""
    with db.begin() as connection:
        connection.execute(text("DELETE FROM statutory_value WHERE year >= 2030"))
    return db


def test_a_split_changes_no_vorabpauschale_already_accrued(store, client):
    """§18 InvStG: ten units held across 2031 accrue 10 x 1.40 for that year
    — stated in that year's units. A two-for-one split in 2032 leaves the
    2031 accrual at 14.00 and the deduction a later sale of all twenty units
    takes (§19 Abs. 1 Satz 3 InvStG) at the same 14.00."""
    eur = _eur(store)
    fund = instruments.create_security(
        store,
        symbol="IWDA",
        name="IWDA",
        type="etf",
        isin="IE00B4L5Y983",
        fund_category="aktienfonds",
        fund_category_source="provider",
        distribution_policy="accumulating",
    )
    depot = _depot(store)
    _keep(store, fund, depot)
    _buy(store, depot, fund, eur, quantity="10", cost="1000", occurred_at=BOUGHT.replace(month=1))
    for key, value in (
        ("advance_lump_sum_base_rate", "0.02"),
        ("advance_lump_sum_factor", "0.7"),
        ("partial_exemption_aktienfonds", "0.30"),
    ):
        for year in (2031, 2032):
            statutory.upsert_value(
                store, year=year, key=key, value=Decimal(value), source="a test value"
            )
    fund_redemption_values.upsert_value(
        store,
        instrument_id=fund,
        year=2031,
        start_of_year_eur=Decimal("100"),
        end_of_year_eur=Decimal("110"),
        distributions_eur=Decimal("0"),
        source="the fund's annual report",
    )
    _apply(client, _split(fund, effective_at="2032-03-01T00:00:00Z"))
    _sell(
        store,
        depot,
        fund,
        eur,
        quantity="20",
        proceeds="1300",
        occurred_at=datetime(2032, 6, 3, 12, 0, tzinfo=UTC),
    )

    (accrual,) = advance_lump_sums.accruals_through(store, through_year=2032)
    (disposal,) = security_disposals.disposals_through(
        store, FakeReferenceRateSource(), through_year=2032
    )

    assert accrual.derived_year == 2031
    assert accrual.quantity == Decimal("10")
    assert accrual.amount_eur == Decimal("14.00")
    assert disposal.advance_lump_sums_eur == Decimal("14.00")
    assert disposal.gain_eur == Decimal("286.00")


# --- An identifier change ----------------------------------------------------


def test_an_identifier_change_orphans_no_lot(db, client):
    """A redomiciliation renames the paper: the Instrument's identifier
    history absorbs the new ISIN, the position and its lots stand untouched,
    and the superseded ISIN still resolves to the same Instrument."""
    eur, sap = _eur(db), _share(db)
    depot = _held(db, sap, eur=eur)
    before = _position(client, sap, depot)

    response = client.put(f"/api/securities/{sap}/isin", json={"isin": "NL0000SAP001"})

    assert response.status_code == 204
    after = _position(client, sap, depot)
    assert after == {**before, "isin": "NL0000SAP001"}
    assert after["basis_eur"] == "7000"
    assert [row.id for row in instruments.find_by_identifier(db, "DE0007164600")] == [sap]
    assert [row.id for row in instruments.find_by_identifier(db, "NL0000SAP001")] == [sap]


def test_an_identifier_change_cannot_take_another_instruments_isin(db, client):
    sap, other = _share(db), _share(db, "SHL", "DE000SHL1006")

    response = client.put(f"/api/securities/{sap}/isin", json={"isin": "DE000SHL1006"})

    assert response.status_code == 409
    assert instruments.get(db, sap).isin == "DE0007164600"
    assert instruments.get(db, other).isin == "DE000SHL1006"
    assert client.put("/api/securities/999999/isin", json={"isin": "X"}).status_code == 404

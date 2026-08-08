"""Opening Balance, both variants (ticket 15): a position that predates
available history, recorded honestly. It behaves like an inbound transfer but
declares that its cost basis is reconstructed, not observed — and the two
cases are distinct, because an exemption depends on the acquisition date
while the basis may be a genuine estimate.

The seams are the schema over real Postgres, the service's structural rules,
the one-place tax-consequence document, the HTTP endpoints and the seed.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from open_leprechaun.repositories import instruments, platforms, transactions
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.services.transactions import (
    RECONSTRUCTED,
    TRANSACTION_TYPES,
    declaration_defect,
    overview,
    structural_defect,
)

# Long before the ledger's own history begins.
ACQUIRED = datetime(2019, 6, 1, 9, 0, tzinfo=UTC)


def _in(quantity="0.5"):
    return Leg(account_id=1, instrument_id=1, role="in", quantity=Decimal(quantity))


def _leg(role):
    return Leg(account_id=1, instrument_id=1, role=role, quantity=Decimal("1"))


# --- The vocabulary and its structural rules ---------------------------------


def test_an_opening_balance_behaves_like_an_inbound_transfer():
    """One in-leg, nothing leaving: the position already existed when history
    begins, so nothing left anywhere and no fee was paid inside the ledger."""
    assert "opening_balance" in TRANSACTION_TYPES

    assert structural_defect("opening_balance", [_in()]) is None
    assert structural_defect("opening_balance", [_leg("out")]) is not None
    assert structural_defect("opening_balance", [_in(), _leg("out")]) is not None
    assert structural_defect("opening_balance", [_in(), _leg("fee")]) is not None


def test_an_opening_balance_records_exactly_one_position():
    """Two positions are two Opening Balances — the declaration of what is
    reconstructed and the estimated basis belong to one position each."""
    defect = structural_defect("opening_balance", [_in(), _in()])

    assert defect is not None
    assert "one position" in defect


def test_a_defect_sentence_carries_the_right_article():
    """ "An opening balance", "an airdrop" — the sentences are shown to the
    Admin, so they read as prose."""
    assert structural_defect("opening_balance", [_leg("out")]).startswith("An opening balance")
    assert structural_defect("airdrop", [_leg("out")]).startswith("An airdrop")


# --- The schema is the arbiter -----------------------------------------------


def _insert_header(connection, *, type, reconstructed, estimated_basis_eur):
    connection.execute(
        text(
            "INSERT INTO transaction (type, occurred_at, reconstructed, estimated_basis_eur)"
            " VALUES (:type, now(), :reconstructed, :estimated_basis_eur)"
        ),
        {
            "type": type,
            "reconstructed": reconstructed,
            "estimated_basis_eur": estimated_basis_eur,
        },
    )


def test_the_schema_holds_an_opening_balance_to_its_declarations(db):
    """An Opening Balance always names what is reconstructed and always
    carries an estimated basis — the declaration is the point, so a row
    without either cannot exist."""
    with db.begin() as connection:
        _insert_header(
            connection, type="opening_balance", reconstructed="basis", estimated_basis_eur="0"
        )
        _insert_header(
            connection,
            type="opening_balance",
            reconstructed="basis_and_date",
            estimated_basis_eur="1234.56",
        )

    for reconstructed, estimated_basis_eur in [
        (None, "100"),
        ("basis", None),
        (None, None),
        ("everything", "100"),
        ("basis", "-1"),
    ]:
        with pytest.raises(IntegrityError), db.begin() as connection:
            _insert_header(
                connection,
                type="opening_balance",
                reconstructed=reconstructed,
                estimated_basis_eur=estimated_basis_eur,
            )


def test_no_other_type_declares_a_reconstruction_or_an_estimated_basis(db):
    """On any other Transaction the assumption would look identical to a real
    movement in every report — the schema refuses the mark where it lies."""
    for reconstructed, estimated_basis_eur in [("basis", "100"), ("basis", None), (None, "100")]:
        with pytest.raises(IntegrityError), db.begin() as connection:
            _insert_header(
                connection,
                type="transfer_in",
                reconstructed=reconstructed,
                estimated_basis_eur=estimated_basis_eur,
            )


# --- Recording and reading back ----------------------------------------------


def _arrange(db):
    platform_id = platforms.create_platform(db, name="BitBox02", kind="cold_storage")
    account = platforms.create_account(db, platform_id, name="Savings")
    btc = instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    return account, btc


def test_an_opening_balance_round_trips_with_its_declarations(db):
    """The declaration is part of the record: what was reconstructed and the
    estimated basis come back with the Transaction, exact fixed-point."""
    account, btc = _arrange(db)

    transactions.create_transaction(
        db,
        type="opening_balance",
        occurred_at=ACQUIRED,
        note="Held since long before the export window",
        legs=[Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("0.75"))],
        reconstructed="basis",
        estimated_basis_eur=Decimal("6543.21"),
    )

    (recorded,) = overview(db)
    assert recorded.type == "opening_balance"
    assert recorded.occurred_at == ACQUIRED
    assert recorded.reconstructed == "basis"
    assert recorded.estimated_basis_eur == Decimal("6543.21")


def test_any_other_transaction_declares_nothing(db):
    account, btc = _arrange(db)

    transactions.create_transaction(
        db,
        type="transfer_in",
        occurred_at=ACQUIRED,
        note=None,
        legs=[Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("1"))],
    )

    (recorded,) = overview(db)
    assert recorded.reconstructed is None
    assert recorded.estimated_basis_eur is None


def test_revising_an_opening_balance_replaces_its_declarations_wholesale(db):
    """The Admin who learns the real acquisition date revises the variant:
    conservative dating is for a date genuinely unknown, and holding onto it
    once the date is known would manufacture tax on an exempt holding."""
    account, btc = _arrange(db)
    transaction_id = transactions.create_transaction(
        db,
        type="opening_balance",
        occurred_at=datetime(2024, 1, 1, tzinfo=UTC),
        note=None,
        legs=[Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("0.75"))],
        reconstructed="basis_and_date",
        estimated_basis_eur=Decimal("30000"),
    )

    replaced = transactions.replace_transaction(
        db,
        transaction_id,
        type="opening_balance",
        occurred_at=ACQUIRED,
        note="Found the old purchase confirmation email",
        legs=[Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("0.75"))],
        reconstructed="basis",
        estimated_basis_eur=Decimal("4000"),
    )

    assert replaced is None
    (recorded,) = overview(db)
    assert recorded.occurred_at == ACQUIRED
    assert recorded.reconstructed == "basis"
    assert recorded.estimated_basis_eur == Decimal("4000")


# --- The declaration is judged before anything is written --------------------


def test_an_opening_balance_names_what_is_reconstructed_and_its_estimate():
    complete = declaration_defect(
        "opening_balance", reconstructed="basis", estimated_basis_eur=Decimal("100")
    )
    unnamed = declaration_defect(
        "opening_balance", reconstructed=None, estimated_basis_eur=Decimal("100")
    )
    unestimated = declaration_defect(
        "opening_balance", reconstructed="basis_and_date", estimated_basis_eur=None
    )

    assert complete is None
    assert "reconstructed" in unnamed
    assert "estimated" in unestimated


def test_no_other_type_may_wear_the_declarations():
    """Worn anywhere else the mark would lie — a real movement posing as an
    assumption, or the reverse."""
    for reconstructed, estimated_basis_eur in [
        ("basis", Decimal("1")),
        ("basis", None),
        (None, Decimal("1")),
    ]:
        assert (
            declaration_defect(
                "transfer_in",
                reconstructed=reconstructed,
                estimated_basis_eur=estimated_basis_eur,
            )
            is not None
        )
    assert declaration_defect("trade", reconstructed=None, estimated_basis_eur=None) is None


# --- The HTTP seam -----------------------------------------------------------


def _api_opening_balance(account, btc, **overrides):
    return {
        "type": "opening_balance",
        "occurred_at": "2019-06-01T09:00:00+00:00",
        "note": None,
        "reconstructed": "basis",
        "estimated_basis_eur": "6543.21",
        "legs": [{"account_id": account, "instrument_id": btc, "role": "in", "quantity": "0.75"}],
        **overrides,
    }


def test_the_api_records_both_variants_and_answers_the_declarations_as_strings(client, db):
    """Fixed-point including in JSON: the estimated basis crosses as a plain
    decimal string in both directions, like every quantity."""
    account, btc = _arrange(db)

    known_date = client.post("/api/transactions", json=_api_opening_balance(account, btc))
    both_reconstructed = client.post(
        "/api/transactions",
        json=_api_opening_balance(
            account,
            btc,
            occurred_at="2026-01-01T00:00:00+00:00",
            reconstructed="basis_and_date",
            estimated_basis_eur="0",
        ),
    )

    assert known_date.status_code == 201
    assert both_reconstructed.status_code == 201
    by_variant = {entry["reconstructed"]: entry for entry in client.get("/api/transactions").json()}
    assert by_variant["basis"]["estimated_basis_eur"] == "6543.21"
    assert by_variant["basis"]["occurred_at"] == "2019-06-01T09:00:00Z"
    assert by_variant["basis_and_date"]["estimated_basis_eur"] == "0"


def test_the_api_refuses_an_undeclared_opening_balance_naming_what_is_missing(client, db):
    account, btc = _arrange(db)

    unnamed = client.post(
        "/api/transactions", json=_api_opening_balance(account, btc, reconstructed=None)
    )
    unestimated = client.post(
        "/api/transactions", json=_api_opening_balance(account, btc, estimated_basis_eur=None)
    )

    assert unnamed.status_code == 422
    assert "reconstructed" in unnamed.json()["detail"]
    assert unestimated.status_code == 422
    assert "estimated" in unestimated.json()["detail"]


def test_the_api_refuses_the_declarations_on_any_other_type(client, db):
    account, btc = _arrange(db)

    response = client.post(
        "/api/transactions", json=_api_opening_balance(account, btc, type="transfer_in")
    )

    assert response.status_code == 422


def test_the_api_refuses_an_estimate_that_drifted_through_a_float_or_below_zero(client, db):
    account, btc = _arrange(db)

    for drifted in (6543.21, "-1"):
        response = client.post(
            "/api/transactions",
            json=_api_opening_balance(account, btc, estimated_basis_eur=drifted),
        )

        assert response.status_code == 422


def test_the_api_revises_a_variant_end_to_end(client, db):
    """The Admin who learns the real date moves from the conservative variant
    to the date-known one, date and estimate revised together."""
    account, btc = _arrange(db)
    conservative = _api_opening_balance(
        account,
        btc,
        occurred_at="2026-01-01T00:00:00+00:00",
        reconstructed="basis_and_date",
        estimated_basis_eur="30000",
    )
    transaction_id = client.post("/api/transactions", json=conservative).json()["id"]

    response = client.put(
        f"/api/transactions/{transaction_id}", json=_api_opening_balance(account, btc)
    )

    assert response.status_code == 204
    (recorded,) = client.get("/api/transactions").json()
    assert recorded["reconstructed"] == "basis"
    assert recorded["occurred_at"] == "2019-06-01T09:00:00Z"
    assert recorded["estimated_basis_eur"] == "6543.21"


def test_the_api_speaks_the_same_variants_as_the_service():
    from typing import get_args

    from open_leprechaun.routers.transactions import Reconstructed

    assert set(get_args(Reconstructed)) == set(RECONSTRUCTED)


# --- The seed ----------------------------------------------------------------


def test_the_seed_demonstrates_an_opening_balance(db):
    """The development ledger carries a position that predates its history —
    the date-known variant, so the screen shows the declaration — and a
    second run changes nothing."""
    from open_leprechaun.seed import seed

    seed(db)
    once = overview(db)
    seed(db)

    assert overview(db) == once
    opening = next(entry for entry in once if entry.type == "opening_balance")
    assert opening.reconstructed == "basis"
    assert opening.estimated_basis_eur is not None
    (leg,) = opening.legs
    assert leg.role == "in"


# --- The one tax-consequence document ----------------------------------------


def test_an_opening_balance_mints_an_estimated_lot_never_an_observed_one():
    """The minted lot's basis is the Admin's declared estimate, so it is
    marked estimated and every disposal consuming it is flagged as resting on
    an estimate — the rule the lot engine (19) and the disposal engine (21)
    read. It must never look like a documented purchase."""
    from open_leprechaun.services import tax_treatment

    consequence = tax_treatment.TAX_CONSEQUENCES["opening_balance"]

    assert consequence.inflow is tax_treatment.Inflow.mints_estimated_lot
    assert consequence.inflow is not tax_treatment.Inflow.mints_lot_at_cost
    assert consequence.outflow is tax_treatment.Outflow.none_expected
    assert consequence.income is None


def test_only_an_estimated_lot_rests_on_an_estimate():
    """The rule the disposal engine (21) reads to flag a disposal as resting
    on an estimate — a predicate, not prose, so the flag cannot be forgotten
    when the engine arrives."""
    from open_leprechaun.services import tax_treatment

    for inflow in tax_treatment.Inflow:
        assert tax_treatment.rests_on_estimate(inflow) is (
            inflow is tax_treatment.Inflow.mints_estimated_lot
        )

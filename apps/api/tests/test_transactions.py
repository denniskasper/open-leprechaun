"""Balanced-leg Transactions: one economic event recorded as a set of legs
that balance — what left, what arrived, what a fee consumed (ADR-0011). A
trade's other side is structural rather than conventional, a fee is its own
leg, and more than two legs are expressible.

The seams are the schema over real Postgres, the repository, the vocabulary
with its one-place tax-consequence document, and the HTTP endpoints.
"""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import get_args

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from open_leprechaun.repositories import instruments, platforms, transactions
from open_leprechaun.repositories.transactions import Leg, Refusal
from open_leprechaun.seed import seed
from open_leprechaun.services import tax_treatment
from open_leprechaun.services.transactions import (
    TRANSACTION_TYPES,
    overview,
    structural_defect,
)

NOON = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)


def _account(db, platform_name="Kraken", kind="exchange", name="Main"):
    platform_id = platforms.create_platform(db, name=platform_name, kind=kind)
    if platform_id is None:
        platform_id = next(
            row.id for row in platforms.list_platforms(db) if row.name == platform_name
        )
    created = platforms.create_account(db, platform_id, name=name)
    if created is platforms.Refusal.name_taken:
        return next(row.id for row in platforms.list_accounts(db) if row.name == name)
    return created


def _eur(db):
    return instruments.create_cash(db, symbol="EUR", name="Euro")


def _btc(db):
    return instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")


def _sol(db):
    return instruments.create_native_coin(db, symbol="SOL", name="Solana", chain="solana")


def _buy(account, eur, btc, *, fee_against=None):
    """Euro out, Bitcoin in — the canonical trade both sides of which must
    exist. Optionally a fee leg charged against the leg at `fee_against`."""
    legs = [
        Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal("100.00")),
        Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("0.005")),
    ]
    if fee_against is not None:
        legs.append(
            Leg(
                account_id=account,
                instrument_id=eur,
                role="fee",
                quantity=Decimal("0.40"),
                charged_against=fee_against,
            )
        )
    return legs


# --- The schema is the arbiter ---------------------------------------------


def test_the_schema_refuses_a_type_outside_the_vocabulary(db):
    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text("INSERT INTO transaction (type, occurred_at) VALUES ('barter', now())")
        )


def test_the_schema_refuses_a_nonpositive_quantity(db):
    """A leg's direction is its role, never a sign convention, so a zero or
    negative quantity is meaningless and the schema refuses it."""
    account, eur = _account(db), _eur(db)
    for quantity in ("0", "-1"):
        with pytest.raises(IntegrityError), db.begin() as connection:
            transaction_id = connection.execute(
                text(
                    "INSERT INTO transaction (type, occurred_at) VALUES ('fee', now()) RETURNING id"
                )
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO transaction_leg"
                    " (transaction_id, account_id, instrument_id, role, quantity)"
                    " VALUES (:transaction_id, :account, :instrument, 'fee', :quantity)"
                ),
                {
                    "transaction_id": transaction_id,
                    "account": account,
                    "instrument": eur,
                    "quantity": quantity,
                },
            )


def test_no_leg_floats_free_of_transaction_account_or_instrument(db):
    """Every leg belongs to a Transaction, sits in an Account and moves an
    Instrument; the schema refuses a row missing any of the three."""
    account, eur = _account(db), _eur(db)
    with db.begin() as connection:
        transaction_id = connection.execute(
            text("INSERT INTO transaction (type, occurred_at) VALUES ('fee', now()) RETURNING id")
        ).scalar_one()
    columns = {"transaction_id": transaction_id, "account": account, "instrument": eur}
    for absent in ("transaction_id", "account", "instrument"):
        with pytest.raises(IntegrityError), db.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO transaction_leg"
                    " (transaction_id, account_id, instrument_id, role, quantity)"
                    " VALUES (:transaction_id, :account, :instrument, 'fee', 1)"
                ),
                {**columns, absent: None},
            )


def test_removing_a_transaction_takes_its_legs_along(db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    transaction_id = transactions.create_transaction(
        db, type="trade", occurred_at=NOON, note=None, legs=_buy(account, eur, btc)
    )

    assert transactions.delete_transaction(db, transaction_id) is True
    with db.connect() as connection:
        remaining = connection.execute(text("SELECT count(*) FROM transaction_leg")).scalar_one()
    assert remaining == 0


def test_an_account_or_instrument_with_ledger_entries_refuses_to_go(db):
    """The ledger is the only truth, so nothing it rests on may vanish from
    under it."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    transactions.create_transaction(
        db, type="trade", occurred_at=NOON, note=None, legs=_buy(account, eur, btc)
    )

    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(text("DELETE FROM account WHERE id = :id"), {"id": account})
    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(text("DELETE FROM instrument WHERE id = :id"), {"id": eur})


def test_a_fee_attaches_only_within_its_own_transaction(db):
    """A fee attaches to the leg it was charged against, and that leg is a
    sibling — the schema itself refuses a reach into another Transaction."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    first = transactions.create_transaction(
        db, type="trade", occurred_at=NOON, note=None, legs=_buy(account, eur, btc)
    )
    second = transactions.create_transaction(
        db, type="trade", occurred_at=NOON, note=None, legs=_buy(account, eur, btc)
    )
    with db.connect() as connection:
        foreign_leg = connection.execute(
            text("SELECT id FROM transaction_leg WHERE transaction_id = :first LIMIT 1"),
            {"first": first},
        ).scalar_one()

    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO transaction_leg (transaction_id, account_id, instrument_id,"
                " role, quantity, charged_against_leg_id)"
                " VALUES (:transaction_id, :account, :instrument, 'fee', 1, :foreign_leg)"
            ),
            {
                "transaction_id": second,
                "account": account,
                "instrument": eur,
                "foreign_leg": foreign_leg,
            },
        )


def test_only_a_fee_leg_attaches_to_another_leg(db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    transaction_id = transactions.create_transaction(
        db, type="trade", occurred_at=NOON, note=None, legs=_buy(account, eur, btc)
    )
    with db.connect() as connection:
        leg = connection.execute(
            text("SELECT id FROM transaction_leg WHERE role = 'in'")
        ).scalar_one()

    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO transaction_leg (transaction_id, account_id, instrument_id,"
                " role, quantity, charged_against_leg_id)"
                " VALUES (:transaction_id, :account, :instrument, 'out', 1, :leg)"
            ),
            {"transaction_id": transaction_id, "account": account, "instrument": eur, "leg": leg},
        )


# --- Recording, revising, removing -----------------------------------------


def test_a_buy_records_both_the_asset_acquired_and_the_cash_spent(db):
    account, eur, btc = _account(db), _eur(db), _btc(db)

    transaction_id = transactions.create_transaction(
        db, type="trade", occurred_at=NOON, note="First buy", legs=_buy(account, eur, btc)
    )

    (recorded,) = overview(db)
    assert recorded.id == transaction_id
    assert recorded.type == "trade"
    assert recorded.occurred_at == NOON
    assert recorded.note == "First buy"
    assert {(leg.role, leg.instrument_id, leg.quantity) for leg in recorded.legs} == {
        ("out", eur, Decimal("100.00")),
        ("in", btc, Decimal("0.005")),
    }


def test_a_fee_in_a_third_asset_is_just_another_leg(db):
    """More than two legs are expressible, so a fee paid in a third asset is
    not a special case — here a SOL fee on a EUR-for-BTC trade, charged
    against the acquisition."""
    account, eur, btc, sol = _account(db), _eur(db), _btc(db), _sol(db)
    legs = [
        Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal("100.00")),
        Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("0.005")),
        Leg(
            account_id=account,
            instrument_id=sol,
            role="fee",
            quantity=Decimal("0.01"),
            charged_against=1,
        ),
    ]

    transactions.create_transaction(db, type="trade", occurred_at=NOON, note=None, legs=legs)

    (recorded,) = overview(db)
    assert len(recorded.legs) == 3
    fee = next(leg for leg in recorded.legs if leg.role == "fee")
    acquisition = next(leg for leg in recorded.legs if leg.role == "in")
    assert fee.instrument_id == sol
    assert fee.charged_against_leg_id == acquisition.id


def test_quantities_survive_as_exact_decimals(db):
    """A satoshi and an eighteen-decimal token unit round-trip untouched —
    fixed-point throughout, never a float."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    legs = [
        Leg(
            account_id=account,
            instrument_id=eur,
            role="out",
            quantity=Decimal("0.000000000000000001"),
        ),
        Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("0.00000001")),
    ]

    transactions.create_transaction(db, type="trade", occurred_at=NOON, note=None, legs=legs)

    (recorded,) = overview(db)
    assert {leg.quantity for leg in recorded.legs} == {
        Decimal("0.000000000000000001"),
        Decimal("0.00000001"),
    }


def test_revising_a_transaction_replaces_its_legs_wholesale(db):
    account, eur, btc, sol = _account(db), _eur(db), _btc(db), _sol(db)
    transaction_id = transactions.create_transaction(
        db, type="trade", occurred_at=NOON, note=None, legs=_buy(account, eur, btc)
    )

    replaced = transactions.replace_transaction(
        db,
        transaction_id,
        type="staking_reward",
        occurred_at=NOON,
        note="Reclassified",
        legs=[Leg(account_id=account, instrument_id=sol, role="in", quantity=Decimal("2"))],
    )

    assert replaced is None
    (recorded,) = overview(db)
    assert recorded.type == "staking_reward"
    assert recorded.note == "Reclassified"
    (leg,) = recorded.legs
    assert (leg.role, leg.instrument_id, leg.quantity) == ("in", sol, Decimal("2"))


def test_revising_a_transaction_that_is_not_there_says_so(db):
    account, sol = _account(db), _sol(db)

    replaced = transactions.replace_transaction(
        db,
        12345,
        type="staking_reward",
        occurred_at=NOON,
        note=None,
        legs=[Leg(account_id=account, instrument_id=sol, role="in", quantity=Decimal("2"))],
    )

    assert replaced is Refusal.no_such_transaction


def test_removing_a_transaction_answers_whether_it_was_there(db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    transaction_id = transactions.create_transaction(
        db, type="trade", occurred_at=NOON, note=None, legs=_buy(account, eur, btc)
    )

    assert transactions.delete_transaction(db, transaction_id) is True
    assert transactions.delete_transaction(db, transaction_id) is False


def test_a_leg_over_a_missing_account_or_instrument_says_which(db):
    """ "No such Account" and "no such Instrument" are different answers, and
    the constraint that failed decides which one is given."""
    account, eur = _account(db), _eur(db)

    missing_account = transactions.create_transaction(
        db,
        type="fee",
        occurred_at=NOON,
        note=None,
        legs=[Leg(account_id=12345, instrument_id=eur, role="fee", quantity=Decimal("1"))],
    )
    missing_instrument = transactions.create_transaction(
        db,
        type="fee",
        occurred_at=NOON,
        note=None,
        legs=[Leg(account_id=account, instrument_id=12345, role="fee", quantity=Decimal("1"))],
    )

    assert missing_account is Refusal.no_such_account
    assert missing_instrument is Refusal.no_such_instrument


# --- Balance is structural --------------------------------------------------


def test_a_trade_missing_either_side_is_refused_with_the_missing_side_named(db):
    account, eur = _account(db), _eur(db)
    only_out = [Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal("1"))]
    only_in = [Leg(account_id=account, instrument_id=eur, role="in", quantity=Decimal("1"))]

    assert "what arrived" in structural_defect("trade", only_out)
    assert "what left" in structural_defect("trade", only_in)


def test_a_transfer_records_only_one_direction(db):
    """A movement that both sends and receives is two Transactions — each
    side is recorded where it happened, and ticket 16 links them."""
    account, btc = _account(db), _btc(db)
    both = [
        Leg(account_id=account, instrument_id=btc, role="out", quantity=Decimal("1")),
        Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("1")),
    ]

    assert structural_defect("transfer_in", both) is not None
    assert structural_defect("transfer_out", both) is not None


def test_an_empty_transaction_is_refused(db):
    assert structural_defect("trade", []) is not None
    assert structural_defect("fee", []) is not None


def test_a_fee_attachment_points_at_a_sibling_that_is_not_a_fee(db):
    account, eur, btc = _account(db), _eur(db), _btc(db)

    def legs(charged_against):
        return [
            Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal("1")),
            Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("1")),
            Leg(
                account_id=account,
                instrument_id=eur,
                role="fee",
                quantity=Decimal("1"),
                charged_against=charged_against,
            ),
        ]

    assert structural_defect("trade", legs(1)) is None
    assert structural_defect("trade", legs(7)) is not None
    assert structural_defect("trade", legs(2)) is not None  # itself
    two_fees = [
        *legs(1),
        Leg(
            account_id=account,
            instrument_id=eur,
            role="fee",
            quantity=Decimal("1"),
            charged_against=2,
        ),
    ]
    assert structural_defect("trade", two_fees) is not None  # a fee, attached to a fee


def test_only_a_fee_carries_an_attachment(db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    legs = [
        Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal("1")),
        Leg(
            account_id=account,
            instrument_id=btc,
            role="in",
            quantity=Decimal("1"),
            charged_against=0,
        ),
    ]

    assert structural_defect("trade", legs) is not None


def test_income_arrives_without_an_outflow(db):
    account, eur = _account(db), _eur(db)
    outflow = [Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal("1"))]

    for income in (
        "staking_reward",
        "lending_interest",
        "mining_reward",
        "airdrop",
        "dividend",
        "distribution",
        "interest",
    ):
        assert structural_defect(income, outflow) is not None


# --- The vocabulary and its one tax-consequence document --------------------


def test_the_vocabulary_names_what_happened_for_crypto_and_securities():
    assert set(TRANSACTION_TYPES) == {
        "trade",
        "transfer_in",
        "transfer_out",
        "spend",
        "staking_reward",
        "lending_interest",
        "mining_reward",
        "airdrop",
        "windfall",
        "opening_balance",
        "dividend",
        "distribution",
        "interest",
        "fee",
    }


def test_every_type_carries_exactly_one_documented_tax_consequence():
    """One place, so a classification cannot drift between the ledger and the
    report."""
    assert set(tax_treatment.TAX_CONSEQUENCES) == set(TRANSACTION_TYPES)


def test_an_unclassified_inflow_is_never_assumed_to_be_a_purchase():
    """A transfer in mints no lot and invents no cost basis; matching (16),
    an Opening Balance (15) or a Stance decision (14) settles what it was."""
    consequence = tax_treatment.TAX_CONSEQUENCES["transfer_in"]

    assert consequence.inflow is tax_treatment.Inflow.no_lot_until_classified
    assert consequence.inflow is not tax_treatment.Inflow.mints_lot_at_cost


def test_an_unmatched_outflow_is_never_quietly_a_disposal():
    consequence = tax_treatment.TAX_CONSEQUENCES["transfer_out"]

    assert consequence.outflow is tax_treatment.Outflow.awaiting_match


def test_the_tax_consequences_are_read_by_the_tax_engines_alone():
    """The lot engine (ticket 19) and the tax engines (tickets 21, 22, 26)
    — the complete list; a future producer emits Section 20 Events through
    section20 rather than reading the table itself (ADR-0013)."""
    package = Path(tax_treatment.__file__).resolve().parents[1]
    readers = [
        str(path.relative_to(package))
        for path in package.rglob("*.py")
        if path.name != "tax_treatment.py"
        and any(
            "tax_treatment" in line and line.lstrip().startswith(("import ", "from "))
            for line in path.read_text().splitlines()
        )
    ]
    assert sorted(readers) == [
        "services/lots.py",
        "services/section20.py",
        "services/section22.py",
        "services/section23.py",
    ]


def test_the_api_speaks_the_same_vocabulary_as_the_service():
    from open_leprechaun.routers.transactions import TransactionType

    assert set(get_args(TransactionType)) == set(TRANSACTION_TYPES)


# --- The HTTP seam ----------------------------------------------------------


def _api_buy(account, eur, btc):
    return {
        "type": "trade",
        "occurred_at": "2026-03-14T12:00:00+00:00",
        "note": "First buy",
        "legs": [
            {"account_id": account, "instrument_id": eur, "role": "out", "quantity": "100.00"},
            {"account_id": account, "instrument_id": btc, "role": "in", "quantity": "0.005"},
            {
                "account_id": account,
                "instrument_id": eur,
                "role": "fee",
                "quantity": "0.40",
                "charged_against": 1,
            },
        ],
    }


def test_the_api_records_a_buy_and_reads_it_back_with_string_quantities(client, db):
    """Monetary and quantity values are fixed-point decimals throughout,
    including in JSON — a quantity arrives as a string, never a float."""
    account, eur, btc = _account(db), _eur(db), _btc(db)

    recorded = client.post("/api/transactions", json=_api_buy(account, eur, btc))
    assert recorded.status_code == 201

    (transaction,) = client.get("/api/transactions").json()
    assert transaction["type"] == "trade"
    assert transaction["occurred_at"] == "2026-03-14T12:00:00Z"
    assert {leg["quantity"] for leg in transaction["legs"]} == {"100.00", "0.005", "0.40"}
    assert all(isinstance(leg["quantity"], str) for leg in transaction["legs"])
    fee = next(leg for leg in transaction["legs"] if leg["role"] == "fee")
    acquisition = next(leg for leg in transaction["legs"] if leg["role"] == "in")
    assert fee["charged_against_leg_id"] == acquisition["id"]


def test_the_api_refuses_an_unbalanced_trade_naming_the_missing_side(client, db):
    account, eur = _account(db), _eur(db)
    payload = {
        "type": "trade",
        "occurred_at": "2026-03-14T12:00:00+00:00",
        "legs": [
            {"account_id": account, "instrument_id": eur, "role": "out", "quantity": "100.00"}
        ],
    }

    response = client.post("/api/transactions", json=payload)

    assert response.status_code == 422
    assert "what arrived" in response.json()["detail"]


def test_the_api_refuses_a_quantity_that_arrives_as_a_number(client, db):
    """Fixed-point including in JSON: a JSON number has been through — or is
    one parse away from — a binary float, so only a string is accepted and
    the digits are never guessed at."""
    account, eur = _account(db), _eur(db)
    for drifted in (0.1, 5):
        payload = {
            "type": "fee",
            "occurred_at": "2026-03-14T12:00:00+00:00",
            "legs": [
                {"account_id": account, "instrument_id": eur, "role": "fee", "quantity": drifted}
            ],
        }

        assert client.post("/api/transactions", json=payload).status_code == 422


def test_the_api_refuses_a_zero_quantity(client, db):
    account, eur = _account(db), _eur(db)
    payload = {
        "type": "fee",
        "occurred_at": "2026-03-14T12:00:00+00:00",
        "legs": [{"account_id": account, "instrument_id": eur, "role": "fee", "quantity": "0"}],
    }

    assert client.post("/api/transactions", json=payload).status_code == 422


def test_the_api_refuses_a_timestamp_without_a_timezone(client, db):
    """The ledger holds absolute instants; a local time that means a
    different instant in every timezone is refused."""
    account, eur = _account(db), _eur(db)
    payload = {
        "type": "fee",
        "occurred_at": "2026-03-14T12:00:00",
        "legs": [{"account_id": account, "instrument_id": eur, "role": "fee", "quantity": "1"}],
    }

    assert client.post("/api/transactions", json=payload).status_code == 422


def test_the_api_answers_not_found_for_a_missing_account_or_instrument(client, db):
    account, eur = _account(db), _eur(db)
    over_missing_account = {
        "type": "fee",
        "occurred_at": "2026-03-14T12:00:00+00:00",
        "legs": [{"account_id": 12345, "instrument_id": eur, "role": "fee", "quantity": "1"}],
    }
    over_missing_instrument = {
        "type": "fee",
        "occurred_at": "2026-03-14T12:00:00+00:00",
        "legs": [{"account_id": account, "instrument_id": 12345, "role": "fee", "quantity": "1"}],
    }

    assert client.post("/api/transactions", json=over_missing_account).status_code == 404
    assert client.post("/api/transactions", json=over_missing_instrument).status_code == 404


def test_the_api_edits_a_transaction_end_to_end(client, db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    transaction_id = client.post("/api/transactions", json=_api_buy(account, eur, btc)).json()["id"]

    revised = {
        "type": "spend",
        "occurred_at": "2026-04-01T09:30:00+00:00",
        "note": None,
        "legs": [{"account_id": account, "instrument_id": btc, "role": "out", "quantity": "0.001"}],
    }
    response = client.put(f"/api/transactions/{transaction_id}", json=revised)

    assert response.status_code == 204
    (transaction,) = client.get("/api/transactions").json()
    assert transaction["type"] == "spend"
    assert transaction["note"] is None
    (leg,) = transaction["legs"]
    assert (leg["role"], leg["quantity"]) == ("out", "0.001")


def test_the_api_answers_not_found_when_editing_what_is_not_there(client, db):
    account, eur = _account(db), _eur(db)
    payload = {
        "type": "fee",
        "occurred_at": "2026-03-14T12:00:00+00:00",
        "legs": [{"account_id": account, "instrument_id": eur, "role": "fee", "quantity": "1"}],
    }

    assert client.put("/api/transactions/12345", json=payload).status_code == 404


def test_the_api_removes_a_transaction(client, db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    transaction_id = client.post("/api/transactions", json=_api_buy(account, eur, btc)).json()["id"]

    assert client.delete(f"/api/transactions/{transaction_id}").status_code == 204
    assert client.get("/api/transactions").json() == []
    assert client.delete(f"/api/transactions/{transaction_id}").status_code == 404


# --- The seed ---------------------------------------------------------------


def test_the_seed_demonstrates_a_balanced_ledger(db):
    """The development database carries a trade with both sides and a fee in
    a third asset, income, and a transfer — so the ledger screen has every
    shape to show from day one, twice over without duplicating. The ledger
    step rests only on the seed's own instruments, so it holds on a database
    whose EUR is gone as much as on a fresh one."""
    seed(db)
    once = overview(db)
    seed(db)

    assert overview(db) == once
    trades = [t for t in once if t.type == "trade"]
    assert any(
        {"in", "out", "fee"} <= {leg.role for leg in trade.legs}
        and len({leg.instrument_id for leg in trade.legs}) == 3
        for trade in trades
    )
    assert {t.type for t in once} >= {"trade", "transfer_in", "staking_reward"}

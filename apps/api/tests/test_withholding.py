"""Depot, withholding and exemption order (ticket 43): a brokerage Account
registered with the tax semantics its broker actually has — whether tax is
withheld at source, and how much of the saver's allowance the broker's
exemption order lets through untaxed.

The seams are the repository over real Postgres — the rules under test are
the schema's own constraints — and the HTTP endpoints through the app.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from open_leprechaun.repositories import instruments, platforms, transactions
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.seed import seed
from open_leprechaun.services import holdings
from open_leprechaun.services import imports as imports_service
from open_leprechaun.services.imports import (
    CommitRefused,
    ImportLeg,
    ImportRow,
    commit,
    evaluate,
)

NOON = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)


def _broker(db, name="Scalable Capital"):
    platform_id = platforms.create_platform(db, name=name, kind="broker")
    assert platform_id is not None
    return platform_id


def test_the_schema_refuses_a_withholding_outside_the_two_behaviours(db):
    broker = _broker(db)

    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text("UPDATE platform SET withholding = 'sometimes' WHERE id = :id"),
            {"id": broker},
        )


def test_the_schema_refuses_withholding_on_a_platform_that_is_not_a_broker(db):
    """Withholding behaviour is a fact about a broker; a bank or an exchange
    carries none, and the schema itself refuses to record one there."""
    kraken = platforms.create_platform(db, name="Kraken", kind="exchange")

    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text("UPDATE platform SET withholding = 'at_source' WHERE id = :id"),
            {"id": kraken},
        )


def test_the_schema_refuses_an_exemption_order_on_a_platform_that_does_not_withhold(db):
    """A Freistellungsauftrag is lodged with a broker that withholds — on any
    other Platform the amount would be an answer to no question."""
    broker = _broker(db)

    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text("UPDATE platform SET exemption_order_eur = 1000 WHERE id = :id"),
            {"id": broker},
        )


def test_the_schema_refuses_a_negative_exemption_order(db):
    broker = _broker(db)

    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text(
                "UPDATE platform SET withholding = 'at_source', exemption_order_eur = -1"
                " WHERE id = :id"
            ),
            {"id": broker},
        )


def test_the_schema_refuses_a_base_currency_that_is_not_a_currency_code(db):
    broker = _broker(db)
    depot = platforms.create_account(db, broker, name="Depot")

    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text("UPDATE account SET base_currency = 'euro' WHERE id = :id"),
            {"id": depot},
        )


def test_the_schema_refuses_an_override_outside_the_two_behaviours(db):
    broker = _broker(db)
    depot = platforms.create_account(db, broker, name="Depot")

    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text("UPDATE account SET withholding_override = 'sometimes' WHERE id = :id"),
            {"id": depot},
        )


def test_a_broker_records_its_withholding_and_exemption_order(db):
    """The behaviour and the allowance slice the broker already consumes are
    one act to record and one row to read back."""
    broker = _broker(db)

    assert (
        platforms.set_withholding(
            db, broker, behaviour="at_source", exemption_order_eur=Decimal("801")
        )
        is None
    )

    (row,) = platforms.list_platforms(db)
    assert row.withholding == "at_source"
    assert row.exemption_order_eur == Decimal("801")


def test_an_absent_exemption_order_means_none(db):
    broker = _broker(db)

    assert platforms.set_withholding(db, broker, behaviour="at_source") is None

    (row,) = platforms.list_platforms(db)
    assert row.exemption_order_eur is None


def test_only_a_broker_carries_withholding_behaviour(db):
    kraken = platforms.create_platform(db, name="Kraken", kind="exchange")

    refused = platforms.set_withholding(db, kraken, behaviour="at_source")

    assert refused is platforms.Refusal.not_a_broker


def test_setting_withholding_on_a_platform_that_is_not_there_says_so(db):
    assert (
        platforms.set_withholding(db, 12345, behaviour="at_source")
        is platforms.Refusal.no_such_platform
    )


def test_an_account_may_override_its_brokers_behaviour_and_clear_it_again(db):
    """One brand operating through several entities: the Platform states the
    common case, the Account the exception — and clearing the override
    returns the Account to its Platform's word."""
    broker = _broker(db)
    platforms.set_withholding(db, broker, behaviour="at_source")
    depot = platforms.create_account(db, broker, name="Depot")

    assert platforms.set_withholding_override(db, depot, behaviour="none") is None
    (row,) = platforms.list_accounts(db)
    assert row.withholding_override == "none"

    assert platforms.set_withholding_override(db, depot, behaviour=None) is None
    (row,) = platforms.list_accounts(db)
    assert row.withholding_override is None


def test_an_account_outside_a_broker_carries_no_override(db):
    kraken = platforms.create_platform(db, name="Kraken", kind="exchange")
    main = platforms.create_account(db, kraken, name="Main")

    refused = platforms.set_withholding_override(db, main, behaviour="none")

    assert refused is platforms.Refusal.not_under_a_broker


def test_clearing_an_override_that_alone_answers_for_held_positions_is_refused(db):
    """The mirror of "set before it holds": a Depot holding positions on the
    strength of its override alone may not have that override cleared while
    the Platform still states nothing — the positions would stand against an
    unknown."""
    broker = _broker(db)
    depot = platforms.create_account(db, broker, name="Depot")
    platforms.set_withholding_override(db, depot, behaviour="at_source")
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    created = transactions.create_transaction(
        db,
        type="transfer_in",
        occurred_at=NOON,
        note=None,
        legs=[Leg(account_id=depot, instrument_id=eur, role="in", quantity=Decimal("100"))],
    )
    assert isinstance(created, int)

    refused = platforms.set_withholding_override(db, depot, behaviour=None)

    assert refused is platforms.Refusal.would_unset_a_held_depot
    (row,) = platforms.list_accounts(db)
    assert row.withholding_override == "at_source"


def test_clearing_an_override_is_fine_once_the_platform_answers(db):
    broker = _broker(db)
    depot = platforms.create_account(db, broker, name="Depot")
    platforms.set_withholding_override(db, depot, behaviour="none")
    platforms.set_withholding(db, broker, behaviour="at_source")

    assert platforms.set_withholding_override(db, depot, behaviour=None) is None


def test_an_override_on_an_account_that_is_not_there_says_so(db):
    assert (
        platforms.set_withholding_override(db, 12345, behaviour="none")
        is platforms.Refusal.no_such_account
    )


def test_a_depot_records_its_base_currency(db):
    broker = _broker(db)

    depot = platforms.create_account(db, broker, name="Depot", base_currency="EUR")

    (row,) = platforms.list_accounts(db)
    assert row.id == depot
    assert row.base_currency == "EUR"


# --- No position against an unknown ----------------------------------------


def _depot(db, base_currency="EUR"):
    broker = _broker(db)
    depot = platforms.create_account(db, broker, name="Depot", base_currency=base_currency)
    assert isinstance(depot, int)
    return broker, depot


def _eur(db):
    return instruments.create_cash(db, symbol="EUR", name="Euro")


def _cash_in(depot, instrument_id, quantity="1000.00"):
    return [
        Leg(account_id=depot, instrument_id=instrument_id, role="in", quantity=Decimal(quantity))
    ]


def test_a_depot_holds_no_position_before_its_withholding_behaviour_is_set(db):
    """Income at a broker is classified by its withholding behaviour, so a
    position standing before the behaviour is known would be classified
    against an unknown — the ledger refuses the leg instead."""
    _, depot = _depot(db)
    eur = _eur(db)

    refused = transactions.create_transaction(
        db, type="transfer_in", occurred_at=NOON, note=None, legs=_cash_in(depot, eur)
    )

    assert refused is transactions.Refusal.withholding_unset


def test_a_depot_with_its_behaviour_set_holds_positions(db):
    broker, depot = _depot(db)
    platforms.set_withholding(db, broker, behaviour="at_source")
    eur = _eur(db)

    created = transactions.create_transaction(
        db, type="transfer_in", occurred_at=NOON, note=None, legs=_cash_in(depot, eur)
    )

    assert isinstance(created, int)


def test_an_override_answers_where_the_platform_is_silent(db):
    """Effective behaviour is the Account's own word first, the Platform's
    second — an override alone is enough for the Depot to hold."""
    _, depot = _depot(db)
    platforms.set_withholding_override(db, depot, behaviour="none")
    eur = _eur(db)

    created = transactions.create_transaction(
        db, type="transfer_in", occurred_at=NOON, note=None, legs=_cash_in(depot, eur)
    )

    assert isinstance(created, int)


def test_an_account_outside_a_broker_needs_no_withholding_behaviour(db):
    kraken = platforms.create_platform(db, name="Kraken", kind="exchange")
    main = platforms.create_account(db, kraken, name="Main")
    eur = _eur(db)

    created = transactions.create_transaction(
        db, type="transfer_in", occurred_at=NOON, note=None, legs=_cash_in(main, eur)
    )

    assert isinstance(created, int)


def test_a_revision_may_not_move_a_leg_into_an_unset_depot(db):
    kraken = platforms.create_platform(db, name="Kraken", kind="exchange")
    main = platforms.create_account(db, kraken, name="Main")
    _, depot = _depot(db)
    eur = _eur(db)
    created = transactions.create_transaction(
        db, type="transfer_in", occurred_at=NOON, note=None, legs=_cash_in(main, eur)
    )

    refused = transactions.replace_transaction(
        db, created, type="transfer_in", occurred_at=NOON, note=None, legs=_cash_in(depot, eur)
    )

    assert refused is transactions.Refusal.withholding_unset


def test_a_bulk_reassignment_may_not_move_legs_into_an_unset_depot(db):
    kraken = platforms.create_platform(db, name="Kraken", kind="exchange")
    main = platforms.create_account(db, kraken, name="Main")
    _, depot = _depot(db)
    eur = _eur(db)
    created = transactions.create_transaction(
        db, type="transfer_in", occurred_at=NOON, note=None, legs=_cash_in(main, eur)
    )

    refused = transactions.reassign_account(db, [created], depot)

    assert refused is transactions.Refusal.withholding_unset


def test_an_import_into_an_unset_depot_is_refused_in_preview_and_commit(db):
    """The preview names the problem before anything is written, and the
    commit answers the same — no import can put a position where income
    could not be classified."""
    _, depot = _depot(db)
    eur = _eur(db)
    rows = [
        ImportRow(
            external_id="row-1",
            type="transfer_in",
            occurred_at=NOON,
            legs=(ImportLeg(role="in", quantity=Decimal("1000.00"), instrument_id=eur),),
        )
    ]

    preview = evaluate(db, source="broker-csv", account_id=depot, rows=rows)
    committed = commit(db, source="broker-csv", label="statement", account_id=depot, rows=rows)

    assert preview.refusal is not None
    assert preview.refusal.kind is imports_service.Refusal.withholding_unset
    assert isinstance(committed, CommitRefused)
    assert committed.kind is imports_service.Refusal.withholding_unset


def test_the_api_refuses_a_position_in_an_unset_depot_and_names_the_repair(client, db):
    _, depot = _depot(db)
    eur = _eur(db)

    response = client.post(
        "/api/transactions",
        json={
            "type": "transfer_in",
            "occurred_at": "2026-03-14T12:00:00Z",
            "legs": [
                {"account_id": depot, "instrument_id": eur, "role": "in", "quantity": "1000.00"}
            ],
        },
    )

    assert response.status_code == 409
    assert "withholding" in response.json()["detail"].lower()


# --- The HTTP seam ----------------------------------------------------------


def test_the_api_records_withholding_and_reads_it_back_nested(client, db):
    """The Admin declares how the broker treats income and what exemption
    order is lodged there, and reads both back on the Platform — money as a
    fixed-point decimal string, never a JSON number."""
    broker = client.post("/api/platforms", json={"name": "Scalable", "kind": "broker"}).json()["id"]
    depot = client.post(
        f"/api/platforms/{broker}/accounts", json={"name": "Depot", "base_currency": "EUR"}
    )
    assert depot.status_code == 201

    recorded = client.put(
        f"/api/platforms/{broker}/withholding",
        json={"behaviour": "at_source", "exemption_order_eur": "801"},
    )
    assert recorded.status_code == 204

    (platform,) = client.get("/api/platforms").json()
    assert platform["withholding"] == "at_source"
    assert platform["exemption_order_eur"] == "801"
    (account,) = platform["accounts"]
    assert account["base_currency"] == "EUR"
    assert account["withholding_override"] is None


def test_the_api_refuses_an_exemption_order_where_nothing_is_withheld(client, db):
    broker = client.post("/api/platforms", json={"name": "Scalable", "kind": "broker"}).json()["id"]

    response = client.put(
        f"/api/platforms/{broker}/withholding",
        json={"behaviour": "none", "exemption_order_eur": "801"},
    )

    assert response.status_code == 422


def test_the_api_refuses_an_exemption_order_as_a_json_number(client, db):
    broker = client.post("/api/platforms", json={"name": "Scalable", "kind": "broker"}).json()["id"]

    response = client.put(
        f"/api/platforms/{broker}/withholding",
        json={"behaviour": "at_source", "exemption_order_eur": 801},
    )

    assert response.status_code == 422


def test_the_api_answers_conflict_for_withholding_outside_a_broker(client, db):
    kraken = client.post("/api/platforms", json={"name": "Kraken", "kind": "exchange"}).json()["id"]

    response = client.put(f"/api/platforms/{kraken}/withholding", json={"behaviour": "at_source"})

    assert response.status_code == 409


def test_the_api_answers_not_found_for_withholding_on_no_platform(client, db):
    response = client.put("/api/platforms/12345/withholding", json={"behaviour": "at_source"})

    assert response.status_code == 404


def test_the_api_records_and_clears_an_account_override(client, db):
    broker = client.post("/api/platforms", json={"name": "Scalable", "kind": "broker"}).json()["id"]
    depot = client.post(f"/api/platforms/{broker}/accounts", json={"name": "Depot"}).json()["id"]

    recorded = client.put(f"/api/accounts/{depot}/withholding-override", json={"behaviour": "none"})
    assert recorded.status_code == 204
    (platform,) = client.get("/api/platforms").json()
    assert platform["accounts"][0]["withholding_override"] == "none"

    cleared = client.put(f"/api/accounts/{depot}/withholding-override", json={"behaviour": None})
    assert cleared.status_code == 204
    (platform,) = client.get("/api/platforms").json()
    assert platform["accounts"][0]["withholding_override"] is None


def test_the_api_answers_conflict_for_clearing_an_override_a_held_depot_rests_on(client, db):
    _, depot = _depot(db)
    platforms.set_withholding_override(db, depot, behaviour="at_source")
    eur = _eur(db)
    transactions.create_transaction(
        db, type="transfer_in", occurred_at=NOON, note=None, legs=_cash_in(depot, eur)
    )

    response = client.put(f"/api/accounts/{depot}/withholding-override", json={"behaviour": None})

    assert response.status_code == 409
    assert "override" in response.json()["detail"].lower()


def test_the_api_answers_conflict_for_an_override_outside_a_broker(client, db):
    kraken = client.post("/api/platforms", json={"name": "Kraken", "kind": "exchange"}).json()["id"]
    main = client.post(f"/api/platforms/{kraken}/accounts", json={"name": "Main"}).json()["id"]

    response = client.put(f"/api/accounts/{main}/withholding-override", json={"behaviour": "none"})

    assert response.status_code == 409


def test_the_api_answers_not_found_for_an_override_on_no_account(client, db):
    response = client.put("/api/accounts/12345/withholding-override", json={"behaviour": "none"})

    assert response.status_code == 404


def test_the_api_refuses_a_base_currency_that_is_not_a_code(client, db):
    broker = client.post("/api/platforms", json={"name": "Scalable", "kind": "broker"}).json()["id"]

    response = client.post(
        f"/api/platforms/{broker}/accounts", json={"name": "Depot", "base_currency": "euro"}
    )

    assert response.status_code == 422


def test_a_depot_may_hold_cash_in_more_than_one_currency(db):
    """Cash is an Instrument like any other, so a Depot's euro and dollar
    balances are two ordinary Positions under one Account."""
    broker, depot = _depot(db)
    platforms.set_withholding(db, broker, behaviour="at_source")
    eur = _eur(db)
    usd = instruments.create_cash(db, symbol="USD", name="US Dollar")

    for instrument_id in (eur, usd):
        created = transactions.create_transaction(
            db, type="transfer_in", occurred_at=NOON, note=None, legs=_cash_in(depot, instrument_id)
        )
        assert isinstance(created, int)

    held = {
        position.symbol: position.quantity
        for position in holdings.portfolio(db)
        if position.account_id == depot
    }
    assert held == {"EUR": Decimal("1000.00"), "USD": Decimal("1000.00")}


def test_the_seed_broker_arrives_with_its_withholding_and_base_currency_set(db):
    """The development database's broker demonstrates the Depot semantics
    from day one: behaviour declared, an exemption order lodged, the Depot's
    base currency stated."""
    seed(db)

    broker = next(row for row in platforms.list_platforms(db) if row.kind == "broker")
    assert broker.withholding == "at_source"
    assert broker.exemption_order_eur is not None
    depot = next(row for row in platforms.list_accounts(db) if row.platform_id == broker.id)
    assert depot.base_currency == "EUR"

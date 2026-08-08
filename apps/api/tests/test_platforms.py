"""Platform and Account: the places that hold value and the holdings under
them. A Platform is any such place, distinguished by kind; an Account is one
holding under exactly one Platform, and the boundary for FIFO lot matching.

The seams are the repository over real Postgres — the rules under test are the
schema's own constraints — and the HTTP endpoints through the app.
"""

from collections import Counter

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from open_leprechaun.repositories import platforms
from open_leprechaun.seed import seed

KINDS = ("exchange", "cold_storage", "software_wallet", "broker", "bank")


def test_every_kind_of_place_is_one_platform_concept(db):
    """Exchange, cold storage, software wallet, broker and bank: one table,
    one shape, distinguished by kind — a new venue type is a row, not a
    hierarchy."""
    created = {
        kind: platforms.create_platform(db, name=f"Some {kind}", kind=kind) for kind in KINDS
    }

    assert all(platform_id is not None for platform_id in created.values())
    assert {row.kind for row in platforms.list_platforms(db)} == set(KINDS)


def test_the_schema_refuses_a_kind_outside_the_five(db):
    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(text("INSERT INTO platform (name, kind) VALUES ('Drawer', 'hardware')"))


def test_registering_the_same_platform_twice_mints_no_second(db):
    first = platforms.create_platform(db, name="Kraken", kind="exchange")
    duplicate = platforms.create_platform(db, name="Kraken", kind="exchange")

    assert first is not None
    assert duplicate is None


def test_one_brand_may_be_two_places_of_different_kinds(db):
    """A name is unique within its kind, not globally: a brand that runs a
    bank and a broker is two Platforms, and both must be registrable."""
    bank = platforms.create_platform(db, name="ING", kind="bank")
    broker = platforms.create_platform(db, name="ING", kind="broker")

    assert bank is not None
    assert broker is not None
    assert bank != broker


def test_a_platform_still_holding_an_account_refuses_to_be_removed(db):
    """An Account is a FIFO boundary with holdings behind it, so removing the
    place it sits under is refused rather than silently taking it along."""
    kraken = platforms.create_platform(db, name="Kraken", kind="exchange")
    platforms.create_account(db, kraken, name="Main")

    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text("DELETE FROM platform WHERE id = :id"),
            {"id": kraken},
        )


def test_no_account_is_locationless(db):
    """Every Account belongs to exactly one Platform; the schema itself
    refuses a row with none."""
    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(text("INSERT INTO account (platform_id, name) VALUES (NULL, 'Main')"))


def test_an_account_is_scoped_as_finely_as_its_platform_evidences(db):
    """A device that names each account yields several Accounts per Platform
    and per chain — the model permits it, because the FIFO boundary rests on
    evidence rather than convention."""
    device = platforms.create_platform(db, name="BitBox02", kind="cold_storage")

    savings = platforms.create_account(db, device, name="Savings", chain="bitcoin")
    spending = platforms.create_account(db, device, name="Spending", chain="bitcoin")

    assert savings is not None
    assert spending is not None
    assert {row.name for row in platforms.list_accounts(db)} == {"Savings", "Spending"}


def test_the_same_account_name_within_a_platform_mints_no_second(db):
    device = platforms.create_platform(db, name="BitBox02", kind="cold_storage")

    first = platforms.create_account(db, device, name="Savings", chain="bitcoin")
    duplicate = platforms.create_account(db, device, name="Savings", chain="bitcoin")

    assert isinstance(first, int)
    assert duplicate is platforms.Refusal.name_taken


def test_an_account_under_a_platform_that_is_not_there_says_so(db):
    """ "There is no such Platform" and "that name is taken" are different
    answers, and the constraint that failed decides which one is given."""
    assert platforms.create_account(db, 12345, name="Main") is platforms.Refusal.no_such_platform


def test_one_account_name_may_recur_across_platforms(db):
    """Uniqueness is per Platform: every venue has a "Main"."""
    kraken = platforms.create_platform(db, name="Kraken", kind="exchange")
    bank = platforms.create_platform(db, name="Sparkasse", kind="bank")

    assert isinstance(platforms.create_account(db, kraken, name="Main"), int)
    assert isinstance(platforms.create_account(db, bank, name="Main"), int)


def test_an_account_records_reference_and_access_software_as_metadata(db):
    """An address, IBAN or reference identifies the holding to a human, and
    the extra software column says how to reach it — both stored and read
    back verbatim, never handed to anything that syncs."""
    bank = platforms.create_platform(db, name="Sparkasse", kind="bank")

    account = platforms.create_account(
        db,
        bank,
        name="Giro",
        external_reference="DE02120300000000202051",
        access_software="chipTAN app",
    )

    (row,) = platforms.list_accounts(db)
    assert row.id == account
    assert row.external_reference == "DE02120300000000202051"
    assert row.access_software == "chipTAN app"
    assert row.chain is None


def test_the_api_registers_platforms_and_lists_accounts_under_them(client, db):
    """The Admin registers a place, then a holding under it, and reads both
    back in one nested answer — an Account never appears outside its
    Platform."""
    registered = client.post("/api/platforms", json={"name": "Kraken", "kind": "exchange"})
    assert registered.status_code == 201

    platform_id = registered.json()["id"]
    added = client.post(
        f"/api/platforms/{platform_id}/accounts",
        json={"name": "Main", "external_reference": "kraken-account-ref"},
    )
    assert added.status_code == 201

    (platform,) = client.get("/api/platforms").json()
    assert platform["name"] == "Kraken"
    assert platform["kind"] == "exchange"
    (account,) = platform["accounts"]
    assert account["name"] == "Main"
    assert account["external_reference"] == "kraken-account-ref"
    assert account["chain"] is None
    assert account["access_software"] is None


def test_the_api_answers_conflict_for_a_duplicate_platform(client, db):
    assert (
        client.post("/api/platforms", json={"name": "Kraken", "kind": "exchange"}).status_code
        == 201
    )

    response = client.post("/api/platforms", json={"name": "Kraken", "kind": "exchange"})

    assert response.status_code == 409


def test_the_api_refuses_a_kind_outside_the_five(client, db):
    response = client.post("/api/platforms", json={"name": "Drawer", "kind": "hardware"})

    assert response.status_code == 422


def test_the_api_refuses_a_nameless_platform(client, db):
    response = client.post("/api/platforms", json={"name": "", "kind": "exchange"})

    assert response.status_code == 422


def test_the_api_refuses_a_name_that_is_only_whitespace(client, db):
    """Trimmed before it is judged, so a blank name cannot slip in as one no
    reader could tell from another."""
    response = client.post("/api/platforms", json={"name": "   ", "kind": "exchange"})

    assert response.status_code == 422


def test_the_api_answers_not_found_for_an_account_under_no_platform(client, db):
    response = client.post("/api/platforms/12345/accounts", json={"name": "Main"})

    assert response.status_code == 404


def test_the_api_answers_conflict_for_a_duplicate_account(client, db):
    platform_id = client.post("/api/platforms", json={"name": "Kraken", "kind": "exchange"}).json()[
        "id"
    ]
    assert (
        client.post(f"/api/platforms/{platform_id}/accounts", json={"name": "Main"}).status_code
        == 201
    )

    response = client.post(f"/api/platforms/{platform_id}/accounts", json={"name": "Main"})

    assert response.status_code == 409


def test_the_seed_demonstrates_every_kind_and_the_evidence_scoped_boundary(db):
    """The development database carries one Platform of each kind, and one
    device with two Accounts on the same chain, so the settings screen has
    every grouping and the finest scoping to show from day one."""
    seed(db)

    assert {row.kind for row in platforms.list_platforms(db)} == set(KINDS)
    per_platform_chain = Counter(
        (row.platform_id, row.chain) for row in platforms.list_accounts(db) if row.chain
    )
    assert max(per_platform_chain.values()) >= 2

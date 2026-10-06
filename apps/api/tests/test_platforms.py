"""Platform and Account: the places that hold value and the holdings under
them. A Platform is any such place, distinguished by kind; an Account is one
holding under exactly one Platform, and the boundary for FIFO lot matching.

The seams are the repository over real Postgres — the rules under test are the
schema's own constraints — and the HTTP endpoints through the app.
"""

from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from open_leprechaun.repositories import (
    delegations,
    instruments,
    platforms,
    stances,
    transactions,
)
from open_leprechaun.repositories.transactions import Leg
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


def a_platform(client, name="Kraken", kind="exchange") -> int:
    return client.post("/api/platforms", json={"name": name, "kind": kind}).json()["id"]


def an_account(client, platform_id, name="Main") -> int:
    return client.post(f"/api/platforms/{platform_id}/accounts", json={"name": name}).json()["id"]


def test_the_api_removes_an_empty_platform(client, db):
    """A Platform registered by mistake can be taken back while nothing sits
    under it; afterwards it is gone from the list, and gone is not found."""
    platform_id = a_platform(client)

    assert client.delete(f"/api/platforms/{platform_id}").status_code == 204
    assert client.get("/api/platforms").json() == []
    assert client.delete(f"/api/platforms/{platform_id}").status_code == 404


def test_the_api_renames_a_platform(client, db):
    """A name is a label, so a typo made at registration does not stay for
    good: the listing reads the new name under the same identity."""
    platform_id = a_platform(client, "Krakn")

    renamed = client.put(f"/api/platforms/{platform_id}", json={"name": "Kraken"})

    assert renamed.status_code == 204
    (platform,) = client.get("/api/platforms").json()
    assert (platform["id"], platform["name"]) == (platform_id, "Kraken")


def a_connection(client, platform_id, label="Main account") -> int:
    return client.post(
        "/api/connections",
        json={
            "platform_id": platform_id,
            "venue": "okx",
            "label": label,
            "key": "AJVqhlN2mUvg5rlIT4YDkbA1",
            "secret": "wJmoXjRk8pdFqe37cChM/2Zt5yUwbBHGSA==",
            "passphrase": "correct horse battery staple",
        },
    ).json()["id"]


def _platform_names(client) -> dict[int, str]:
    return {platform["id"]: platform["name"] for platform in client.get("/api/platforms").json()}


def test_a_name_taken_within_the_kind_refuses_the_rename_and_changes_nothing(client, db):
    """Two places of one kind the Admin could not tell apart: refused in the
    words registration uses, and the Platform keeps the name it had."""
    kraken = a_platform(client, "Kraken")
    okx = a_platform(client, "OKX")

    refused = client.put(f"/api/platforms/{okx}", json={"name": "Kraken"})

    assert refused.status_code == 409
    assert refused.json()["detail"] == "'Kraken' is already registered as this kind."
    assert _platform_names(client) == {kraken: "Kraken", okx: "OKX"}


def test_a_platform_may_take_a_name_another_kind_already_uses(client, db):
    """One brand can still be two places of different kinds."""
    bank = a_platform(client, "ING", "bank")
    broker = a_platform(client, "ING DiBa", "broker")

    assert client.put(f"/api/platforms/{broker}", json={"name": "ING"}).status_code == 204
    assert _platform_names(client) == {bank: "ING", broker: "ING"}


def test_a_change_of_capitalisation_is_an_ordinary_rename(client, db):
    platform_id = a_platform(client, "kraken")

    assert client.put(f"/api/platforms/{platform_id}", json={"name": "Kraken"}).status_code == 204
    assert _platform_names(client) == {platform_id: "Kraken"}


def test_saving_a_platform_under_its_unchanged_name_succeeds(client, db):
    """Opening the form and saving it as it stood is never an error."""
    platform_id = a_platform(client, "Kraken")

    assert client.put(f"/api/platforms/{platform_id}", json={"name": "Kraken"}).status_code == 204
    assert _platform_names(client) == {platform_id: "Kraken"}


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_platform_is_never_renamed_to_nothing(client, db, blank):
    platform_id = a_platform(client, "Kraken")

    assert client.put(f"/api/platforms/{platform_id}", json={"name": blank}).status_code == 422
    assert _platform_names(client) == {platform_id: "Kraken"}


def test_a_new_platform_name_is_trimmed_as_at_registration(client, db):
    platform_id = a_platform(client, "Krakn")

    assert (
        client.put(f"/api/platforms/{platform_id}", json={"name": "  Kraken "}).status_code == 204
    )
    assert _platform_names(client) == {platform_id: "Kraken"}


def test_renaming_a_platform_that_is_not_there_answers_not_found(client, db):
    """A stale id is told apart from a refused name."""
    assert client.put("/api/platforms/12345", json={"name": "Kraken"}).status_code == 404


def test_a_platform_in_use_is_renamed_and_keeps_what_it_holds(client, db):
    """A rename is never refused because of what the Platform holds, and the
    Accounts and Connections under it stay under it."""
    platform_id = a_platform(client, "OKEx")
    account_id = an_account(client, platform_id, "Trading")
    connection_id = a_connection(client, platform_id, "Main account")

    assert client.put(f"/api/platforms/{platform_id}", json={"name": "OKX"}).status_code == 204

    (platform,) = client.get("/api/platforms").json()
    assert platform["name"] == "OKX"
    assert [account["id"] for account in platform["accounts"]] == [account_id]
    (connection,) = client.get("/api/connections").json()
    assert (connection["id"], connection["platform_id"]) == (connection_id, platform_id)


def test_the_api_refuses_to_remove_a_platform_holding_accounts_and_names_them(client, db):
    platform_id = a_platform(client)
    an_account(client, platform_id, "Main")
    an_account(client, platform_id, "Savings")

    refused = client.delete(f"/api/platforms/{platform_id}")

    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "This Platform still holds the Accounts 'Main' and 'Savings' — remove them first."
    )
    (platform,) = client.get("/api/platforms").json()
    assert [account["name"] for account in platform["accounts"]] == ["Main", "Savings"]


def test_removing_a_platform_never_removes_a_connection(client, db):
    """Discarding credentials stays its own explicit act: a Connection in the
    way refuses the removal, by name, and is still there afterwards."""
    platform_id = a_platform(client, "OKX")
    a_connection(client, platform_id, "Main account")

    refused = client.delete(f"/api/platforms/{platform_id}")

    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "This Platform still holds the Connection 'Main account' — remove it first."
    )
    assert [connection["label"] for connection in client.get("/api/connections").json()] == [
        "Main account"
    ]
    assert len(client.get("/api/platforms").json()) == 1


def test_a_platform_held_by_both_is_refused_naming_both(client, db):
    platform_id = a_platform(client, "OKX")
    an_account(client, platform_id, "Trading")
    a_connection(client, platform_id, "Bob's key")

    refused = client.delete(f"/api/platforms/{platform_id}")

    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "This Platform still holds the Account 'Trading' and the Connection 'Bob's key'"
        " — remove them first."
    )


def test_the_api_removes_an_account_nothing_was_recorded_in(client, db):
    platform_id = a_platform(client)
    account_id = an_account(client, platform_id)

    assert client.delete(f"/api/accounts/{account_id}").status_code == 204
    (platform,) = client.get("/api/platforms").json()
    assert platform["accounts"] == []
    assert client.delete(f"/api/accounts/{account_id}").status_code == 404


def test_what_the_admin_declared_about_an_account_goes_with_it(client, db):
    """A Stance, a staking marker, the withholding override and the declared
    authoritative source are settings, not history: they neither hold the
    Account nor outlive it."""
    platform_id = a_platform(client, "Scalable Capital", "broker")
    account_id = an_account(client, platform_id, "Depot")
    sol = instruments.create_native_coin(db, symbol="SOL", name="Solana", chain="solana")
    assert stances.classify(db, sol, stance="kept", account_id=account_id) == []
    assert delegations.mark(db, instrument_id=sol, account_id=account_id, note=None)
    assert client.put(
        f"/api/accounts/{account_id}/withholding-override", json={"behaviour": "none"}
    ).is_success
    assert client.put(
        f"/api/accounts/{account_id}/authoritative-source", json={"source": "csv:scalable"}
    ).is_success

    assert client.delete(f"/api/accounts/{account_id}").status_code == 204

    assert platforms.list_accounts(db) == []
    assert stances.list_stances(db, sol) == []
    assert delegations.unmark(db, instrument_id=sol, account_id=account_id) is False


def _a_leg(db, account_id):
    btc = instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    transactions.create_transaction(
        db,
        type="transfer_in",
        occurred_at=datetime(2031, 3, 14, 12, 0, tzinfo=UTC),
        note=None,
        legs=[Leg(account_id=account_id, instrument_id=btc, role="in", quantity=Decimal("0.5"))],
    )


def _an_import_batch(db, account_id):
    with db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO import_batch (source, label, account_id)"
                " VALUES ('csv:kraken', 'ledgers.csv', :account)"
            ),
            {"account": account_id},
        )


def _a_futures_record(db, account_id):
    with db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO futures_derivation_issue (source, account_id, symbol, reason)"
                " VALUES ('okx:futures', :account, 'BTC-USDT-SWAP', 'A close without an open.')"
            ),
            {"account": account_id},
        )


@pytest.mark.parametrize("record", [_a_leg, _an_import_batch, _a_futures_record])
def test_the_api_refuses_to_remove_an_account_with_recorded_history(client, db, record):
    """Past tax years point at it: a leg, an import batch — even one whose
    rows all turned out duplicates — or a futures record keeps the Account for
    good, and nothing is deleted."""
    platform_id = a_platform(client)
    account_id = an_account(client, platform_id)
    record(db, account_id)

    refused = client.delete(f"/api/accounts/{account_id}")

    assert refused.status_code == 409
    assert refused.json()["detail"] == "This Account has recorded history, so it stays for good."
    assert [row.id for row in platforms.list_accounts(db)] == [account_id]


def test_the_api_refuses_to_remove_a_paired_account_and_names_the_connection(client, db):
    """A silently unpaired Connection would keep syncing and land nothing, so
    the pairing is the Admin's to release — and it is still there afterwards."""
    platform_id = a_platform(client, "OKX")
    account_id = an_account(client, platform_id, "Trading")
    connection_id = a_connection(client, platform_id, "Main account")
    assert client.put(
        f"/api/connections/{connection_id}/pairings/spot", json={"account_id": account_id}
    ).is_success

    refused = client.delete(f"/api/accounts/{account_id}")

    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "This Account is paired with the Connection 'Main account' (spot) — unpair it first."
    )
    (connection,) = client.get("/api/connections").json()
    assert connection["pairings"] == [{"adapter_kind": "spot", "account_id": account_id}]

    assert client.delete(f"/api/connections/{connection_id}/pairings/spot").is_success
    assert client.delete(f"/api/accounts/{account_id}").status_code == 204


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

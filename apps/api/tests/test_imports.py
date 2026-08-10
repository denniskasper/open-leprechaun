"""The import framework (ticket 31): every import shows exactly what it will
create before it creates anything, commits as a separate act, is recorded as
an Import Batch reversible as a unit, and deduplicates on source and external
identifier so re-importing the same file changes nothing.

The seams are the registry schema over real Postgres, the one evaluation the
preview and the commit share, the batch repository, the manual-override
marking on the ledger's own edit and delete, the bulk repair operations, and
the HTTP endpoints.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from open_leprechaun.repositories import imports as registry
from open_leprechaun.repositories import instruments, platforms, transactions
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.services.imports import (
    ImportLeg,
    ImportRow,
    InstrumentSpec,
    commit,
    evaluate,
)
from open_leprechaun.services.transactions import overview

NOON = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)
SOURCE = "kraken-csv"


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


def _trade(external_id, eur, btc):
    return ImportRow(
        external_id=external_id,
        type="trade",
        occurred_at=NOON,
        legs=(
            ImportLeg(role="out", quantity=Decimal("100.00"), instrument_id=eur),
            ImportLeg(role="in", quantity=Decimal("0.005"), instrument_id=btc),
        ),
    )


SOL = InstrumentSpec(kind="native", symbol="SOL", name="Solana", chain="solana")


def _reward(external_id, spec=SOL):
    return ImportRow(
        external_id=external_id,
        type="staking_reward",
        occurred_at=NOON,
        legs=(ImportLeg(role="in", quantity=Decimal("2"), instrument=spec),),
    )


def _authoritative_source(db, account):
    with db.connect() as connection:
        return connection.execute(
            text("SELECT authoritative_source FROM account WHERE id = :id"), {"id": account}
        ).scalar_one()


def _counts(db):
    tables = ("transaction", "transaction_leg", "instrument", "import_batch", "imported_row")
    with db.connect() as connection:
        return {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in tables
        }


# --- The schema is the arbiter ----------------------------------------------


def test_the_registry_holds_one_row_per_source_and_external_id(db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    commit(db, source=SOURCE, label="a.csv", account_id=account, rows=[_trade("t-1", eur, btc)])

    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO imported_row (source, external_id, overridden)"
                " VALUES (:source, 't-1', true)"
            ),
            {"source": SOURCE},
        )


def test_a_registry_row_detached_from_batch_or_transaction_is_only_ever_overridden(db):
    """A row released from its batch, or outliving its Transaction, is an
    overridden tombstone by definition; the schema refuses any other state."""
    account = _account(db)
    with db.begin() as connection:
        batch = connection.execute(
            text(
                "INSERT INTO import_batch (source, label, account_id)"
                " VALUES (:source, 'a.csv', :account) RETURNING id"
            ),
            {"source": SOURCE, "account": account},
        ).scalar_one()
        transaction = connection.execute(
            text("INSERT INTO transaction (type, occurred_at) VALUES ('fee', now()) RETURNING id")
        ).scalar_one()
    detached = {"batch": None, "transaction": transaction}
    transactionless = {"batch": batch, "transaction": None}
    for row in (detached, transactionless):
        with pytest.raises(IntegrityError), db.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO imported_row (batch_id, source, external_id, transaction_id)"
                    " VALUES (:batch, :source, 't-x', :transaction)"
                ),
                {**row, "source": SOURCE},
            )


# --- The preview -------------------------------------------------------------


def test_the_preview_states_creations_skips_new_instruments_and_duplicates(db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    commit(db, source=SOURCE, label="a.csv", account_id=account, rows=[_trade("t-1", eur, btc)])

    unbalanced = ImportRow(
        external_id="t-3",
        type="trade",
        occurred_at=NOON,
        legs=(ImportLeg(role="out", quantity=Decimal("1"), instrument_id=eur),),
    )
    rows = [_trade("t-1", eur, btc), _trade("t-2", eur, btc), unbalanced, _reward("t-4")]

    preview = evaluate(db, source=SOURCE, account_id=account, rows=rows)

    assert [row.external_id for row in preview.creatable] == ["t-2", "t-4"]
    assert preview.duplicate_external_ids == ("t-1",)
    assert [(skip.external_id, skip.reason) for skip in preview.skipped] == [
        ("t-3", "A trade records what arrived, and this one is missing it.")
    ]
    assert [spec.symbol for spec in preview.new_instruments] == ["SOL"]
    assert preview.refusal is None


def test_the_preview_writes_nothing(db):
    """Nothing is written during preview — not a Transaction, not an
    Instrument, not a batch — so a cancelled import leaves no trace."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    before = _counts(db)

    evaluate(
        db,
        source=SOURCE,
        account_id=account,
        rows=[_trade("t-1", eur, btc), _reward("t-2")],
    )

    assert _counts(db) == before
    assert _authoritative_source(db, account) is None


def test_a_row_repeating_an_external_id_in_the_same_file_is_skipped(db):
    account, eur, btc = _account(db), _eur(db), _btc(db)

    preview = evaluate(
        db,
        source=SOURCE,
        account_id=account,
        rows=[_trade("t-1", eur, btc), _trade("t-1", eur, btc)],
    )

    assert [row.external_id for row in preview.creatable] == ["t-1"]
    assert [(skip.external_id, skip.reason) for skip in preview.skipped] == [
        ("t-1", "This external identifier appears earlier in the same file.")
    ]


def test_an_import_never_records_an_opening_balance(db):
    """An Opening Balance declares a reconstruction the Admin must own; no
    file gets to assert one, so the row is refused with the declaration's own
    sentence."""
    account, eur = _account(db), _eur(db)
    row = ImportRow(
        external_id="t-1",
        type="opening_balance",
        occurred_at=NOON,
        legs=(ImportLeg(role="in", quantity=Decimal("1"), instrument_id=eur),),
    )

    preview = evaluate(db, source=SOURCE, account_id=account, rows=[row])

    assert preview.creatable == ()
    (skip,) = preview.skipped
    assert skip.reason == (
        "An opening balance names what is reconstructed —"
        " the basis alone, or the date and basis both."
    )


def test_a_defective_leg_is_skipped_with_its_reason(db):
    account, eur = _account(db), _eur(db)
    missing_instrument = ImportRow(
        external_id="t-1",
        type="fee",
        occurred_at=NOON,
        legs=(ImportLeg(role="fee", quantity=Decimal("1"), instrument_id=999999),),
    )
    nonpositive = ImportRow(
        external_id="t-2",
        type="fee",
        occurred_at=NOON,
        legs=(ImportLeg(role="fee", quantity=Decimal("0"), instrument_id=eur),),
    )
    unnamed = ImportRow(
        external_id="t-3",
        type="fee",
        occurred_at=NOON,
        legs=(ImportLeg(role="fee", quantity=Decimal("1")),),
    )

    preview = evaluate(
        db, source=SOURCE, account_id=account, rows=[missing_instrument, nonpositive, unnamed]
    )

    assert preview.creatable == ()
    assert [(skip.external_id, skip.reason) for skip in preview.skipped] == [
        ("t-1", "No such Instrument."),
        ("t-2", "A quantity is positive — direction is a leg's role."),
        ("t-3", "A leg names its Instrument by id or by identity, and exactly one."),
    ]


def test_the_preview_resolves_a_security_by_a_superseded_isin(db):
    """A file exported before a merger still names the old ISIN; the
    identifier history resolves it to the same Instrument instead of minting
    a double."""
    account = _account(db, platform_name="Comdirect", kind="broker")
    security = instruments.create_security(
        db, symbol="ACME", name="Acme SE", type="share", isin="DE0000000001"
    )
    assert instruments.change_isin(db, security, new_isin="IE0000000002")
    row = ImportRow(
        external_id="t-1",
        type="dividend",
        occurred_at=NOON,
        legs=(
            ImportLeg(
                role="in",
                quantity=Decimal("10"),
                instrument=InstrumentSpec(
                    kind="security",
                    symbol="ACME",
                    name="Acme SE",
                    security_type="share",
                    isin="DE0000000001",
                ),
            ),
        ),
    )

    preview = evaluate(db, source="broker-csv", account_id=account, rows=[row])

    assert [r.external_id for r in preview.creatable] == ["t-1"]
    assert preview.new_instruments == ()


# --- Commit ------------------------------------------------------------------


def test_commit_records_the_batch_the_transactions_and_the_registry(db):
    account, eur, btc = _account(db), _eur(db), _btc(db)

    committed = commit(
        db,
        source=SOURCE,
        label="a.csv",
        account_id=account,
        rows=[_trade("t-1", eur, btc), _reward("t-2")],
    )

    assert committed.created == 2
    assert committed.duplicates == 0
    assert committed.instruments_created == 1
    (batch,) = registry.list_batches(db)
    assert (batch.id, batch.source, batch.label, batch.account_id) == (
        committed.batch_id,
        SOURCE,
        "a.csv",
        account,
    )
    assert (batch.rows, batch.overridden) == (2, 0)
    ledger = {row.type: row for row in overview(db)}
    assert set(ledger) == {"trade", "staking_reward"}
    for row in ledger.values():
        assert row.import_batch_id == committed.batch_id
        assert row.import_source == SOURCE
        assert row.manually_overridden is False
    assert all(leg.account_id == account for row in ledger.values() for leg in row.legs)
    sol = ledger["staking_reward"].legs[0].instrument_id
    assert instruments.get(db, sol).symbol == "SOL"


def test_reimporting_the_same_file_changes_nothing(db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    rows = [_trade("t-1", eur, btc), _trade("t-2", eur, btc)]
    commit(db, source=SOURCE, label="a.csv", account_id=account, rows=rows)
    before = _counts(db)

    preview = evaluate(db, source=SOURCE, account_id=account, rows=rows)
    recommitted = commit(db, source=SOURCE, label="a.csv", account_id=account, rows=rows)

    assert preview.duplicate_external_ids == ("t-1", "t-2")
    assert (recommitted.batch_id, recommitted.created, recommitted.duplicates) == (None, 0, 2)
    assert _counts(db) == before


def test_the_first_commit_declares_its_source_and_a_second_source_may_not_write(db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    commit(db, source=SOURCE, label="a.csv", account_id=account, rows=[_trade("t-1", eur, btc)])
    assert _authoritative_source(db, account) == SOURCE
    before = _counts(db)

    preview = evaluate(db, source="kraken-api", account_id=account, rows=[_trade("x-1", eur, btc)])
    refused = commit(
        db, source="kraken-api", label="sync", account_id=account, rows=[_trade("x-1", eur, btc)]
    )

    assert preview.refusal.kind is registry.Refusal.not_authoritative
    assert preview.refusal.sentence == (
        f"{SOURCE!r} is authoritative for this Account —"
        " 'kraken-api' may reconcile but may not write."
    )
    assert preview.refusal.sentence in preview.warnings
    assert refused.kind is registry.Refusal.not_authoritative
    assert _counts(db) == before


def test_a_commit_into_a_missing_account_is_refused(db):
    eur, btc = _eur(db), _btc(db)

    refused = commit(
        db, source=SOURCE, label="a.csv", account_id=999999, rows=[_trade("t-1", eur, btc)]
    )

    assert refused.kind is registry.Refusal.no_such_account


# --- Reversal ----------------------------------------------------------------


def test_reversing_a_batch_removes_what_it_created_as_a_unit(db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    rows = [_trade("t-1", eur, btc), _trade("t-2", eur, btc)]
    committed = commit(db, source=SOURCE, label="a.csv", account_id=account, rows=rows)

    assert registry.reverse_batch(db, committed.batch_id) is True

    assert overview(db) == []
    assert registry.list_batches(db) == []
    reimported = commit(db, source=SOURCE, label="a.csv", account_id=account, rows=rows)
    assert reimported.created == 2

    assert registry.reverse_batch(db, committed.batch_id) is False


def test_reversal_spares_a_row_the_admin_took_ownership_of(db):
    """An edited imported row is the Admin's now: reversing the batch removes
    the rest, leaves that Transaction standing, and keeps its tombstone so a
    re-import does not resurrect the original."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    rows = [_trade("t-1", eur, btc), _trade("t-2", eur, btc)]
    committed = commit(db, source=SOURCE, label="a.csv", account_id=account, rows=rows)
    edited = next(row for row in overview(db) if row.import_source == SOURCE)
    transactions.replace_transaction(
        db,
        edited.id,
        type="trade",
        occurred_at=NOON,
        note="corrected by hand",
        legs=[
            Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal("90")),
            Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("0.005")),
        ],
    )

    assert registry.reverse_batch(db, committed.batch_id) is True

    (survivor,) = overview(db)
    assert (survivor.id, survivor.note) == (edited.id, "corrected by hand")
    assert survivor.manually_overridden is True
    assert survivor.import_batch_id is None
    reimported = commit(db, source=SOURCE, label="a.csv", account_id=account, rows=rows)
    assert (reimported.created, reimported.duplicates) == (1, 1)
    assert survivor.note in {row.note for row in overview(db)}


def test_a_manually_deleted_imported_row_stays_deleted_through_reimport(db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    commit(db, source=SOURCE, label="a.csv", account_id=account, rows=[_trade("t-1", eur, btc)])
    (imported,) = overview(db)

    assert transactions.delete_transaction(db, imported.id) is True

    preview = evaluate(db, source=SOURCE, account_id=account, rows=[_trade("t-1", eur, btc)])
    assert preview.duplicate_external_ids == ("t-1",)
    recommitted = commit(
        db, source=SOURCE, label="a.csv", account_id=account, rows=[_trade("t-1", eur, btc)]
    )
    assert (recommitted.created, recommitted.duplicates) == (0, 1)
    assert overview(db) == []


# --- The ledger's own hands --------------------------------------------------


def test_the_ledger_marks_an_imported_row_edited_or_deleted_by_hand(client, db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    commit(
        db,
        source=SOURCE,
        label="a.csv",
        account_id=account,
        rows=[_trade("t-1", eur, btc), _trade("t-2", eur, btc)],
    )
    first, second = client.get("/api/transactions").json()
    revision = {
        "type": "trade",
        "occurred_at": "2026-03-14T12:00:00Z",
        "note": "corrected by hand",
        "legs": [
            {"account_id": account, "instrument_id": eur, "role": "out", "quantity": "90"},
            {"account_id": account, "instrument_id": btc, "role": "in", "quantity": "0.005"},
        ],
    }

    assert client.put(f"/api/transactions/{first['id']}", json=revision).status_code == 204
    assert client.delete(f"/api/transactions/{second['id']}").status_code == 204

    (row,) = [row for row in client.get("/api/transactions").json() if row["id"] == first["id"]]
    assert row["manually_overridden"] is True
    assert row["import_source"] == SOURCE
    with db.connect() as connection:
        tombstone = connection.execute(
            text(
                "SELECT overridden, transaction_id FROM imported_row"
                " WHERE external_id IN ('t-1', 't-2') AND transaction_id IS NULL"
            )
        ).one()
    assert tombstone.overridden is True


# --- Bulk repair -------------------------------------------------------------


def test_bulk_reassignment_moves_every_leg_and_marks_imported_rows_overridden(client, db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    other = _account(db, name="Earn")
    commit(db, source=SOURCE, label="a.csv", account_id=account, rows=[_trade("t-1", eur, btc)])
    (imported,) = client.get("/api/transactions").json()

    reassigned = client.post(
        "/api/transactions/bulk-reassignment",
        json={"transaction_ids": [imported["id"]], "account_id": other},
    )

    assert reassigned.status_code == 204
    (row,) = client.get("/api/transactions").json()
    assert all(leg["account_id"] == other for leg in row["legs"])
    assert row["manually_overridden"] is True

    missing_account = client.post(
        "/api/transactions/bulk-reassignment",
        json={"transaction_ids": [imported["id"]], "account_id": 999999},
    )
    assert missing_account.status_code == 404
    missing_transaction = client.post(
        "/api/transactions/bulk-reassignment",
        json={"transaction_ids": [999999], "account_id": other},
    )
    assert missing_transaction.status_code == 404


def test_bulk_retyping_holds_the_vocabulary_and_marks_rows_overridden(client, db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    inflow = ImportRow(
        external_id="t-1",
        type="transfer_in",
        occurred_at=NOON,
        legs=(ImportLeg(role="in", quantity=Decimal("2"), instrument_id=btc),),
    )
    commit(
        db,
        source=SOURCE,
        label="a.csv",
        account_id=account,
        rows=[inflow, _trade("t-2", eur, btc)],
    )
    rows = {row["type"]: row for row in client.get("/api/transactions").json()}

    retyped = client.post(
        "/api/transactions/bulk-retyping",
        json={"transaction_ids": [rows["transfer_in"]["id"]], "type": "staking_reward"},
    )

    assert retyped.status_code == 204
    listed = {row["id"]: row for row in client.get("/api/transactions").json()}
    assert listed[rows["transfer_in"]["id"]]["type"] == "staking_reward"
    assert listed[rows["transfer_in"]["id"]]["manually_overridden"] is True

    refused = client.post(
        "/api/transactions/bulk-retyping",
        json={"transaction_ids": [rows["trade"]["id"]], "type": "staking_reward"},
    )
    assert refused.status_code == 422
    assert refused.json()["detail"] == (
        f"Transaction {rows['trade']['id']}: A staking reward does not record what left —"
        " that is its own Transaction."
    )
    assert listed[rows["trade"]["id"]]["manually_overridden"] is False


# --- The HTTP endpoints ------------------------------------------------------


def _api_rows(eur, btc):
    return [
        {
            "external_id": "t-1",
            "type": "trade",
            "occurred_at": "2026-03-14T12:00:00Z",
            "legs": [
                {"role": "out", "quantity": "100.00", "instrument_id": eur},
                {"role": "in", "quantity": "0.005", "instrument_id": btc},
            ],
        },
        {
            "external_id": "t-2",
            "type": "staking_reward",
            "occurred_at": "2026-03-14T12:00:00Z",
            "legs": [
                {
                    "role": "in",
                    "quantity": "2",
                    "instrument": {
                        "kind": "native",
                        "symbol": "SOL",
                        "name": "Solana",
                        "chain": "solana",
                    },
                }
            ],
        },
    ]


def test_the_api_previews_commits_lists_and_reverses_an_import(client, db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    file = {"source": SOURCE, "account_id": account, "rows": _api_rows(eur, btc)}

    previewed = client.post("/api/imports/preview", json=file)
    assert previewed.status_code == 200
    preview = previewed.json()
    assert [row["external_id"] for row in preview["to_create"]] == ["t-1", "t-2"]
    assert preview["duplicates"] == 0
    assert preview["skipped"] == []
    assert [spec["symbol"] for spec in preview["new_instruments"]] == ["SOL"]
    assert any("unacknowledged" in warning for warning in preview["warnings"])
    assert client.get("/api/transactions").json() == []

    committed = client.post("/api/imports", json={**file, "label": "a.csv"})
    assert committed.status_code == 201
    assert committed.json()["created"] == 2
    batch_id = committed.json()["batch_id"]

    (batch,) = client.get("/api/import-batches").json()
    assert (batch["id"], batch["source"], batch["label"], batch["rows"]) == (
        batch_id,
        SOURCE,
        "a.csv",
        2,
    )

    assert client.delete(f"/api/import-batches/{batch_id}").status_code == 204
    assert client.get("/api/transactions").json() == []
    assert client.get("/api/import-batches").json() == []
    assert client.delete(f"/api/import-batches/{batch_id}").status_code == 404


def test_the_api_refuses_a_commit_from_a_second_source_with_the_sentence(client, db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    file = {"source": SOURCE, "label": "a.csv", "account_id": account, "rows": _api_rows(eur, btc)}
    assert client.post("/api/imports", json=file).status_code == 201

    refused = client.post("/api/imports", json={**file, "source": "kraken-api"})

    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        f"{SOURCE!r} is authoritative for this Account —"
        " 'kraken-api' may reconcile but may not write."
    )


def test_the_account_declares_and_clears_its_authoritative_source(client, db):
    account, eur, btc = _account(db), _eur(db), _btc(db)
    file = {"source": SOURCE, "label": "a.csv", "account_id": account, "rows": _api_rows(eur, btc)}

    declared = client.put(
        f"/api/accounts/{account}/authoritative-source", json={"source": "kraken-api"}
    )
    assert declared.status_code == 204
    (platform,) = client.get("/api/platforms").json()
    assert platform["accounts"][0]["authoritative_source"] == "kraken-api"
    assert client.post("/api/imports", json=file).status_code == 409

    cleared = client.put(f"/api/accounts/{account}/authoritative-source", json={"source": None})
    assert cleared.status_code == 204
    assert client.post("/api/imports", json=file).status_code == 201

    missing = client.put("/api/accounts/999999/authoritative-source", json={"source": "x"})
    assert missing.status_code == 404

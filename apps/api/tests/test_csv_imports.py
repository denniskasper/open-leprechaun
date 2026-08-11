"""The CSV connector port and the file-import seam (ticket 32, ADR-0008):
a connector parses one venue's exported file into normalized rows, and the
import framework alone decides what enters the ledger — preview first, commit
as a separate act, one reversible batch.

The seam is the HTTP API over real Postgres with a fake of the connector port
standing in through the same registry dependency production reads, so adding
a connector is a registry entry and nothing else: no service, router or
screen changes, which this file proves by driving an invented connector end
to end.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from open_leprechaun.adapters import get_csv_connectors
from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.ports.csv_connector import FileRejectedError, NormalizedRow, ParsedFile
from open_leprechaun.repositories import instruments


@dataclass(frozen=True)
class FakeConnector:
    """The port's fake: what it answers is set by the test, and `parse`
    refuses exactly when told to — no file format involved."""

    connector: str = "fake"
    name: str = "Fake wallet"
    expects: str = "The CSV the fake wallet exports."
    timezone: str = "UTC"
    parsed: ParsedFile = field(default_factory=ParsedFile)
    rejects_with: str | None = None

    def parse(self, content: str) -> ParsedFile:
        if self.rejects_with is not None:
            raise FileRejectedError(self.rejects_with)
        return self.parsed


@pytest.fixture
def connectors() -> dict:
    """The connector registry under test control — tests attach fakes; the
    dict is read per request, so later edits take effect."""
    return {}


@pytest.fixture
def client(db: Engine, connectors: dict) -> Iterator[TestClient]:
    """The API bound to the migrated test database and the fake connector
    registry."""
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_csv_connectors] = lambda: connectors
    with TestClient(app) as client:
        yield client


def cold_storage(client: TestClient, name: str = "Hardware wallet") -> int:
    return client.post("/api/platforms", json={"name": name, "kind": "cold_storage"}).json()["id"]


def account(client: TestClient, platform_id: int, name: str = "Bitcoin") -> int:
    return client.post(f"/api/platforms/{platform_id}/accounts", json={"name": name}).json()["id"]


def row(**overrides) -> NormalizedRow:
    given = dict(
        external_id="tx-1",
        occurred_at=datetime(2026, 3, 14, 12, 0, tzinfo=UTC),
        type="transfer_in",
        symbol="BTC",
        quantity=Decimal("0.5"),
    )
    given.update(overrides)
    return NormalizedRow(**given)


def test_the_registry_names_each_connector_and_what_its_file_looks_like(client, connectors):
    """The screen renders its picker from this answer alone, so a new
    connector appears without any UI change: name, the file to produce, and
    the timezone its timestamps are read in."""
    connectors["fake"] = FakeConnector()

    listed = client.get("/api/csv-connectors")

    assert listed.status_code == 200
    assert listed.json() == [
        {
            "connector": "fake",
            "name": "Fake wallet",
            "expects": "The CSV the fake wallet exports.",
            "timezone": "UTC",
        }
    ]


def test_the_shipped_registry_serves_the_two_hardware_wallet_connectors():
    """What production reads through the same dependency the fakes stand in
    for: both hardware-wallet connectors, each keyed by its own name."""
    shipped = get_csv_connectors()

    assert sorted(shipped) == ["bitbox", "ledger_live"]
    assert all(key == connector.connector for key, connector in shipped.items())


# --- Preview: what the file would create, without writing anything ---


def test_the_preview_answers_the_rows_and_the_connectors_own_warnings(client, connectors, db):
    """The framework's preview — creations, duplicates, skips — wearing the
    connector's warnings first: what the file could not or should not yield
    is part of what the Admin judges before committing."""
    instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    account_id = account(client, cold_storage(client))
    connectors["fake"] = FakeConnector(
        parsed=ParsedFile(
            rows=(row(), row(external_id="tx-2", type="transfer_out", quantity=Decimal("0.1"))),
            warnings=("2 unconfirmed rows were left out.",),
        )
    )

    preview = client.post(
        "/api/csv-imports/preview",
        json={"connector": "fake", "account_id": account_id, "content": "whatever"},
    )

    assert preview.status_code == 200
    answered = preview.json()
    assert [entry["external_id"] for entry in answered["to_create"]] == ["tx-1", "tx-2"]
    assert answered["duplicates"] == 0
    assert answered["skipped"] == []
    assert answered["warnings"][0] == "2 unconfirmed rows were left out."


def test_the_preview_writes_nothing(client, connectors, db):
    instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    account_id = account(client, cold_storage(client))
    connectors["fake"] = FakeConnector(parsed=ParsedFile(rows=(row(),)))

    client.post(
        "/api/csv-imports/preview",
        json={"connector": "fake", "account_id": account_id, "content": "whatever"},
    )

    assert client.get("/api/transactions").json() == []
    assert client.get("/api/import-batches").json() == []


def test_a_file_the_connector_refuses_is_answered_with_its_sentence(client, connectors):
    """A mismatched file or an unsupported variant is refused whole — the
    connector's own sentence travels to the Admin instead of a mis-parse."""
    account_id = account(client, cold_storage(client))
    connectors["fake"] = FakeConnector(rejects_with="This is not the fake wallet's export.")

    preview = client.post(
        "/api/csv-imports/preview",
        json={"connector": "fake", "account_id": account_id, "content": "wrong,file"},
    )

    assert preview.status_code == 422
    assert preview.json()["detail"] == "This is not the fake wallet's export."


def test_an_unknown_connector_is_refused(client, connectors):
    account_id = account(client, cold_storage(client))

    preview = client.post(
        "/api/csv-imports/preview",
        json={"connector": "nobody", "account_id": account_id, "content": "whatever"},
    )

    assert preview.status_code == 404
    assert preview.json()["detail"] == "No connector reads this file."


def test_a_symbol_nothing_answers_to_refuses_the_file_with_the_sentence(client, connectors):
    """A symbol is a resolution hint, never an identity (ADR-0010): a file
    naming an Instrument the ledger does not hold refuses whole instead of
    guessing or minting one from a bare symbol."""
    account_id = account(client, cold_storage(client))
    connectors["fake"] = FakeConnector(parsed=ParsedFile(rows=(row(),)))

    preview = client.post(
        "/api/csv-imports/preview",
        json={"connector": "fake", "account_id": account_id, "content": "whatever"},
    )

    assert preview.status_code == 422
    assert preview.json()["detail"] == (
        "No Instrument answers to 'BTC' — create it, then import again."
    )


# --- Commit: the separate act, one reversible batch, idempotent re-import ---


def test_commit_lands_the_file_as_one_batch_under_its_scoped_source(client, connectors, db):
    """The batch carries the file's label and a source scoped to the Account
    ("fake:<id>"), and the rows wear their legs — the fee charged against the
    movement it enabled."""
    instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    account_id = account(client, cold_storage(client))
    connectors["fake"] = FakeConnector(
        parsed=ParsedFile(
            rows=(
                row(type="transfer_out", quantity=Decimal("0.4"), fee_quantity=Decimal("0.0001")),
            )
        )
    )

    committed = client.post(
        "/api/csv-imports",
        json={
            "connector": "fake",
            "account_id": account_id,
            "content": "whatever",
            "label": "export.csv",
        },
    )

    assert committed.status_code == 201
    assert committed.json()["created"] == 1
    (batch,) = client.get("/api/import-batches").json()
    assert batch["source"] == f"fake:{account_id}"
    assert batch["label"] == "export.csv"
    (transaction,) = client.get("/api/transactions").json()
    assert transaction["type"] == "transfer_out"
    roles = {leg["role"]: leg for leg in transaction["legs"]}
    assert roles["out"]["quantity"] == "0.4"
    assert roles["fee"]["quantity"] == "0.0001"
    assert roles["fee"]["charged_against_leg_id"] == roles["out"]["id"]


def test_reimporting_the_same_file_changes_nothing(client, connectors, db):
    instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    account_id = account(client, cold_storage(client))
    connectors["fake"] = FakeConnector(parsed=ParsedFile(rows=(row(),)))
    request = {
        "connector": "fake",
        "account_id": account_id,
        "content": "whatever",
        "label": "export.csv",
    }
    client.post("/api/csv-imports", json=request)

    again = client.post("/api/csv-imports", json=request)

    assert again.status_code == 201
    assert again.json() == {
        "batch_id": None,
        "created": 0,
        "duplicates": 1,
        "skipped": 0,
        "instruments_created": 0,
    }
    assert len(client.get("/api/import-batches").json()) == 1


def test_two_accounts_fed_by_the_same_connector_do_not_swallow_each_others_rows(
    client, connectors, db
):
    """A transfer between two of the Admin's own wallets appears in both
    exports under one transaction id, and both sides are facts: the source is
    scoped per Account, so deduplication holds a file to its Account."""
    instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    platform_id = cold_storage(client)
    first = account(client, platform_id, name="Wallet A")
    second = account(client, platform_id, name="Wallet B")
    connectors["fake"] = FakeConnector(parsed=ParsedFile(rows=(row(type="transfer_out"),)))
    client.post(
        "/api/csv-imports",
        json={"connector": "fake", "account_id": first, "content": "a", "label": "a.csv"},
    )
    connectors["fake"] = FakeConnector(parsed=ParsedFile(rows=(row(type="transfer_in"),)))

    landed = client.post(
        "/api/csv-imports",
        json={"connector": "fake", "account_id": second, "content": "b", "label": "b.csv"},
    )

    assert landed.json()["created"] == 1
    assert landed.json()["duplicates"] == 0


def test_a_second_source_may_preview_but_not_commit_into_the_account(client, connectors, db):
    """The first commit declares its scoped source authoritative for the
    Account (ticket 31); another connector may reconcile there but its commit
    is refused with the sentence naming the holder."""
    instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    account_id = account(client, cold_storage(client))
    connectors["fake"] = FakeConnector(parsed=ParsedFile(rows=(row(),)))
    connectors["other"] = FakeConnector(
        connector="other", name="Other wallet", parsed=ParsedFile(rows=(row(external_id="tx-9"),))
    )
    client.post(
        "/api/csv-imports",
        json={"connector": "fake", "account_id": account_id, "content": "a", "label": "a.csv"},
    )

    previewed = client.post(
        "/api/csv-imports/preview",
        json={"connector": "other", "account_id": account_id, "content": "b"},
    )
    refused = client.post(
        "/api/csv-imports",
        json={"connector": "other", "account_id": account_id, "content": "b", "label": "b.csv"},
    )

    assert previewed.status_code == 200
    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        f"'fake:{account_id}' is authoritative for this Account —"
        f" 'other:{account_id}' may reconcile but may not write."
    )

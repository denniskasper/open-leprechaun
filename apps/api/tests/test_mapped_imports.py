"""The generic column-mapping flow over HTTP (ticket 33): the Admin maps an
arbitrary file's columns onto ledger fields, watches the first rows
interpreted live, saves the mapping under a name for a later file, and the
result flows through the same preview, batch and reversal machinery as any
shipped connector's import.

The seam is the HTTP API over real Postgres — the same evaluation ticket 31
pinned decides what enters; these tests prove the mapped file reaches it and
nothing else changed.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.repositories import instruments

EXPORT = (
    "Datum;Typ;Coin;Betrag;Gebühr;Referenz\n"
    "01.07.2026 14:30;Einzahlung;BTC;0,5;0,0001;abc-1\n"
    "02.01.2026 09:00;Auszahlung;BTC;-0,2;;abc-2\n"
)


@pytest.fixture
def client(db: Engine) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    with TestClient(app) as client:
        yield client


def mapping(**overrides) -> dict:
    given = dict(
        occurred_at="Datum",
        datetime_format="%d.%m.%Y %H:%M",
        timezone="Europe/Berlin",
        delimiter=";",
        decimal_comma=True,
        quantity="Betrag",
        symbol="Coin",
        type="Typ",
        type_values={"Einzahlung": "transfer_in", "Auszahlung": "transfer_out"},
        external_id="Referenz",
        fee_quantity="Gebühr",
    )
    given.update(overrides)
    return given


def account(client: TestClient) -> int:
    platform = client.post(
        "/api/platforms", json={"name": "Some venue", "kind": "exchange"}
    ).json()["id"]
    return client.post(f"/api/platforms/{platform}/accounts", json={"name": "Main"}).json()["id"]


# --- The live interpretation the mapping screen renders ---


def test_interpret_answers_the_first_rows_as_they_would_be_interpreted(client):
    """The live preview over HTTP: columns for the pickers, each row's
    normalized reading with quantities as fixed-point strings, and an empty
    defect list once the mapping is complete."""
    answered = client.post(
        "/api/column-mappings/interpret", json={"content": EXPORT, "mapping": mapping()}
    )

    assert answered.status_code == 200
    interpretation = answered.json()
    assert interpretation["columns"] == ["Datum", "Typ", "Coin", "Betrag", "Gebühr", "Referenz"]
    assert interpretation["defects"] == []
    assert interpretation["row_count"] == 2
    first = interpretation["rows"][0]
    assert first == {
        "number": 1,
        "external_id": "abc-1",
        "occurred_at": "2026-07-01T12:30:00Z",
        "type": "transfer_in",
        "symbol": "BTC",
        "quantity": "0.5",
        "fee_quantity": "0.0001",
        "note": None,
        "left_out": None,
        "problems": [],
    }


def test_interpret_names_the_defects_of_a_half_built_mapping(client):
    """Lenient on purpose: the mapping screen calls this while the Admin is
    still assigning columns, so an incomplete mapping answers its defects and
    whatever rows it can already read — never a refusal."""
    answered = client.post(
        "/api/column-mappings/interpret",
        json={
            "content": EXPORT,
            "mapping": {"delimiter": ";", "quantity": "Betrag", "decimal_comma": True},
        },
    )

    assert answered.status_code == 200
    interpretation = answered.json()
    assert "No column is assigned to the timestamp." in interpretation["defects"]
    assert interpretation["rows"][0]["quantity"] == "0.5"


# --- Saved mappings: named, listed, reused, deleted ---


def test_a_mapping_saves_under_a_name_and_lists_back(client):
    saved = client.post("/api/column-mappings", json={"name": "Some venue", "mapping": mapping()})

    assert saved.status_code == 201
    listed = client.get("/api/column-mappings").json()
    assert [entry["name"] for entry in listed] == ["Some venue"]
    assert listed[0]["mapping"]["occurred_at"] == "Datum"
    assert listed[0]["mapping"]["type_values"] == {
        "Einzahlung": "transfer_in",
        "Auszahlung": "transfer_out",
    }


def test_saving_under_the_same_name_replaces_the_mapping(client):
    client.post("/api/column-mappings", json={"name": "Some venue", "mapping": mapping()})

    client.post(
        "/api/column-mappings",
        json={"name": "Some venue", "mapping": mapping(fixed_symbol="ETH", symbol=None)},
    )

    listed = client.get("/api/column-mappings").json()
    assert len(listed) == 1
    assert listed[0]["mapping"]["fixed_symbol"] == "ETH"


def test_an_incomplete_mapping_does_not_save(client):
    """A saved mapping is a complete declaration — required fields are
    enforced before anything can be reused, with the sentences naming what is
    missing."""
    refused = client.post(
        "/api/column-mappings",
        json={"name": "Half done", "mapping": {"quantity": "Betrag"}},
    )

    assert refused.status_code == 422
    assert "No column is assigned to the timestamp." in refused.json()["detail"]
    assert client.get("/api/column-mappings").json() == []


def test_a_saved_mapping_deletes(client):
    saved = client.post(
        "/api/column-mappings", json={"name": "Some venue", "mapping": mapping()}
    ).json()

    gone = client.delete(f"/api/column-mappings/{saved['id']}")

    assert gone.status_code == 204
    assert client.get("/api/column-mappings").json() == []
    assert client.delete(f"/api/column-mappings/{saved['id']}").status_code == 404


# --- The import itself: the same preview, batch and reversal machinery ---


def test_preview_runs_the_mapped_file_through_the_import_framework(client, db):
    instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    account_id = account(client)

    previewed = client.post(
        "/api/mapped-imports/preview",
        json={"account_id": account_id, "content": EXPORT, "mapping": mapping()},
    )

    assert previewed.status_code == 200
    answered = previewed.json()
    assert [row["external_id"] for row in answered["to_create"]] == ["abc-1", "abc-2"]
    assert answered["skipped"] == []
    # Nothing was written — the preview is the framework's own.
    assert client.get("/api/transactions").json() == []
    assert client.get("/api/import-batches").json() == []


def test_an_incomplete_mapping_cannot_proceed_to_import(client):
    account_id = account(client)

    refused = client.post(
        "/api/mapped-imports/preview",
        json={"account_id": account_id, "content": EXPORT, "mapping": {"quantity": "Betrag"}},
    )

    assert refused.status_code == 422
    assert "No column is assigned to the timestamp." in refused.json()["detail"]


def test_commit_lands_one_reversible_batch_under_the_mapping_source(client, db):
    """The batch wears the "mapping:<account>" source — whichever saved
    mapping read the file, the Account's rows are one series — and reversal
    removes what it created, exactly as for any other import."""
    instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    account_id = account(client)

    committed = client.post(
        "/api/mapped-imports",
        json={
            "account_id": account_id,
            "content": EXPORT,
            "mapping": mapping(),
            "label": "venue-export.csv",
        },
    )

    assert committed.status_code == 201
    assert committed.json()["created"] == 2
    (batch,) = client.get("/api/import-batches").json()
    assert batch["source"] == f"mapping:{account_id}"
    assert batch["label"] == "venue-export.csv"
    transactions = client.get("/api/transactions").json()
    assert sorted(entry["type"] for entry in transactions) == ["transfer_in", "transfer_out"]

    reversed_ = client.delete(f"/api/import-batches/{batch['id']}")
    assert reversed_.status_code == 204
    assert client.get("/api/transactions").json() == []


def test_reimporting_the_same_file_changes_nothing_even_under_another_saved_mapping(client, db):
    """Deduplication holds to the Account, not to which mapping read the
    file: a re-import under a renamed or re-saved mapping still changes
    nothing."""
    instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    account_id = account(client)
    request = {
        "account_id": account_id,
        "content": EXPORT,
        "mapping": mapping(),
        "label": "venue-export.csv",
    }
    client.post("/api/mapped-imports", json=request)

    again = client.post("/api/mapped-imports", json={**request, "mapping": mapping(note="Coin")})

    assert again.status_code == 201
    assert again.json() == {
        "batch_id": None,
        "created": 0,
        "duplicates": 2,
        "skipped": 0,
        "instruments_created": 0,
    }
    assert len(client.get("/api/import-batches").json()) == 1

"""The Address Indexer port and the address-import seam (ticket 38,
ADR-0008): an indexer answers what moved at a public address, and the import
framework alone decides what enters the ledger — preview first, commit as a
separate act, one reversible batch.

The seam is the HTTP API over real Postgres with a fake of the indexer port
standing in through the same registry dependency production reads, so adding
a chain is a registry entry and nothing else.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from open_leprechaun.adapters import get_address_indexers
from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.ports.address_indexer import (
    AddressHistory,
    AddressRejectedError,
    ChainAsset,
    IndexerError,
    NormalizedAddressTransfer,
    NormalizedNetworkFee,
)
from open_leprechaun.repositories import instruments
from open_leprechaun.services import lots

COIN = ChainAsset(symbol="FKE", name="Fakecoin")
# Mixed case on purpose: an address on a chain that writes case-sensitive
# addresses must survive the ledger exactly as the chain states it.
UNKNOWN_TOKEN = ChainAsset(
    symbol="DUST",
    name="Dust Token",
    contract_address="DustMintAddr3ssWithMixedCase1111111111111111",
)
ADDRESS = "Wa11etAddr3ss"
NOON = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)


@dataclass
class FakeIndexer:
    """The port's fake: what it answers is set by the test, and it records
    every address it was asked about — the whole of what an indexer is ever
    given."""

    chain: str = "fakechain"
    name: str = "Fakechain"
    native: ChainAsset = COIN
    lookback_days: int | None = None
    answers: AddressHistory = field(default_factory=AddressHistory)
    rejects_with: str | None = None
    fails_with: str | None = None
    asked: list[str] = field(default_factory=list)

    def history(self, address: str) -> AddressHistory:
        self.asked.append(address)
        if self.rejects_with is not None:
            raise AddressRejectedError(self.rejects_with)
        if self.fails_with is not None:
            raise IndexerError(self.fails_with)
        return self.answers


@pytest.fixture
def indexers() -> dict:
    """The indexer registry under test control — the dict is read per
    request, so later edits take effect."""
    return {}


@pytest.fixture
def client(db: Engine, indexers: dict) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_address_indexers] = lambda: indexers
    with TestClient(app) as client:
        yield client


def wallet_account(client: TestClient, name: str = "Main") -> int:
    platform = client.post("/api/platforms", json={"name": "Phantom", "kind": "software_wallet"})
    assert platform.status_code == 201, platform.text
    created = client.post(f"/api/platforms/{platform.json()['id']}/accounts", json={"name": name})
    return created.json()["id"]


def transfer(**overrides) -> NormalizedAddressTransfer:
    given = dict(
        external_id="sig-1:native",
        occurred_at=NOON,
        direction="in",
        asset=COIN,
        quantity=Decimal("2.5"),
    )
    given.update(overrides)
    return NormalizedAddressTransfer(**given)


def request(account_id: int, **overrides) -> dict:
    return {"chain": "fakechain", "address": ADDRESS, "account_id": account_id, **overrides}


def test_the_registry_names_each_chain_an_address_can_be_read_on(client, indexers):
    """The screen renders its picker from this answer alone, so a new chain
    appears without any UI change."""
    indexers["fakechain"] = FakeIndexer()

    listed = client.get("/api/address-indexers")

    assert listed.status_code == 200
    assert listed.json() == [
        {"chain": "fakechain", "name": "Fakechain", "native_symbol": "FKE", "lookback_days": None}
    ]


def test_the_shipped_registry_serves_solana():
    shipped = get_address_indexers()

    assert list(shipped) == ["solana"]
    assert shipped["solana"].chain == "solana"


def test_an_indexer_is_given_the_address_and_nothing_else(client, indexers):
    """No credentials exist to hand over: the address is the whole input, and
    the preview writes nothing."""
    indexers["fakechain"] = FakeIndexer(answers=AddressHistory(transfers=(transfer(),)))
    account_id = wallet_account(client)

    preview = client.post("/api/address-imports/preview", json=request(account_id))

    assert preview.status_code == 200, preview.text
    assert indexers["fakechain"].asked == [ADDRESS]
    answered = preview.json()
    assert [entry["external_id"] for entry in answered["to_create"]] == ["sig-1:native"]
    assert [entry["type"] for entry in answered["to_create"]] == ["transfer_in"]
    assert client.get("/api/transactions").json() == []
    assert client.get("/api/instruments").json() == []


def test_the_preview_leads_with_the_indexers_own_warnings(client, indexers):
    indexers["fakechain"] = FakeIndexer(
        answers=AddressHistory(transfers=(transfer(),), warnings=("1 transaction looked odd.",))
    )

    preview = client.post("/api/address-imports/preview", json=request(wallet_account(client)))

    assert preview.json()["warnings"][0] == "1 transaction looked odd."


def test_a_commit_lands_transfers_and_fees_as_one_batch(client, indexers, db):
    """In and out as their own Transactions, the network fee the address
    paid as a fee leg in the chain's coin charged against the movement it
    enabled, and a fee that enabled nothing as a standalone fee."""
    token = instruments.create_crypto_token(
        db, symbol="TOK", name="Token", chain="fakechain", contract_address="TokMint"
    )
    indexers["fakechain"] = FakeIndexer(
        answers=AddressHistory(
            transfers=(
                transfer(),
                transfer(
                    external_id="sig-2:TokMint",
                    direction="out",
                    asset=ChainAsset(symbol="TOK", name="Token", contract_address="TokMint"),
                    quantity=Decimal("40"),
                    fee_quantity=Decimal("0.000005"),
                ),
            ),
            fees=(
                NormalizedNetworkFee(
                    external_id="sig-3:fee", occurred_at=NOON, quantity=Decimal("0.00001")
                ),
            ),
        )
    )
    account_id = wallet_account(client)

    committed = client.post("/api/address-imports", json=request(account_id))

    assert committed.status_code == 201, committed.text
    assert committed.json()["created"] == 3
    (batch,) = client.get("/api/import-batches").json()
    assert batch["source"] == f"fakechain:{ADDRESS}"
    assert batch["account_id"] == account_id
    by_type = {entry["type"]: entry for entry in client.get("/api/transactions").json()}
    assert sorted(by_type) == ["fee", "transfer_in", "transfer_out"]
    coin = next(
        i["id"] for i in client.get("/api/instruments").json() if i["symbol"] == COIN.symbol
    )
    sent = {leg["role"]: leg for leg in by_type["transfer_out"]["legs"]}
    assert (sent["out"]["instrument_id"], Decimal(sent["out"]["quantity"])) == (
        token,
        Decimal("40"),
    )
    assert (sent["fee"]["instrument_id"], Decimal(sent["fee"]["quantity"])) == (
        coin,
        Decimal("0.000005"),
    )
    (standalone,) = by_type["fee"]["legs"]
    assert (standalone["role"], Decimal(standalone["quantity"])) == ("fee", Decimal("0.00001"))


def test_reading_the_same_address_again_changes_nothing(client, indexers):
    indexers["fakechain"] = FakeIndexer(answers=AddressHistory(transfers=(transfer(),)))
    account_id = wallet_account(client)
    client.post("/api/address-imports", json=request(account_id))

    again = client.post("/api/address-imports", json=request(account_id))

    assert again.status_code == 201
    assert again.json() == {
        "batch_id": None,
        "created": 0,
        "duplicates": 1,
        "skipped": 0,
        "instruments_created": 0,
        "unpriced": [],
        "price_conditions": [],
    }
    assert len(client.get("/api/transactions").json()) == 1


def test_an_inflow_of_an_unknown_instrument_arrives_unacknowledged_and_mints_no_lot(
    client, indexers, db
):
    """The unsolicited inflow (ADR-0012): the chain states the token's
    identity, so the Instrument is created from it — exactly as the chain
    writes the contract — and waits in the inbox; nothing enters the cost
    basis until the Admin has looked."""
    indexers["fakechain"] = FakeIndexer(
        answers=AddressHistory(
            transfers=(
                transfer(
                    external_id="sig-9:dust", asset=UNKNOWN_TOKEN, quantity=Decimal("1000000")
                ),
            )
        )
    )
    account_id = wallet_account(client)

    preview = client.post("/api/address-imports/preview", json=request(account_id)).json()
    committed = client.post("/api/address-imports", json=request(account_id))

    assert preview["new_instruments"] == [{"kind": "token", "symbol": "DUST", "name": "Dust Token"}]
    assert committed.json()["instruments_created"] == 1
    (item,) = client.get("/api/inbox").json()
    assert item["symbol"] == "DUST"
    assert item["chain"] == "fakechain"
    assert item["contract_address"] == UNKNOWN_TOKEN.contract_address
    assert item["account_id"] == account_id
    assert item["unclassified_inflow_count"] == 1
    assert lots.fresh_lots(db) == []


def test_a_known_token_resolves_by_its_contract_whatever_it_is_called(client, indexers, db):
    """Identity is chain and contract (ADR-0010): the label the indexer
    knows the token by decides nothing."""
    known = instruments.create_crypto_token(
        db,
        symbol="REAL",
        name="The Real Name",
        chain="fakechain",
        contract_address=UNKNOWN_TOKEN.contract_address,
    )
    indexers["fakechain"] = FakeIndexer(
        answers=AddressHistory(transfers=(transfer(asset=UNKNOWN_TOKEN),))
    )

    committed = client.post("/api/address-imports", json=request(wallet_account(client)))

    assert committed.json()["instruments_created"] == 0
    (recorded,) = client.get("/api/transactions").json()
    assert [leg["instrument_id"] for leg in recorded["legs"]] == [known]


def test_a_second_address_may_not_write_into_the_same_account(client, indexers):
    """One authoritative source per Account: the address is part of the
    source, so another address previews but is refused at commit."""
    indexers["fakechain"] = FakeIndexer(answers=AddressHistory(transfers=(transfer(),)))
    account_id = wallet_account(client)
    client.post("/api/address-imports", json=request(account_id))

    other = client.post("/api/address-imports", json=request(account_id, address="0therAddr3ss"))

    assert other.status_code == 409
    assert f"fakechain:{ADDRESS}" in other.json()["detail"]


def test_what_is_not_an_address_is_refused_with_the_indexers_sentence(client, indexers):
    indexers["fakechain"] = FakeIndexer(rejects_with="That is not a Fakechain address.")

    refused = client.post("/api/address-imports/preview", json=request(wallet_account(client)))

    assert refused.status_code == 422
    assert refused.json()["detail"] == "That is not a Fakechain address."


def test_an_indexer_failure_is_the_chains_not_the_ledgers(client, indexers):
    indexers["fakechain"] = FakeIndexer(fails_with="Fakechain is rate-limiting.")
    account_id = wallet_account(client)

    preview = client.post("/api/address-imports/preview", json=request(account_id))
    commit = client.post("/api/address-imports", json=request(account_id))

    assert (preview.status_code, commit.status_code) == (502, 502)
    assert preview.json()["detail"] == "Fakechain is rate-limiting."
    assert client.get("/api/import-batches").json() == []


def test_an_unknown_chain_or_account_is_not_found(client, indexers):
    indexers["fakechain"] = FakeIndexer(answers=AddressHistory(transfers=(transfer(),)))
    account_id = wallet_account(client)

    no_chain = client.post(
        "/api/address-imports/preview", json=request(account_id, chain="nowhere")
    )
    no_account = client.post("/api/address-imports/preview", json=request(account_id + 999))

    assert no_chain.status_code == 404
    assert no_chain.json()["detail"] == "No indexer reads this chain."
    assert no_account.status_code == 404

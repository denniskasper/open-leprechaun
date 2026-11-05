"""Deployments (ADR-0032): a token its issuer mints natively on several
chains is one Instrument, and each chain's contract is a Deployment — an
identity of that Instrument, attached by the Admin.

The seam is the HTTP API over real Postgres.
"""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from open_leprechaun.repositories import platforms, transactions
from open_leprechaun.repositories.transactions import Leg

ETHEREUM_CONTRACT = "0x" + "a0" * 20
SOLANA_MINT = "SoLanaMintAddr3ssWithMixedCase111111111111"


def add_token(
    client: TestClient,
    *,
    symbol: str = "USDX",
    chain: str = "ethereum",
    contract_address: str = ETHEREUM_CONTRACT,
) -> int:
    added = client.post(
        "/api/instruments",
        json={
            "kind": "token",
            "symbol": symbol,
            "name": f"{symbol} Coin",
            "chain": chain,
            "contract_address": contract_address,
        },
    )
    assert added.status_code == 201, added.text
    return added.json()["id"]


NOON = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)


def wallet(db, name: str = "Phantom") -> int:
    platform = platforms.create_platform(db, name=name, kind="software_wallet")
    return platforms.create_account(db, platform, name="Main")


def inflow(db, account: int, instrument: int, quantity: str = "100") -> int:
    return transactions.create_transaction(
        db,
        type="transfer_in",
        occurred_at=NOON,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=instrument, role="in", quantity=Decimal(quantity))
        ],
    )


def settle_as_deployment_of(client: TestClient, newer: int, older: int):
    return client.post(f"/api/instruments/{newer}/deployment-of", json={"instrument_id": older})


def deployments_of(client: TestClient, instrument_id: int) -> list[dict]:
    (instrument,) = [i for i in client.get("/api/instruments").json() if i["id"] == instrument_id]
    return instrument["deployments"]


def test_a_token_is_listed_with_the_deployment_it_was_created_with(client, db):
    token = add_token(client)

    assert deployments_of(client, token) == [
        {"chain": "ethereum", "contract_address": ETHEREUM_CONTRACT}
    ]


def test_the_admin_attaches_a_deployment_on_another_chain(client, db):
    token = add_token(client)

    attached = client.post(
        f"/api/instruments/{token}/deployments",
        json={"chain": "Solana", "contract_address": SOLANA_MINT},
    )

    assert attached.status_code == 201, attached.text
    assert deployments_of(client, token) == [
        {"chain": "ethereum", "contract_address": ETHEREUM_CONTRACT},
        {"chain": "solana", "contract_address": SOLANA_MINT},
    ]


def test_a_contract_another_instrument_holds_is_refused_naming_it(client, db):
    token = add_token(client)
    add_token(client, symbol="USDS", chain="solana", contract_address=SOLANA_MINT)

    refused = client.post(
        f"/api/instruments/{token}/deployments",
        json={"chain": "solana", "contract_address": SOLANA_MINT},
    )

    assert refused.status_code == 409
    assert "USDS Coin (USDS) already holds this contract" in refused.json()["detail"]
    assert deployments_of(client, token) == [
        {"chain": "ethereum", "contract_address": ETHEREUM_CONTRACT}
    ]


def test_a_coin_has_no_deployments(client, db):
    coin = client.post(
        "/api/instruments",
        json={"kind": "native", "symbol": "FKE", "name": "Fakecoin", "chain": "fakechain"},
    ).json()["id"]

    refused = client.post(
        f"/api/instruments/{coin}/deployments",
        json={"chain": "solana", "contract_address": SOLANA_MINT},
    )

    assert refused.status_code == 409
    assert "Only a token has Deployments" in refused.json()["detail"]
    assert deployments_of(client, coin) == []


def test_a_deployment_of_nothing_is_not_found(client, db):
    missing = client.post(
        "/api/instruments/999999/deployments",
        json={"chain": "solana", "contract_address": SOLANA_MINT},
    )

    assert missing.status_code == 404


# --- Settling an unacknowledged token as a Deployment of another ------------


def test_an_unacknowledged_token_settles_as_a_deployment_of_another(client, db):
    """The wallet saw a contract the ledger had never met, so it arrived as
    its own Instrument. Settled as a Deployment of the token it is, its
    contract joins that token, its inflows wait under that token instead, and
    the newer Instrument is gone."""
    older = add_token(client)
    newer = add_token(client, symbol="USDX", chain="solana", contract_address=SOLANA_MINT)
    account = wallet(db)
    arrived = inflow(db, account, newer)

    settled = settle_as_deployment_of(client, newer, older)

    assert settled.status_code == 200, settled.text
    assert [i["id"] for i in client.get("/api/instruments").json()] == [older]
    assert deployments_of(client, older) == [
        {"chain": "ethereum", "contract_address": ETHEREUM_CONTRACT},
        {"chain": "solana", "contract_address": SOLANA_MINT},
    ]
    (recorded,) = client.get("/api/transactions").json()
    assert recorded["id"] == arrived
    assert [leg["instrument_id"] for leg in recorded["legs"]] == [older]
    (waiting,) = client.get("/api/inbox").json()
    assert (waiting["instrument_id"], waiting["account_id"]) == (older, account)


def test_a_token_with_a_stance_does_not_settle_as_a_deployment(client, db):
    """Once the Admin has decided anything about it, its inflows have been
    settled as something — folding it would rewrite that history."""
    older = add_token(client)
    newer = add_token(client, symbol="USDX", chain="solana", contract_address=SOLANA_MINT)
    account = wallet(db)
    inflow(db, account, newer)
    kept = client.put(
        f"/api/instruments/{newer}/stance", json={"stance": "kept", "account_id": account}
    )
    assert kept.status_code == 200, kept.text

    refused = settle_as_deployment_of(client, newer, older)

    assert refused.status_code == 409
    assert "only while nothing about it has been decided" in refused.json()["detail"]
    assert {i["id"] for i in client.get("/api/instruments").json()} == {older, newer}


def test_a_token_with_anything_but_inflows_does_not_settle_as_a_deployment(client, db):
    older = add_token(client)
    newer = add_token(client, symbol="USDX", chain="solana", contract_address=SOLANA_MINT)
    account = wallet(db)
    transactions.create_transaction(
        db,
        type="transfer_out",
        occurred_at=NOON,
        note=None,
        legs=[Leg(account_id=account, instrument_id=newer, role="out", quantity=Decimal("1"))],
    )

    refused = settle_as_deployment_of(client, newer, older)

    assert refused.status_code == 409
    assert "only while nothing about it has been decided" in refused.json()["detail"]


def test_only_a_token_settles_as_a_deployment_of_another_token(client, db):
    token = add_token(client)
    coin = client.post(
        "/api/instruments",
        json={"kind": "native", "symbol": "FKE", "name": "Fakecoin", "chain": "fakechain"},
    ).json()["id"]

    assert settle_as_deployment_of(client, token, coin).status_code == 409
    assert settle_as_deployment_of(client, coin, token).status_code == 409
    assert settle_as_deployment_of(client, token, token).status_code == 409
    assert settle_as_deployment_of(client, token, 999999).status_code == 404

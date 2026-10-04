"""One Depot holding coins beside securities, end to end (ticket 49): the
Bitpanda adapters sync both through one Connection into one Account, and
each position is taxed under the regime of its Instrument — the private sale
for a coin, capital income for a security — with nothing asked of the Account.

The seam is the HTTP API over real Postgres with the real adapters behind a
mock of the venue (see test_bitpanda_adapter), and each regime's one public
read — `section23.year_report` and `section20.year_report`.
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from open_leprechaun.adapters import get_venue_adapters
from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.repositories import instruments, stances
from open_leprechaun.services import section20, section23
from test_bitpanda_adapter import CREDENTIALS, only, venue


class NoRates:
    """The reference-rate port's fake: everything here settles in EUR."""

    def daily_rates(self, currency, start, end):
        return []


@pytest.fixture
def adapters() -> dict:
    return {}


@pytest.fixture
def client(db: Engine, adapters: dict) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_venue_adapters] = lambda: adapters
    with TestClient(app) as client:
        yield client


def depot(client, db, adapters, payloads=None):
    """The ledger as it stands before a first sync — the euro, the coins the
    Admin holds and the share as a share — a Bitpanda Depot, and a Connection
    whose two kinds are both paired with it. Answers (connection_id,
    account_id, instrument ids by symbol)."""
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    ids = {
        "EUR": eur,
        "BTC": instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin"),
        "ETH": instruments.create_native_coin(db, symbol="ETH", name="Ether", chain="ethereum"),
        "MSFT": instruments.create_security(
            db, symbol="MSFT", name="Microsoft", type="share", isin="US5949181045"
        ),
    }
    platform_id = client.post("/api/platforms", json={"name": "Bitpanda", "kind": "broker"}).json()[
        "id"
    ]
    client.put(f"/api/platforms/{platform_id}/withholding", json={"behaviour": "none"})
    account_id = client.post(
        f"/api/platforms/{platform_id}/accounts", json={"name": "Depot", "base_currency": "EUR"}
    ).json()["id"]
    for symbol in ("BTC", "ETH", "MSFT"):
        assert not isinstance(
            stances.classify(db, ids[symbol], stance="kept", account_id=account_id),
            stances.Refusal,
        )
    connection_id = client.post(
        "/api/connections",
        json=dict(platform_id=platform_id, venue="bitpanda", label="Depot", key=CREDENTIALS.key),
    ).json()["id"]
    for kind in ("spot", "securities"):
        paired = client.put(
            f"/api/connections/{connection_id}/pairings/{kind}", json={"account_id": account_id}
        )
        assert paired.status_code == 204
    spot, securities, _ = venue(payloads)
    adapters["bitpanda"] = (spot, securities)
    return connection_id, account_id, ids


def test_one_sync_lands_coins_and_securities_in_the_one_depot(client, db, adapters):
    connection_id, account_id, _ = depot(client, db, adapters)

    spot, securities = client.post(f"/api/connections/{connection_id}/sync").json()

    assert (spot["adapter_kind"], spot["ok"], spot["error"]) == ("spot", True, None)
    assert (securities["adapter_kind"], securities["ok"], securities["error"]) == (
        "securities",
        True,
        None,
    )
    # Three coin trades and a withdrawal; three security trades, a dividend,
    # interest, a deposit and a fee.
    assert spot["imported"]["created"] == 4
    assert securities["imported"]["created"] == 7
    assert len(securities["passed_over"]) == 2
    transactions = client.get("/api/transactions").json()
    assert {leg["account_id"] for t in transactions for leg in t["legs"]} == {account_id}
    by_source: dict[str, set[int]] = {}
    for transaction in transactions:
        by_source.setdefault(transaction["import_source"], set()).update(
            leg["instrument_id"] for leg in transaction["legs"]
        )
    listed = {row["id"]: row for row in client.get("/api/instruments").json()}
    assert {listed[i]["family"] for i in by_source["bitpanda:spot"]} == {"crypto", "cash"}
    assert {listed[i]["family"] for i in by_source["bitpanda:securities"]} == {"security", "cash"}
    # The fund the ledger had never seen arrived by its ISIN, flagged.
    (fund,) = [row for row in listed.values() if row["symbol"] == "SXR8"]
    assert fund["family"] == "security" and fund["needs_review"] is True


def test_syncing_the_depot_again_changes_nothing(client, db, adapters):
    connection_id, _, _ = depot(client, db, adapters)
    client.post(f"/api/connections/{connection_id}/sync")

    spot, securities = client.post(f"/api/connections/{connection_id}/sync").json()

    assert (spot["imported"]["created"], spot["imported"]["duplicates"]) == (0, 4)
    assert (securities["imported"]["created"], securities["imported"]["duplicates"]) == (0, 7)
    assert len(client.get("/api/transactions").json()) == 11


def test_each_position_is_taxed_under_its_instruments_regime(client, db, adapters):
    """A coin and a share bought and sold through the same Depot within the
    year: the coin's sale is a private sale and no capital income, the
    share's capital income and no private sale — the same Account, the same
    cash, the same sync."""
    # The deposit; a coin bought and part of it sold; a share bought, its
    # dividend, and half of it sold.
    connection_id, account_id, ids = depot(client, db, adapters, only(1, 2, 3, 10, 11, 12))
    client.post(f"/api/connections/{connection_id}/sync")

    private_sales = section23.year_report(db, NoRates(), year=2024)
    capital_income = section20.year_report(db, NoRates(), year=2024)

    (coin_sale,) = private_sales.disposals
    assert (coin_sale.instrument_id, coin_sale.account_id) == (ids["BTC"], account_id)
    # 0.004 of the 0.01 priced at 492.65, sold at 240.00. An exchange
    # trade's fee names no leg it was charged against, so — as for every
    # venue on that port — it enters neither the basis nor the proceeds.
    assert private_sales.total_gain_eur == Decimal("42.94")
    (share_sale,) = capital_income.disposals
    assert (share_sale.instrument_id, share_sale.account_id) == (ids["MSFT"], account_id)
    pots = {balance.category: balance for balance in capital_income.balances}
    # Half of the share that cost 401.00 with its fee, sold for 219.00 after
    # the fee.
    assert pots["aktien"].balance_eur == Decimal("18.50")
    (receipt,) = capital_income.receipts
    assert receipt.net_eur == Decimal("0.45")


def test_the_depot_is_reconciled_once_against_everything_it_holds(client, db, adapters):
    """The securities kind states the whole Depot, so coins, securities and
    cash are each compared once — and what was passed over shows as the gap
    it left."""
    connection_id, account_id, _ = depot(client, db, adapters)
    client.post(f"/api/connections/{connection_id}/sync")

    (reconciled,) = client.post(f"/api/connections/{connection_id}/reconcile").json()

    assert (reconciled["adapter_kind"], reconciled["account_id"]) == ("securities", account_id)
    lines = {line["symbol"]: line for line in reconciled["lines"]}
    assert (lines["BTC"]["family"], lines["BTC"]["status"]) == ("crypto", "matched")
    assert (lines["SXR8"]["family"], lines["SXR8"]["status"]) == ("security", "matched")
    # The venue's second listing of the paper is held beside the first.
    assert (lines["MSFT"]["live"], lines["MSFT"]["tracked"]) == ("0.75", "0.5")
    # The reward that was passed over is the coin the ledger does not have.
    assert (lines["ETH"]["status"], lines["ETH"]["difference"]) == ("gap", "0.0003")
    # The metal's purchase was passed over too, and the cash it took with it.
    assert (lines["EUR"]["status"], lines["EUR"]["difference"]) == ("gap", "-35.50")
    assert lines["XAU"]["status"] == "unresolved"

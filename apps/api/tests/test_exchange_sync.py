"""The exchange adapter port and the sync seam (ticket 35, ADR-0004,
ADR-0008): testing and syncing act on the Connection and report per adapter
kind, adapters are the only place a venue's API is known, and core code never
learns a venue's name.

The seam is the HTTP API over real Postgres with fakes of the adapter port —
no live venue is ever called. The fake stands in through the same dependency
the real registry serves, so what is under test is exactly what production
runs: credentials decrypted for the adapter, records routed to the futures
pipeline and the import framework, results recorded per kind.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from open_leprechaun.adapters import get_exchange_adapters
from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.ports import exchange as port
from open_leprechaun.repositories import instruments

KEY = "AJVqhlN2mUvg5rlIT4YDkbA1"
SECRET = "wJmoXjRk8pdFqe37cChM/2Zt5yUwbBHGSA=="
PASSPHRASE = "correct horse battery staple"


@pytest.fixture
def adapters() -> dict:
    """The adapter registry under test control — tests attach fakes per
    venue; the dict is read per request, so later edits take effect."""
    return {}


@pytest.fixture
def client(db: Engine, adapters: dict) -> Iterator[TestClient]:
    """The API bound to the migrated test database and the fake adapter
    registry."""
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_exchange_adapters] = lambda: adapters
    with TestClient(app) as client:
        yield client


def okx(client: TestClient, name: str = "OKX") -> int:
    return client.post("/api/platforms", json={"name": name, "kind": "exchange"}).json()["id"]


def account(client: TestClient, platform_id: int, name: str = "Trading") -> int:
    return client.post(f"/api/platforms/{platform_id}/accounts", json={"name": name}).json()["id"]


def connect(client: TestClient, platform_id: int, **overrides) -> int:
    request = dict(
        platform_id=platform_id,
        venue="okx",
        label="Main account",
        key=KEY,
        secret=SECRET,
        passphrase=PASSPHRASE,
    )
    request.update(overrides)
    return client.post("/api/connections", json=request).json()["id"]


def test_the_venue_registry_names_its_adapter_kinds(client):
    """The UI offers pairing per kind before anything has synced — the
    registry says which kinds a venue serves, empty until its adapters
    ship."""
    venues = {venue["venue"]: venue for venue in client.get("/api/connections/venues").json()}

    assert venues["pionex"]["adapter_kinds"] == ["futures"]
    assert venues["okx"]["adapter_kinds"] == ["spot", "futures"]
    assert venues["coinbase"]["adapter_kinds"] == []


# --- Account pairing: which Account each kind writes into (ADR-0004) ---


def test_pairing_names_the_account_a_kind_writes_into(client):
    """Account pairing is per adapter kind, stored on the Connection and
    answered with the overview."""
    platform_id = okx(client)
    account_id = account(client, platform_id)
    connection_id = connect(client, platform_id)

    paired = client.put(
        f"/api/connections/{connection_id}/pairings/futures", json={"account_id": account_id}
    )

    assert paired.status_code == 204
    (listed,) = client.get("/api/connections").json()
    assert listed["pairings"] == [{"adapter_kind": "futures", "account_id": account_id}]


def test_repairing_a_kind_replaces_the_account(client):
    """One Account per kind — pairing again moves the kind, it does not
    accumulate."""
    platform_id = okx(client)
    first = account(client, platform_id, name="Trading")
    second = account(client, platform_id, name="Bots")
    connection_id = connect(client, platform_id)
    client.put(f"/api/connections/{connection_id}/pairings/futures", json={"account_id": first})

    client.put(f"/api/connections/{connection_id}/pairings/futures", json={"account_id": second})

    (listed,) = client.get("/api/connections").json()
    assert listed["pairings"] == [{"adapter_kind": "futures", "account_id": second}]


def test_a_pairing_outside_the_connections_platform_is_refused(client):
    """A Connection's data lands under its own Platform — an Account under
    another Platform is a mispairing, named before anything is stored."""
    platform_id = okx(client)
    elsewhere = account(client, okx(client, name="Coinbase"), name="Foreign")
    connection_id = connect(client, platform_id)

    refused = client.put(
        f"/api/connections/{connection_id}/pairings/futures", json={"account_id": elsewhere}
    )

    assert refused.status_code == 422
    assert "Platform" in refused.json()["detail"]
    (listed,) = client.get("/api/connections").json()
    assert listed["pairings"] == []


def test_pairing_refusals_name_what_is_missing(client):
    platform_id = okx(client)
    account_id = account(client, platform_id)
    connection_id = connect(client, platform_id)

    no_connection = client.put(
        "/api/connections/12345/pairings/futures", json={"account_id": account_id}
    )
    no_account = client.put(
        f"/api/connections/{connection_id}/pairings/futures", json={"account_id": 12345}
    )

    assert no_connection.status_code == 404
    assert no_account.status_code == 404


class FakeAdapter:
    """A fake of the port: one kind, a scripted answer, and a record of the
    credentials it was handed."""

    def __init__(
        self, kind, *, harvest=None, detail="Authenticated.", failure=None, lookback_days=90
    ):
        self.kind = kind
        self.harvest = harvest or port.Harvest()
        self.detail = detail
        self.failure = failure
        self.lookback_days = lookback_days
        self.seen_credentials = []

    def _answer(self, credentials):
        self.seen_credentials.append(credentials)
        if self.failure is not None:
            raise port.AdapterError(self.failure)

    def test(self, credentials):
        self._answer(credentials)
        return self.detail

    def pull(self, credentials):
        self._answer(credentials)
        return self.harvest


# --- Testing a Connection: per-kind, one failing never hides another ---


def test_testing_reports_and_records_results_per_kind(client, adapters):
    """Both kinds answer — the working one its detail, the broken one its
    error — and the recorded statuses keep them apart (ADR-0004)."""
    platform_id = okx(client)
    connection_id = connect(client, platform_id)
    adapters["okx"] = (
        FakeAdapter("spot", detail="Authenticated — 3 balances visible."),
        FakeAdapter("futures", failure="The key does not open the futures API."),
    )

    tested = client.post(f"/api/connections/{connection_id}/test")

    assert tested.status_code == 200
    assert tested.json() == [
        {
            "adapter_kind": "spot",
            "ok": True,
            "detail": "Authenticated — 3 balances visible.",
            "error": None,
        },
        {
            "adapter_kind": "futures",
            "ok": False,
            "detail": None,
            "error": "The key does not open the futures API.",
        },
    ]
    (listed,) = client.get("/api/connections").json()
    recorded = {status["adapter_kind"]: status for status in listed["statuses"]}
    assert recorded["spot"]["last_success_at"] is not None
    assert recorded["spot"]["last_error"] is None
    assert recorded["futures"]["last_error"] == "The key does not open the futures API."


def test_testing_hands_the_adapter_what_the_admin_typed(client, adapters):
    """The credentials round-trip through encryption to the adapter, and
    using them stamps last_used_at."""
    platform_id = okx(client)
    connection_id = connect(client, platform_id)
    fake = FakeAdapter("futures")
    adapters["okx"] = (fake,)

    client.post(f"/api/connections/{connection_id}/test")

    (credentials,) = fake.seen_credentials
    assert (credentials.key, credentials.secret, credentials.passphrase) == (
        KEY,
        SECRET,
        PASSPHRASE,
    )
    (listed,) = client.get("/api/connections").json()
    assert listed["last_used_at"] is not None


def test_an_adapter_bug_is_one_kind_failing_not_a_crash(client, adapters):
    """An exception the adapter did not translate still answers as that
    kind's error — it must never hide the other kind succeeding. Its message
    promises nothing about secret material, so only the type is recorded."""

    class Broken(FakeAdapter):
        def test(self, credentials):
            raise ValueError(f"unexpected shape near {credentials.secret}")

    platform_id = okx(client)
    connection_id = connect(client, platform_id)
    adapters["okx"] = (Broken("spot"), FakeAdapter("futures"))

    tested = client.post(f"/api/connections/{connection_id}/test")

    assert tested.status_code == 200
    spot, futures = tested.json()
    assert spot["ok"] is False and "ValueError" in spot["error"]
    assert SECRET not in tested.text
    assert futures["ok"] is True


def test_testing_a_venue_without_adapters_answers_no_kinds(client, adapters):
    """A registered venue whose adapters have not shipped yet: nothing to
    test, honestly answered as an empty result rather than an error."""
    platform_id = okx(client)
    connection_id = connect(client, platform_id)

    tested = client.post(f"/api/connections/{connection_id}/test")

    assert tested.status_code == 200
    assert tested.json() == []


def test_testing_an_unknown_connection_says_so(client):
    assert client.post("/api/connections/12345/test").status_code == 404


# --- Syncing: fills and funding land in the futures pipeline ---


AN_INSTANT = datetime(2031, 3, 2, 10, 0, tzinfo=UTC)


def usdt(db):
    return instruments.create_crypto_token(
        db,
        symbol="USDT",
        name="Tether",
        chain="ethereum",
        contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7",
        pegged_currency="USD",
    )


def futures_harvest():
    """One round trip: open long, close at a profit, one funding payment —
    everything named in the venue's own symbols."""
    return port.Harvest(
        fills=(
            port.NormalizedFill(
                external_id="fill-1",
                occurred_at=AN_INSTANT,
                symbol="BTC_USDT_PERP",
                side="buy",
                price=Decimal("50000"),
                size=Decimal("2"),
                fee=Decimal("1"),
                settlement_symbol="USDT",
                inverse=False,
            ),
            port.NormalizedFill(
                external_id="fill-2",
                occurred_at=AN_INSTANT + timedelta(hours=2),
                symbol="BTC_USDT_PERP",
                side="sell",
                price=Decimal("51000"),
                size=Decimal("2"),
                fee=Decimal("1"),
                settlement_symbol="USDT",
                inverse=False,
            ),
        ),
        funding=(
            port.NormalizedFunding(
                external_id="BTC_USDT_PERP|1",
                occurred_at=AN_INSTANT + timedelta(hours=1),
                symbol="BTC_USDT_PERP",
                amount=Decimal("-0.5"),
                settlement_symbol="USDT",
            ),
        ),
    )


def paired_futures_connection(client, adapters, harvest=None):
    platform_id = okx(client)
    account_id = account(client, platform_id)
    connection_id = connect(client, platform_id)
    client.put(
        f"/api/connections/{connection_id}/pairings/futures", json={"account_id": account_id}
    )
    adapters["okx"] = (FakeAdapter("futures", harvest=harvest or futures_harvest()),)
    return connection_id, account_id


def test_a_futures_sync_lands_fills_and_funding_end_to_end(client, adapters, db):
    """Credentials in, normalized records out, a derived position in the
    overview — stamped with the per-kind provenance string, in the paired
    Account, its settlement resolved to the one Instrument wearing the
    symbol."""
    usdt(db)
    connection_id, account_id = paired_futures_connection(client, adapters)

    synced = client.post(f"/api/connections/{connection_id}/sync")

    assert synced.status_code == 200
    (result,) = synced.json()
    assert result["adapter_kind"] == "futures"
    assert result["ok"] is True
    assert result["futures"] == {"new_fills": 2, "new_funding": 1}
    assert result["imported"] is None

    overview = client.get("/api/futures").json()
    (position,) = overview["positions"]
    assert position["source"] == "okx:futures"
    assert position["account_id"] == account_id
    assert position["symbol"] == "BTC_USDT_PERP"
    assert position["closed_at"] is not None
    # 2 x 1000 profit - 2 fees - 0.5 funding paid, all in the settlement asset.
    assert Decimal(position["net"]) == Decimal("1997.5")


def test_syncing_again_stores_nothing_twice(client, adapters, db):
    """The dedupe key (source, external id) makes a re-sync change nothing."""
    usdt(db)
    connection_id, _ = paired_futures_connection(client, adapters)
    client.post(f"/api/connections/{connection_id}/sync")

    again = client.post(f"/api/connections/{connection_id}/sync")

    (result,) = again.json()
    assert result["ok"] is True
    assert result["futures"] == {"new_fills": 0, "new_funding": 0}
    assert len(client.get("/api/futures").json()["positions"]) == 1


def test_an_unpaired_kind_refuses_with_a_sentence(client, adapters, db):
    """Without a pairing the kind cannot know where records land — its own
    error, recorded per kind, while nothing is written."""
    usdt(db)
    platform_id = okx(client)
    connection_id = connect(client, platform_id)
    adapters["okx"] = (FakeAdapter("futures", harvest=futures_harvest()),)

    (result,) = client.post(f"/api/connections/{connection_id}/sync").json()

    assert result["ok"] is False
    assert "paired" in result["error"]
    assert client.get("/api/futures").json()["positions"] == []
    (listed,) = client.get("/api/connections").json()
    (status,) = listed["statuses"]
    assert status["last_error"] == result["error"]


def test_a_symbol_nothing_answers_to_refuses_the_kind(client, adapters):
    """No Instrument wears 'USDT' — the kind refuses with the symbol named,
    rather than minting an identity from a bare symbol."""
    connection_id, _ = paired_futures_connection(client, adapters)

    (result,) = client.post(f"/api/connections/{connection_id}/sync").json()

    assert result["ok"] is False
    assert "USDT" in result["error"]
    assert client.get("/api/futures").json()["positions"] == []


def test_a_symbol_two_instruments_wear_refuses_the_kind(client, adapters, db):
    """Two tokens legitimately share a ticker — the ledger cannot choose from
    a symbol alone, and says so instead of guessing (ADR-0010)."""
    usdt(db)
    instruments.create_crypto_token(
        db,
        symbol="USDT",
        name="Tether on Tron",
        chain="tron",
        contract_address="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
    )
    connection_id, _ = paired_futures_connection(client, adapters)

    (result,) = client.post(f"/api/connections/{connection_id}/sync").json()

    assert result["ok"] is False
    assert "several" in result["error"] and "USDT" in result["error"]
    assert client.get("/api/futures").json()["positions"] == []


def test_syncing_an_unknown_connection_says_so(client):
    assert client.post("/api/connections/12345/sync").status_code == 404


# --- Syncing: the result states the period the pull covered ---


def test_a_sync_reports_the_period_the_pull_covered(client, adapters, db):
    """The adapter declares how far back the venue reaches (ADR-0008); a
    successful pull answers that declaration with the result, so "nothing
    found" is never mistaken for "nothing exists"."""
    usdt(db)
    connection_id, _ = paired_futures_connection(client, adapters)

    (result,) = client.post(f"/api/connections/{connection_id}/sync").json()

    assert result["ok"] is True
    assert result["covered_days"] == 90


def test_a_sync_of_an_account_with_no_history_completes_cleanly(client, adapters):
    """An empty harvest is a clean outcome, not an error — and the period
    covered is still stated, because "nothing in 90 days" is the finding."""
    platform_id = okx(client)
    account_id = account(client, platform_id)
    connection_id = connect(client, platform_id)
    client.put(
        f"/api/connections/{connection_id}/pairings/futures", json={"account_id": account_id}
    )
    adapters["okx"] = (FakeAdapter("futures", harvest=port.Harvest()),)

    (result,) = client.post(f"/api/connections/{connection_id}/sync").json()

    assert result["ok"] is True
    assert result["error"] is None
    assert result["futures"] is None and result["imported"] is None
    assert result["covered_days"] == 90


def test_a_refused_commit_states_no_coverage(client, adapters, db):
    """The pull succeeded, the account refused — records did not all land,
    so the kind must not claim its period is covered (while the other kind,
    landing first, claims its own)."""
    spot_instruments(db)
    platform_id = okx(client)
    account_id = account(client, platform_id)
    connection_id = connect(client, platform_id)
    for kind in ("spot", "futures"):
        client.put(
            f"/api/connections/{connection_id}/pairings/{kind}", json={"account_id": account_id}
        )
    late_transfer = port.Harvest(
        transfers=(
            port.NormalizedTransfer(
                external_id="transfer-2",
                occurred_at=AN_INSTANT,
                direction="in",
                symbol="BTC",
                quantity=Decimal("1"),
            ),
        )
    )
    adapters["okx"] = (
        FakeAdapter("spot", harvest=spot_harvest()),
        FakeAdapter("futures", harvest=late_transfer),
    )

    spot, futures = client.post(f"/api/connections/{connection_id}/sync").json()

    assert spot["ok"] is True and spot["covered_days"] == 90
    assert futures["ok"] is False and "okx:spot" in futures["error"]
    assert futures["covered_days"] is None


def test_a_failed_pull_covers_no_period(client, adapters):
    """A kind that never pulled states no coverage — an error and a covered
    period would contradict each other."""
    platform_id = okx(client)
    account_id = account(client, platform_id)
    connection_id = connect(client, platform_id)
    client.put(
        f"/api/connections/{connection_id}/pairings/futures", json={"account_id": account_id}
    )
    adapters["okx"] = (FakeAdapter("futures", failure="The venue is down."),)

    (result,) = client.post(f"/api/connections/{connection_id}/sync").json()

    assert result["ok"] is False
    assert result["covered_days"] is None


# --- Syncing: trades, transfers and cash movements land in the ledger ---


def spot_harvest():
    """A buy, an inbound transfer and a fiat deposit — the three ledger-bound
    record shapes, named in the venue's own symbols."""
    return port.Harvest(
        trades=(
            port.NormalizedTrade(
                external_id="trade-1",
                occurred_at=AN_INSTANT,
                base_symbol="BTC",
                quote_symbol="USDT",
                side="buy",
                base_quantity=Decimal("0.5"),
                quote_quantity=Decimal("25000"),
                fee_symbol="USDT",
                fee_quantity=Decimal("25"),
            ),
        ),
        transfers=(
            port.NormalizedTransfer(
                external_id="transfer-1",
                occurred_at=AN_INSTANT + timedelta(hours=1),
                direction="in",
                symbol="BTC",
                quantity=Decimal("0.1"),
            ),
        ),
        cash_movements=(
            port.NormalizedCashMovement(
                external_id="deposit-1",
                occurred_at=AN_INSTANT + timedelta(hours=2),
                direction="in",
                currency="EUR",
                amount=Decimal("1000"),
            ),
        ),
    )


def spot_instruments(db):
    instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    usdt(db)
    instruments.create_cash(db, symbol="EUR", name="Euro")


def paired_spot_connection(client, adapters):
    platform_id = okx(client)
    account_id = account(client, platform_id)
    connection_id = connect(client, platform_id)
    client.put(f"/api/connections/{connection_id}/pairings/spot", json={"account_id": account_id})
    adapters["okx"] = (FakeAdapter("spot", harvest=spot_harvest()),)
    return connection_id, account_id


def test_a_spot_sync_lands_transactions_in_the_ledger(client, adapters, db):
    """Trades, transfers and cash movements arrive as balanced ledger
    Transactions through the import framework: one batch, provenance marked,
    in the paired Account."""
    spot_instruments(db)
    connection_id, account_id = paired_spot_connection(client, adapters)

    synced = client.post(f"/api/connections/{connection_id}/sync")

    (result,) = synced.json()
    assert result["ok"] is True
    assert result["futures"] is None
    assert result["imported"]["created"] == 3
    assert result["imported"]["duplicates"] == 0
    assert result["imported"]["batch_id"] is not None

    transactions = client.get("/api/transactions").json()
    assert {transaction["type"] for transaction in transactions} == {
        "trade",
        "transfer_in",
    }
    assert all(transaction["import_source"] == "okx:spot" for transaction in transactions)
    (trade,) = [t for t in transactions if t["type"] == "trade"]
    assert {leg["role"] for leg in trade["legs"]} == {"in", "out", "fee"}

    (batch,) = client.get("/api/import-batches").json()
    assert batch["source"] == "okx:spot"
    assert batch["account_id"] == account_id
    assert batch["rows"] == 3


def test_a_spot_re_sync_changes_nothing(client, adapters, db):
    """Every record is already registered — no batch, no rows, three
    duplicates. Re-running a sync is as idempotent as re-importing a file."""
    spot_instruments(db)
    connection_id, _ = paired_spot_connection(client, adapters)
    client.post(f"/api/connections/{connection_id}/sync")

    (result,) = client.post(f"/api/connections/{connection_id}/sync").json()

    assert result["ok"] is True
    assert result["imported"] == {
        "batch_id": None,
        "created": 0,
        "duplicates": 3,
        "skipped": 0,
    }
    assert len(client.get("/api/transactions").json()) == 3
    assert len(client.get("/api/import-batches").json()) == 1


def test_a_sync_claims_the_authoritative_source_for_its_account(client, adapters, db):
    """The first commit claims the Account (ticket 31) — a different source
    may preview but may not write there afterwards."""
    spot_instruments(db)
    connection_id, account_id = paired_spot_connection(client, adapters)
    client.post(f"/api/connections/{connection_id}/sync")

    refused = client.post(
        "/api/imports",
        json={
            "source": "csv:by-hand",
            "label": "statement.csv",
            "account_id": account_id,
            "rows": [],
        },
    )

    assert refused.status_code == 409
    assert "okx:spot" in refused.json()["detail"]


def test_one_kind_failing_never_hides_another_landing(client, adapters, db):
    """The venue serves two kinds; the broken one reports its error, the
    working one lands its records — in the same sync (ADR-0004)."""
    spot_instruments(db)
    platform_id = okx(client)
    account_id = account(client, platform_id)
    connection_id = connect(client, platform_id)
    for kind in ("spot", "futures"):
        client.put(
            f"/api/connections/{connection_id}/pairings/{kind}", json={"account_id": account_id}
        )
    adapters["okx"] = (
        FakeAdapter("spot", failure="The venue is down."),
        FakeAdapter("futures", harvest=futures_harvest()),
    )

    spot, futures = client.post(f"/api/connections/{connection_id}/sync").json()

    assert spot["ok"] is False and spot["error"] == "The venue is down."
    assert futures["ok"] is True
    assert futures["futures"] == {"new_fills": 2, "new_funding": 1}
    assert len(client.get("/api/futures").json()["positions"]) == 1


def test_unpairing_releases_the_kind(client):
    platform_id = okx(client)
    account_id = account(client, platform_id)
    connection_id = connect(client, platform_id)
    client.put(
        f"/api/connections/{connection_id}/pairings/futures", json={"account_id": account_id}
    )

    released = client.delete(f"/api/connections/{connection_id}/pairings/futures")

    assert released.status_code == 204
    (listed,) = client.get("/api/connections").json()
    assert listed["pairings"] == []
    assert client.delete(f"/api/connections/{connection_id}/pairings/futures").status_code == 404

"""History windows and coverage warnings (ticket 40, ADR-0008): a venue's
capped lookback must never let "no trades found" pass for "no trades exist".

The seam is the HTTP API over real Postgres with fakes of the adapter port.
A successful sync records how far back the venue's window reached; the
warnings endpoint compares each paired Account's coverage against the
earliest activity recorded elsewhere in the ledger and names the venue that
cannot reach far enough back.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from open_leprechaun.adapters import get_exchange_adapters
from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.ports import exchange as port
from open_leprechaun.repositories import instruments


@pytest.fixture
def adapters() -> dict:
    return {}


@pytest.fixture
def client(db: Engine, adapters: dict) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_exchange_adapters] = lambda: adapters
    with TestClient(app) as client:
        yield client


class FakeAdapter:
    """A fake of the port: one kind, a scripted harvest, a declared
    lookback."""

    def __init__(self, kind, *, harvest=None, failure=None, lookback_days=90):
        self.kind = kind
        self.harvest = harvest or port.Harvest()
        self.failure = failure
        self.lookback_days = lookback_days

    def test(self, credentials):
        return "Authenticated."

    def pull(self, credentials):
        if self.failure is not None:
            raise port.AdapterError(self.failure)
        return self.harvest


def platform(client: TestClient, name: str) -> int:
    return client.post("/api/platforms", json={"name": name, "kind": "exchange"}).json()["id"]


def account(client: TestClient, platform_id: int, name: str = "Trading") -> int:
    return client.post(f"/api/platforms/{platform_id}/accounts", json={"name": name}).json()["id"]


def paired_connection(
    client: TestClient, adapters: dict, *, venue: str = "okx", lookback_days: int | None = 90
) -> tuple[int, int]:
    """One Connection with a futures kind paired to a fresh Account, its fake
    adapter serving an empty harvest."""
    platform_id = platform(client, f"{venue} #{len(adapters)}")
    account_id = account(client, platform_id)
    connection_id = client.post(
        "/api/connections",
        json={
            "platform_id": platform_id,
            "venue": venue,
            "label": "Main account",
            "key": "AJVqhlN2mUvg5rlIT4YDkbA1",
            "secret": "wJmoXjRk8pdFqe37cChM/2Zt5yUwbBHGSA==",
            "passphrase": "correct horse battery staple",
        },
    ).json()["id"]
    client.put(
        f"/api/connections/{connection_id}/pairings/futures", json={"account_id": account_id}
    )
    adapters[venue] = (FakeAdapter("futures", lookback_days=lookback_days),)
    return connection_id, account_id


def eur(db: Engine) -> int:
    return instruments.create_cash(db, symbol="EUR", name="Euro")


def record_activity(client: TestClient, account_id: int, instrument_id: int, at: datetime) -> None:
    """One hand-recorded inbound transfer — the earliest activity an Account
    is known by."""
    recorded = client.post(
        "/api/transactions",
        json={
            "type": "transfer_in",
            "occurred_at": at.isoformat(),
            "legs": [
                {
                    "account_id": account_id,
                    "instrument_id": instrument_id,
                    "role": "in",
                    "quantity": "100",
                }
            ],
        },
    )
    assert recorded.status_code == 201


def test_a_venue_whose_window_starts_after_older_activity_elsewhere_warns(client, adapters, db):
    """Activity recorded years before the venue's 90-day window opened: the
    warning names the venue's Platform, its Connection and the paired
    Account, and states both instants."""
    cash = eur(db)
    elsewhere_platform = platform(client, "Coinbase")
    elsewhere_account = account(client, elsewhere_platform, name="Old wallet")
    long_ago = datetime(2024, 1, 3, 12, 0, tzinfo=UTC)
    record_activity(client, elsewhere_account, cash, long_ago)
    connection_id, account_id = paired_connection(client, adapters)

    client.post(f"/api/connections/{connection_id}/sync")
    warnings = client.get("/api/connections/coverage-warnings")

    assert warnings.status_code == 200
    (warning,) = warnings.json()
    assert warning["account_id"] == account_id
    assert warning["connection_id"] == connection_id
    assert warning["connection_label"] == "Main account"
    assert warning["venue"] == "okx"
    assert warning["platform_name"] == "okx #0"
    assert warning["earliest_elsewhere_at"] == "2024-01-03T12:00:00Z"
    coverage_starts = datetime.fromisoformat(warning["coverage_starts_at"])
    assert datetime.now(UTC) - timedelta(days=91) < coverage_starts
    assert coverage_starts < datetime.now(UTC) - timedelta(days=89)


def test_activity_the_window_still_reaches_warns_nothing(client, adapters, db):
    """Everything recorded elsewhere began inside the venue's 90 days — no
    gap to surface."""
    cash = eur(db)
    elsewhere = account(client, platform(client, "Coinbase"), name="Recent wallet")
    record_activity(client, elsewhere, cash, datetime.now(UTC) - timedelta(days=10))
    connection_id, _ = paired_connection(client, adapters)

    client.post(f"/api/connections/{connection_id}/sync")

    assert client.get("/api/connections/coverage-warnings").json() == []


def test_older_history_already_in_the_account_closes_the_gap(client, adapters, db):
    """The paired Account already holds records older than anything recorded
    elsewhere — imported history is coverage no matter what claimed it, so
    the venue's capped window is no longer a gap."""
    cash = eur(db)
    elsewhere = account(client, platform(client, "Coinbase"), name="Old wallet")
    record_activity(client, elsewhere, cash, datetime(2024, 1, 3, 12, 0, tzinfo=UTC))
    connection_id, account_id = paired_connection(client, adapters)
    record_activity(client, account_id, cash, datetime(2023, 6, 1, 12, 0, tzinfo=UTC))

    client.post(f"/api/connections/{connection_id}/sync")

    assert client.get("/api/connections/coverage-warnings").json() == []


def test_a_failed_sync_claims_no_coverage(client, adapters, db):
    """A kind that never pulled has covered nothing — no window is claimed,
    so no warning can rest on it."""
    cash = eur(db)
    elsewhere = account(client, platform(client, "Coinbase"), name="Old wallet")
    record_activity(client, elsewhere, cash, datetime(2024, 1, 3, 12, 0, tzinfo=UTC))
    connection_id, _ = paired_connection(client, adapters)
    adapters["okx"] = (FakeAdapter("futures", failure="The venue is down."),)

    client.post(f"/api/connections/{connection_id}/sync")

    assert client.get("/api/connections/coverage-warnings").json() == []


def test_a_test_alone_claims_no_coverage(client, adapters, db):
    """Proving a credential opens the venue pulls no history — only a sync
    claims a window."""
    cash = eur(db)
    elsewhere = account(client, platform(client, "Coinbase"), name="Old wallet")
    record_activity(client, elsewhere, cash, datetime(2024, 1, 3, 12, 0, tzinfo=UTC))
    connection_id, _ = paired_connection(client, adapters)

    client.post(f"/api/connections/{connection_id}/test")

    assert client.get("/api/connections/coverage-warnings").json() == []


def test_an_unbounded_venue_claims_all_history_and_never_warns(client, adapters, db):
    """A venue that serves its full history has no window to fall short —
    nothing to warn about, however old the activity elsewhere."""
    cash = eur(db)
    elsewhere = account(client, platform(client, "Coinbase"), name="Old wallet")
    record_activity(client, elsewhere, cash, datetime(2024, 1, 3, 12, 0, tzinfo=UTC))
    connection_id, _ = paired_connection(client, adapters, lookback_days=None)

    client.post(f"/api/connections/{connection_id}/sync")

    assert client.get("/api/connections/coverage-warnings").json() == []


def test_two_kinds_into_one_account_warn_once_at_the_most_limited_window(client, adapters, db):
    """Spot reaches 90 days, futures only 30 — full coverage of the Account
    begins where the most limited window does, stated as one warning rather
    than one per kind."""
    cash = eur(db)
    elsewhere = account(client, platform(client, "Coinbase"), name="Old wallet")
    record_activity(client, elsewhere, cash, datetime(2024, 1, 3, 12, 0, tzinfo=UTC))
    connection_id, account_id = paired_connection(client, adapters)
    client.put(f"/api/connections/{connection_id}/pairings/spot", json={"account_id": account_id})
    adapters["okx"] = (
        FakeAdapter("spot", lookback_days=90),
        FakeAdapter("futures", lookback_days=30),
    )

    client.post(f"/api/connections/{connection_id}/sync")

    (warning,) = client.get("/api/connections/coverage-warnings").json()
    coverage_starts = datetime.fromisoformat(warning["coverage_starts_at"])
    assert datetime.now(UTC) - timedelta(days=31) < coverage_starts
    assert coverage_starts < datetime.now(UTC) - timedelta(days=29)

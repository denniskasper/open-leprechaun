"""Reconciliation (ticket 39, ADR-0008): what a venue says is held compared
against what the transactions account for, the difference surfaced rather
than absorbed.

The seam is the HTTP API over real Postgres with fakes of the adapter port —
no live venue is ever called. A fake states Normalized Positions through the
same dependency the real registry serves; the tracked side is whatever the
ledger holds, recorded through the API like any other test's.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from open_leprechaun.adapters import get_exchange_adapters
from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.ports import exchange as port
from open_leprechaun.repositories import instruments
from open_leprechaun.settings import Settings, get_settings

AN_INSTANT = datetime(2031, 3, 2, 10, 0, tzinfo=UTC)
AS_OF = datetime(2031, 6, 1, 12, 0, tzinfo=UTC)


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


class FakeAdapter:
    """A fake of the port that states balances: one kind, scripted positions,
    and a harvest for the tests that sync first."""

    lookback_days = 90

    def __init__(self, kind, *, positions=(), harvest=None, failure=None):
        self.kind = kind
        self._positions = tuple(positions)
        self.harvest = harvest or port.Harvest()
        self.failure = failure

    def test(self, credentials):
        return "Authenticated."

    def pull(self, credentials):
        return self.harvest

    def normalized_positions(self, credentials):
        if self.failure is not None:
            raise port.AdapterError(self.failure)
        return self._positions


class SilentAdapter:
    """A kind whose venue states no balances — the port's base shape alone."""

    lookback_days = 90

    def __init__(self, kind):
        self.kind = kind

    def test(self, credentials):
        return "Authenticated."

    def pull(self, credentials):
        return port.Harvest()


def position(symbol, quantity):
    return port.NormalizedPosition(symbol=symbol, quantity=Decimal(quantity), as_of=AS_OF)


def paired_connection(client, kind="spot"):
    """A Connection whose one kind is paired with an Account under its own
    Platform. Answers (connection_id, account_id)."""
    platform_id = client.post("/api/platforms", json={"name": "OKX", "kind": "exchange"}).json()[
        "id"
    ]
    account_id = client.post(f"/api/platforms/{platform_id}/accounts", json={"name": "Trading"})
    account_id = account_id.json()["id"]
    connection_id = client.post(
        "/api/connections",
        json=dict(
            platform_id=platform_id,
            venue="okx",
            label="Main account",
            key="AJVqhlN2mUvg5rlIT4YDkbA1",
            secret="wJmoXjRk8pdFqe37cChM/2Zt5yUwbBHGSA==",
            passphrase="correct horse battery staple",
        ),
    ).json()["id"]
    client.put(f"/api/connections/{connection_id}/pairings/{kind}", json={"account_id": account_id})
    return connection_id, account_id


def bitcoin(db):
    return instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")


def euro(db):
    return instruments.create_cash(db, symbol="EUR", name="Euro")


def received(client, account_id, instrument_id, quantity):
    """An inbound transfer — the plainest way the ledger comes to track a
    balance."""
    created = client.post(
        "/api/transactions",
        json={
            "type": "transfer_in",
            "occurred_at": AN_INSTANT.isoformat(),
            "legs": [
                {
                    "account_id": account_id,
                    "instrument_id": instrument_id,
                    "role": "in",
                    "quantity": quantity,
                }
            ],
        },
    )
    assert created.status_code == 201, created.text


def reconcile(client, connection_id, **body):
    return client.post(f"/api/connections/{connection_id}/reconcile", json=body or None)


def test_reconciliation_reports_live_tracked_and_the_difference_per_instrument(
    client, adapters, db
):
    """The venue states more than the transactions account for: the line
    names the Instrument and says by how much — live less tracked."""
    btc = bitcoin(db)
    connection_id, account_id = paired_connection(client)
    received(client, account_id, btc, "0.6")
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "1.5")]),)

    reconciled = reconcile(client, connection_id)

    assert reconciled.status_code == 200
    (result,) = reconciled.json()
    assert result["adapter_kind"] == "spot"
    assert result["ok"] is True
    assert result["account_id"] == account_id
    (line,) = result["lines"]
    assert line["instrument_id"] == btc
    assert line["symbol"] == "BTC"
    assert (line["live"], line["tracked"], line["difference"]) == ("1.5", "0.6", "0.9")
    assert line["status"] == "gap"


def test_a_balance_the_ledger_tracks_and_the_venue_no_longer_shows_is_a_gap(client, adapters, db):
    """The venue's silence about an Instrument is a statement of zero — what
    the ledger still tracks there is unexplained, and reported as negative."""
    btc = bitcoin(db)
    connection_id, account_id = paired_connection(client)
    received(client, account_id, btc, "0.6")
    adapters["okx"] = (FakeAdapter("spot", positions=[]),)

    (result,) = reconcile(client, connection_id).json()

    (line,) = result["lines"]
    assert (line["live"], line["tracked"], line["difference"]) == ("0", "0.6", "-0.6")
    assert line["status"] == "gap"


def test_agreeing_balances_are_matched(client, adapters, db):
    btc = bitcoin(db)
    connection_id, account_id = paired_connection(client)
    received(client, account_id, btc, "0.6")
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "0.6")]),)

    (result,) = reconcile(client, connection_id).json()

    (line,) = result["lines"]
    assert Decimal(line["difference"]) == 0
    assert line["status"] == "matched"
    assert line["resolutions"] == []


def test_the_result_states_when_the_venue_said_so(client, adapters, db):
    bitcoin(db)
    connection_id, _ = paired_connection(client)
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "1")]),)

    (result,) = reconcile(client, connection_id).json()

    assert datetime.fromisoformat(result["as_of"]) == AS_OF


def test_balances_a_venue_states_in_several_places_are_summed(client, adapters, db):
    """One asset split across a venue's sub-accounts is one balance to the
    Account it reconciles against."""
    btc = bitcoin(db)
    connection_id, account_id = paired_connection(client)
    received(client, account_id, btc, "1")
    adapters["okx"] = (
        FakeAdapter("spot", positions=[position("BTC", "0.75"), position("BTC", "0.25")]),
    )

    (result,) = reconcile(client, connection_id).json()

    (line,) = result["lines"]
    assert Decimal(line["live"]) == 1
    assert line["status"] == "matched"


def test_an_asset_held_nowhere_is_not_a_line(client, adapters, db):
    """The venue lists an empty balance and the ledger tracks none — nothing
    to compare, so nothing to read past."""
    bitcoin(db)
    connection_id, _ = paired_connection(client)
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "0")]),)

    (result,) = reconcile(client, connection_id).json()

    assert result["ok"] is True
    assert result["lines"] == []


# --- The tolerance is configurable ---


def test_the_configured_tolerance_forgives_rounding_and_nothing_more(client, adapters, db):
    """Out of the box one unit of the eighth decimal place is venue rounding;
    two is a difference."""
    btc = bitcoin(db)
    connection_id, account_id = paired_connection(client)
    received(client, account_id, btc, "0.6")
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "0.60000001")]),)

    (rounding,) = reconcile(client, connection_id).json()
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "0.60000002")]),)
    (beyond,) = reconcile(client, connection_id).json()

    assert rounding["tolerance"] == "0.00000001"
    assert rounding["lines"][0]["status"] == "matched"
    # A matched line still states the difference it forgave.
    assert rounding["lines"][0]["difference"] == "0.00000001"
    assert beyond["lines"][0]["status"] == "gap"


def test_a_run_may_state_its_own_tolerance(client, adapters, db):
    btc = bitcoin(db)
    connection_id, account_id = paired_connection(client)
    received(client, account_id, btc, "0.6")
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "1.0")]),)

    (loose,) = reconcile(client, connection_id, tolerance="0.4").json()
    (strict,) = reconcile(client, connection_id, tolerance="0.39").json()

    assert loose["tolerance"] == "0.4"
    assert loose["lines"][0]["status"] == "matched"
    assert strict["lines"][0]["status"] == "gap"


def test_a_zero_tolerance_reports_every_difference(client, adapters, db):
    btc = bitcoin(db)
    connection_id, account_id = paired_connection(client)
    received(client, account_id, btc, "0.6")
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "0.60000001")]),)

    (result,) = reconcile(client, connection_id, tolerance="0").json()

    assert result["lines"][0]["status"] == "gap"


def test_a_negative_tolerance_is_refused(client, adapters, db):
    connection_id, _ = paired_connection(client)
    adapters["okx"] = (FakeAdapter("spot"),)

    assert reconcile(client, connection_id, tolerance="-1").status_code == 422


def test_the_deployment_configures_the_tolerance_a_run_inherits(db, adapters):
    """RECONCILIATION_TOLERANCE is the standing configuration; a run that
    states nothing reconciles under it."""
    configured = get_settings().model_copy(update={"reconciliation_tolerance": Decimal("0.5")})
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_exchange_adapters] = lambda: adapters
    app.dependency_overrides[get_settings] = lambda: configured
    with TestClient(app) as client:
        btc = bitcoin(db)
        connection_id, account_id = paired_connection(client)
        received(client, account_id, btc, "0.6")
        adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "1.0")]),)

        (result,) = reconcile(client, connection_id).json()

    assert result["tolerance"] == "0.5"
    assert result["lines"][0]["status"] == "matched"


def test_the_tolerance_setting_reads_from_the_environment(monkeypatch):
    monkeypatch.setenv("RECONCILIATION_TOLERANCE", "0.001")

    assert Settings().reconciliation_tolerance == Decimal("0.001")


# --- A gap is reported, never filled ---


def test_a_gap_is_reported_and_never_auto_filled(client, adapters, db):
    """Reconciling writes nothing: no transaction appears, the holding stays
    what the transactions made it, and the same gap answers next time — no
    cost basis was invented to close it."""
    btc = bitcoin(db)
    connection_id, account_id = paired_connection(client)
    received(client, account_id, btc, "0.6")
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "1.5")]),)
    transactions_before = client.get("/api/transactions").json()

    reconcile(client, connection_id)
    (again,) = reconcile(client, connection_id).json()

    assert client.get("/api/transactions").json() == transactions_before
    (held,) = client.get("/api/holdings").json()["positions"]
    assert held["quantity"] == "0.6"
    assert again["lines"][0]["difference"] == "0.9"


def test_synced_positions_never_become_transactions(client, adapters, db):
    """A kind that states positions is synced: what it says is held lands
    nowhere — positions feed reconciliation only, never the ledger, so a
    snapshot cannot become a phantom cost basis."""
    bitcoin(db)
    connection_id, _ = paired_connection(client)
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "1.5")]),)

    (synced,) = client.post(f"/api/connections/{connection_id}/sync").json()

    assert synced["ok"] is True
    assert synced["imported"] is None
    assert client.get("/api/transactions").json() == []
    assert client.get("/api/holdings").json()["positions"] == []


# --- Each gap offers the two honest resolutions ---


def test_a_gap_offers_importing_history_or_an_opening_balance(client, adapters, db):
    """The venue holds more than the transactions account for: either the
    history that explains it is imported, or the Admin records an Opening
    Balance — whose own declaration marks the uncertainty (ticket 15)."""
    btc = bitcoin(db)
    connection_id, account_id = paired_connection(client)
    received(client, account_id, btc, "0.6")
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "1.5")]),)

    (result,) = reconcile(client, connection_id).json()

    assert result["lines"][0]["resolutions"] == ["import_history", "opening_balance"]


def test_an_opening_balance_is_not_offered_to_explain_quantity_away(client, adapters, db):
    """The ledger tracks more than the venue shows: an Opening Balance only
    ever adds a position, so the one honest resolution is the missing
    history."""
    btc = bitcoin(db)
    connection_id, account_id = paired_connection(client)
    received(client, account_id, btc, "0.6")
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "0.1")]),)

    (result,) = reconcile(client, connection_id).json()

    assert result["lines"][0]["resolutions"] == ["import_history"]


def test_recording_the_offered_opening_balance_closes_the_gap(client, adapters, db):
    """The resolution is the Admin's act through the ledger's own door: an
    Opening Balance for the difference, its reconstruction declared, and the
    next reconciliation matches."""
    btc = bitcoin(db)
    connection_id, account_id = paired_connection(client)
    received(client, account_id, btc, "0.6")
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "1.5")]),)
    (before,) = reconcile(client, connection_id).json()

    recorded = client.post(
        "/api/transactions",
        json={
            "type": "opening_balance",
            "occurred_at": AN_INSTANT.isoformat(),
            "reconstructed": "basis_and_date",
            "estimated_basis_eur": "0",
            "legs": [
                {
                    "account_id": account_id,
                    "instrument_id": btc,
                    "role": "in",
                    "quantity": before["lines"][0]["difference"],
                }
            ],
        },
    )

    assert recorded.status_code == 201, recorded.text
    (after,) = reconcile(client, connection_id).json()
    assert after["lines"][0]["status"] == "matched"


# --- Crypto balances and cash alike ---


def test_cash_reconciles_like_any_other_instrument(client, adapters, db):
    """Cash is an Instrument (ADR-0011): a fiat balance at the venue compares
    against the tracked cash position with no special case."""
    eur = euro(db)
    btc = bitcoin(db)
    connection_id, account_id = paired_connection(client)
    received(client, account_id, eur, "1000")
    received(client, account_id, btc, "0.6")
    adapters["okx"] = (
        FakeAdapter("spot", positions=[position("EUR", "750.50"), position("BTC", "0.6")]),
    )

    (result,) = reconcile(client, connection_id).json()

    crypto, cash = result["lines"]
    assert (crypto["symbol"], crypto["family"], crypto["status"]) == ("BTC", "crypto", "matched")
    assert (cash["symbol"], cash["family"]) == ("EUR", "cash")
    assert (cash["live"], cash["tracked"], cash["difference"]) == ("750.50", "1000", "-249.50")
    assert cash["status"] == "gap"


# --- A second source reconciles without writing ---


def test_a_non_authoritative_source_reconciles_without_writing(client, adapters, db):
    """Another source is authoritative for the Account, so this Connection
    may not write there (ADR-0008) — its sync is refused — yet it still
    reconciles against it, and the declaration and the ledger stay exactly
    as they were."""
    btc = bitcoin(db)
    connection_id, account_id = paired_connection(client)
    received(client, account_id, btc, "0.6")
    client.put(f"/api/accounts/{account_id}/authoritative-source", json={"source": "ledger_live"})
    harvest = port.Harvest(
        transfers=(
            port.NormalizedTransfer(
                external_id="transfer-1",
                occurred_at=AN_INSTANT,
                direction="in",
                symbol="BTC",
                quantity=Decimal("0.9"),
            ),
        )
    )
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "1.5")], harvest=harvest),)
    transactions_before = client.get("/api/transactions").json()

    (synced,) = client.post(f"/api/connections/{connection_id}/sync").json()
    (result,) = reconcile(client, connection_id).json()

    assert synced["ok"] is False and "ledger_live" in synced["error"]
    assert result["ok"] is True
    assert result["lines"][0]["difference"] == "0.9"
    assert client.get("/api/transactions").json() == transactions_before
    (platform,) = client.get("/api/platforms").json()
    (account,) = platform["accounts"]
    assert account["authoritative_source"] == "ledger_live"


def test_reconciling_claims_no_authority_over_an_undeclared_account(client, adapters, db):
    """A first committed import declares itself authoritative; a
    reconciliation is not an import and declares nothing."""
    bitcoin(db)
    connection_id, _ = paired_connection(client)
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "1.5")]),)

    reconcile(client, connection_id)

    (platform,) = client.get("/api/platforms").json()
    assert platform["accounts"][0]["authoritative_source"] is None


# --- Symbols are hints, never identities (ADR-0010) ---


def test_a_balance_no_instrument_answers_to_is_reported_unresolved(client, adapters, db):
    """The venue holds something the ledger has no Instrument for: the line
    says so with the symbol named — nothing is minted from a bare symbol, and
    the lines that do resolve are still compared."""
    btc = bitcoin(db)
    connection_id, account_id = paired_connection(client)
    received(client, account_id, btc, "0.6")
    adapters["okx"] = (
        FakeAdapter("spot", positions=[position("BTC", "0.6"), position("DOGE", "42")]),
    )

    (result,) = reconcile(client, connection_id).json()

    resolved, unresolved = result["lines"]
    assert resolved["status"] == "matched"
    assert unresolved["status"] == "unresolved"
    assert unresolved["instrument_id"] is None
    assert unresolved["live"] == "42"
    assert unresolved["tracked"] is None and unresolved["difference"] is None
    assert "DOGE" in unresolved["detail"]
    assert unresolved["resolutions"] == []
    assert [instrument["id"] for instrument in client.get("/api/instruments").json()] == [btc]


def test_dust_in_an_unknown_symbol_is_within_tolerance_too(client, adapters, db):
    """Nothing tracked could answer an unresolved symbol, so its whole
    balance is the difference — and the tolerance judges it like any other."""
    connection_id, _ = paired_connection(client)
    adapters["okx"] = (FakeAdapter("spot", positions=[position("DOGE", "0.004")]),)

    (forgiven,) = reconcile(client, connection_id, tolerance="0.01").json()
    (reported,) = reconcile(client, connection_id, tolerance="0.001").json()

    assert forgiven["lines"] == []
    assert reported["lines"][0]["status"] == "unresolved"


def tether_twice(db):
    ethereum = instruments.create_crypto_token(
        db,
        symbol="USDT",
        name="Tether",
        chain="ethereum",
        contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7",
        pegged_currency="USD",
    )
    tron = instruments.create_crypto_token(
        db,
        symbol="USDT",
        name="Tether on Tron",
        chain="tron",
        contract_address="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
    )
    return ethereum, tron


def test_a_shared_symbol_resolves_to_the_instrument_the_account_tracks(client, adapters, db):
    """Two tokens share a ticker; the transactions in this Account already
    said which one is held here, so that one answers."""
    _, tron = tether_twice(db)
    connection_id, account_id = paired_connection(client)
    received(client, account_id, tron, "100")
    adapters["okx"] = (FakeAdapter("spot", positions=[position("USDT", "100")]),)

    (result,) = reconcile(client, connection_id).json()

    (line,) = result["lines"]
    assert (line["instrument_id"], line["status"]) == (tron, "matched")


def test_a_shared_symbol_the_account_cannot_settle_stays_unresolved(client, adapters, db):
    """Two tokens share a ticker and this Account tracks neither — the
    ledger cannot choose from a symbol alone, and says so."""
    tether_twice(db)
    connection_id, _ = paired_connection(client)
    adapters["okx"] = (FakeAdapter("spot", positions=[position("USDT", "100")]),)

    (result,) = reconcile(client, connection_id).json()

    (line,) = result["lines"]
    assert line["status"] == "unresolved"
    assert "several" in line["detail"] and "USDT" in line["detail"]


# --- Per Connection, per kind (ADR-0004) ---


def test_one_kind_failing_never_hides_another_reconciling(client, adapters, db):
    btc = bitcoin(db)
    connection_id, account_id = paired_connection(client)
    client.put(f"/api/connections/{connection_id}/pairings/margin", json={"account_id": account_id})
    received(client, account_id, btc, "0.6")
    adapters["okx"] = (
        FakeAdapter("margin", failure="The key does not open the balance API."),
        FakeAdapter("spot", positions=[position("BTC", "0.6")]),
    )

    margin, spot = reconcile(client, connection_id).json()

    assert margin["adapter_kind"] == "margin"
    assert margin["ok"] is False
    assert margin["error"] == "The key does not open the balance API."
    assert margin["lines"] == []
    assert spot["ok"] is True and spot["lines"][0]["status"] == "matched"


def test_an_adapter_bug_is_one_kind_failing_with_its_message_withheld(client, adapters, db):
    """An exception the adapter did not translate promises nothing about
    secret material (ADR-0003) — only its type is answered."""

    class Broken(FakeAdapter):
        def normalized_positions(self, credentials):
            raise ValueError(f"unexpected shape near {credentials.secret}")

    connection_id, _ = paired_connection(client)
    adapters["okx"] = (Broken("spot"),)

    reconciled = reconcile(client, connection_id)

    (result,) = reconciled.json()
    assert result["ok"] is False and "ValueError" in result["error"]
    assert "wJmoXjRk8pdFqe37cChM" not in reconciled.text


def test_an_unpaired_kind_refuses_with_a_sentence(client, adapters, db):
    """Without a pairing there is no Account to compare against."""
    connection_id, _ = paired_connection(client, kind="futures")
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "1")]),)

    (result,) = reconcile(client, connection_id).json()

    assert result["ok"] is False
    assert "paired" in result["error"]
    assert result["account_id"] is None


def test_a_kind_that_states_no_positions_is_passed_by(client, adapters, db):
    """Stating what is held is a capability a kind declares by having it —
    one without it has nothing to reconcile and answers nothing."""
    connection_id, _ = paired_connection(client)
    adapters["okx"] = (SilentAdapter("spot"),)

    reconciled = reconcile(client, connection_id)

    assert reconciled.status_code == 200
    assert reconciled.json() == []


def test_reconciling_an_unknown_connection_says_so(client):
    assert reconcile(client, 12345).status_code == 404


def test_reconciliation_leaves_the_recorded_sync_results_alone(client, adapters, db):
    """The per-kind status is what testing and syncing recorded — a
    reconciliation neither clears a sync's error nor claims a success."""
    connection_id, _ = paired_connection(client)
    adapters["okx"] = (FakeAdapter("spot", positions=[position("BTC", "1")]),)

    reconcile(client, connection_id)

    (listed,) = client.get("/api/connections").json()
    assert listed["statuses"] == []

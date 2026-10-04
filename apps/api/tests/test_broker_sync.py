"""The broker adapter port and its sync seam (ticket 48, ADR-0008,
ADR-0025): a broker's trades, dividends, cash movements and fees land as
Transactions through the import framework, and its positions reach
Reconciliation alone.

The seam is the HTTP API over real Postgres with a fake of the broker port —
no live venue is ever called. The fake stands in through the same dependency
the real registry serves, so what is under test is exactly what production
runs.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from open_leprechaun.adapters import get_venue_adapters
from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.ports import broker as port
from open_leprechaun.ports import exchange as exchange_port
from open_leprechaun.repositories import instruments

BOUGHT_AT = datetime(2031, 3, 4, 14, 31, 7, tzinfo=UTC)
PAID_AT = datetime(2031, 5, 16, 11, 20, tzinfo=UTC)
PULLED_AT = datetime(2031, 6, 2, 12, 0, tzinfo=UTC)

APPLE = port.NormalizedSecurity(isin="US0378331005", symbol="AAPL", name="Apple")


@pytest.fixture
def adapters() -> dict:
    """The adapter registry under test control — tests attach fakes per
    venue; the dict is read per request, so later edits take effect."""
    return {}


@pytest.fixture
def client(db: Engine, adapters: dict) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_venue_adapters] = lambda: adapters
    with TestClient(app) as client:
        yield client


class FakeBroker:
    """A fake of the broker port: one kind, a scripted harvest and scripted
    positions."""

    kind = "securities"

    def __init__(self, *, harvest=None, positions=(), lookback_days=None):
        self.harvest = harvest or port.BrokerHarvest(covered=port.CoveredPeriod(None, PULLED_AT))
        self.positions = tuple(positions)
        self.lookback_days = lookback_days

    def test(self, credentials):
        return "Authenticated."

    def pull(self, credentials):
        return self.harvest

    def normalized_positions(self, credentials):
        return self.positions


def harvest(**records) -> port.BrokerHarvest:
    return port.BrokerHarvest(covered=port.CoveredPeriod(None, PULLED_AT), **records)


def a_purchase(**overrides) -> port.NormalizedSecurityTrade:
    """Two shares priced in dollars, settled in euros, the conversion fee
    stated apart."""
    fields = dict(
        external_id="fill-1",
        occurred_at=BOUGHT_AT,
        security=APPLE,
        side="buy",
        quantity=Decimal("2"),
        settled_amount=Decimal("333.33"),
        settlement_currency="EUR",
        original=port.NormalizedOriginalAmount(
            amount=Decimal("360.00"), currency="USD", fx_rate=Decimal("1.08")
        ),
        fees=(
            port.NormalizedFee("STAMP_DUTY", Decimal("1.20"), "EUR", "security"),
            port.NormalizedFee("CURRENCY_CONVERSION_FEE", Decimal("0.50"), "EUR", "cash"),
        ),
    )
    fields.update(overrides)
    return port.NormalizedSecurityTrade(**fields)


def a_deposit(amount="1000") -> port.NormalizedCashMovement:
    return port.NormalizedCashMovement(
        external_id="transaction-1",
        occurred_at=datetime(2031, 3, 1, 8, 30, tzinfo=UTC),
        direction="in",
        currency="EUR",
        amount=Decimal(amount),
    )


def depot(client, *, withholding="none"):
    """A broker Platform with its withholding behaviour set, one Depot under
    it and a Connection whose securities kind is paired with that Depot.
    Answers (connection_id, account_id)."""
    platform_id = client.post(
        "/api/platforms", json={"name": "Trading 212", "kind": "broker"}
    ).json()["id"]
    if withholding is not None:
        client.put(f"/api/platforms/{platform_id}/withholding", json={"behaviour": withholding})
    account_id = client.post(
        f"/api/platforms/{platform_id}/accounts", json={"name": "Invest", "base_currency": "EUR"}
    ).json()["id"]
    connection_id = client.post(
        "/api/connections",
        json=dict(
            platform_id=platform_id,
            venue="trading_212",
            label="Invest",
            key="the-key",
            secret="the-secret",
        ),
    ).json()["id"]
    client.put(
        f"/api/connections/{connection_id}/pairings/securities", json={"account_id": account_id}
    )
    return connection_id, account_id


def sync(client, connection_id) -> dict:
    synced = client.post(f"/api/connections/{connection_id}/sync")
    assert synced.status_code == 200
    (result,) = synced.json()
    return result


def instruments_by_symbol(client) -> dict:
    return {row["symbol"]: row for row in client.get("/api/instruments").json()}


def legs_of(client, transaction) -> list[tuple]:
    symbols = {row["id"]: row["symbol"] for row in client.get("/api/instruments").json()}
    by_id = {leg["id"]: leg for leg in transaction["legs"]}
    return [
        (
            leg["role"],
            symbols[leg["instrument_id"]],
            leg["quantity"],
            symbols[by_id[leg["charged_against_leg_id"]]["instrument_id"]]
            if leg["charged_against_leg_id"]
            else None,
        )
        for leg in transaction["legs"]
    ]


# --- Trades ---


def test_a_purchase_lands_as_the_security_in_and_the_settled_cash_out(client, adapters):
    """The Depot's cash stays true: what left is what the broker debited for
    the security, in the currency it settled in."""
    connection_id, account_id = depot(client)
    adapters["trading_212"] = (FakeBroker(harvest=harvest(trades=(a_purchase(fees=()),))),)

    result = sync(client, connection_id)

    assert result["ok"] is True and result["imported"]["created"] == 1
    (transaction,) = client.get("/api/transactions").json()
    assert transaction["type"] == "trade"
    assert transaction["import_source"] == "trading_212:securities"
    assert legs_of(client, transaction) == [
        ("in", "AAPL", "2", None),
        ("out", "EUR", "333.33", None),
    ]
    assert {leg["account_id"] for leg in transaction["legs"]} == {account_id}


def test_a_foreign_currency_trade_stores_its_original_amount_rate_and_rate_date(client, adapters):
    """The original amount and currency stand beside the EUR amount, with
    the rate the broker applied and the date that rate is of."""
    connection_id, _ = depot(client)
    adapters["trading_212"] = (FakeBroker(harvest=harvest(trades=(a_purchase(),))),)

    sync(client, connection_id)

    (transaction,) = client.get("/api/transactions").json()
    assert transaction["original_amount"] == {
        "amount": "360.00",
        "currency": "USD",
        "rate": "1.08",
        "rate_date": "2031-03-04",
    }


def test_a_trade_priced_in_its_settlement_currency_states_no_original_amount(client, adapters):
    connection_id, _ = depot(client)
    plain = a_purchase(original=None, fees=())
    adapters["trading_212"] = (FakeBroker(harvest=harvest(trades=(plain,))),)

    sync(client, connection_id)

    (transaction,) = client.get("/api/transactions").json()
    assert transaction["original_amount"] is None


def test_a_conversion_fee_attaches_to_the_cash_leg_and_a_trade_cost_to_the_security(
    client, adapters
):
    """Each fee attaches to the leg it was charged against, and so inherits
    that leg's regime: the conversion fee is a cost of the cash, the stamp
    duty a cost of acquiring the security."""
    connection_id, _ = depot(client)
    adapters["trading_212"] = (FakeBroker(harvest=harvest(trades=(a_purchase(),))),)

    sync(client, connection_id)

    (transaction,) = client.get("/api/transactions").json()
    assert legs_of(client, transaction) == [
        ("in", "AAPL", "2", None),
        ("out", "EUR", "333.33", None),
        ("fee", "EUR", "1.20", "AAPL"),
        ("fee", "EUR", "0.50", "EUR"),
    ]


def test_a_sales_fees_attach_the_same_way_round(client, adapters):
    connection_id, _ = depot(client)
    sale = a_purchase(external_id="fill-2", side="sell")
    adapters["trading_212"] = (FakeBroker(harvest=harvest(trades=(a_purchase(), sale))),)

    sync(client, connection_id)

    sold = [
        row
        for row in client.get("/api/transactions").json()
        if legs_of(client, row)[0] == ("in", "EUR", "333.33", None)
    ]
    assert [legs_of(client, row) for row in sold] == [
        [
            ("in", "EUR", "333.33", None),
            ("out", "AAPL", "2", None),
            ("fee", "EUR", "1.20", "AAPL"),
            ("fee", "EUR", "0.50", "EUR"),
        ]
    ]


def test_a_security_the_ledger_never_saw_arrives_flagged_for_review(client, adapters):
    """A broker names a security by its ISIN — the ledger's own identity for
    it — so an unknown one is minted flagged rather than refusing the sync."""
    connection_id, _ = depot(client)
    adapters["trading_212"] = (FakeBroker(harvest=harvest(trades=(a_purchase(),))),)

    sync(client, connection_id)

    apple = instruments_by_symbol(client)["AAPL"]
    assert (apple["family"], apple["isin"], apple["needs_review"]) == (
        "security",
        "US0378331005",
        True,
    )


def test_a_known_security_is_resolved_by_its_isin_whatever_the_venue_calls_it(client, adapters):
    connection_id, _ = depot(client)
    known = client.post(
        "/api/securities",
        json={"isin": "US0378331005", "symbol": "APC", "name": "Apple Inc.", "type": "share"},
    )
    assert known.status_code == 201
    adapters["trading_212"] = (FakeBroker(harvest=harvest(trades=(a_purchase(),))),)

    sync(client, connection_id)

    (transaction,) = client.get("/api/transactions").json()
    assert legs_of(client, transaction)[0] == ("in", "APC", "2", None)
    assert "AAPL" not in instruments_by_symbol(client)


# --- Dividends, cash movements, fees ---


def test_a_dividend_lands_net_naming_the_security_that_paid(client, adapters):
    connection_id, _ = depot(client)
    dividend = port.NormalizedDividend(
        external_id="dividend-1",
        occurred_at=PAID_AT,
        kind="dividend",
        amount=Decimal("0.39"),
        currency="EUR",
        security=APPLE,
        gross_amount=Decimal("0.50"),
        gross_currency="USD",
    )
    adapters["trading_212"] = (FakeBroker(harvest=harvest(dividends=(dividend,))),)

    sync(client, connection_id)

    (transaction,) = client.get("/api/transactions").json()
    assert transaction["type"] == "dividend"
    assert legs_of(client, transaction) == [("in", "EUR", "0.39", None)]
    apple = instruments_by_symbol(client)["AAPL"]
    assert transaction["capital_income"]["paying_instrument_id"] == apple["id"]
    # Nothing withheld is declared, because the venue stated none — but the
    # gross it did state is kept where the Admin will read it.
    assert transaction["capital_income"]["foreign_withholding"] == "0"
    assert "0.50 USD" in transaction["note"]


def test_a_dividend_declares_the_withholding_a_broker_states(client, adapters):
    connection_id, _ = depot(client)
    dividend = port.NormalizedDividend(
        external_id="dividend-1",
        occurred_at=PAID_AT,
        kind="dividend",
        amount=Decimal("0.85"),
        currency="EUR",
        security=APPLE,
        foreign_withholding=Decimal("0.15"),
        source_country="US",
    )
    adapters["trading_212"] = (FakeBroker(harvest=harvest(dividends=(dividend,))),)

    sync(client, connection_id)

    (transaction,) = client.get("/api/transactions").json()
    declared = transaction["capital_income"]
    assert (declared["foreign_withholding"], declared["source_country"]) == ("0.15", "US")


def test_a_withholding_broker_declares_the_german_tax_it_took_at_source(client, adapters):
    """The port carries what a withholding broker states — the next broker
    needs no change to it."""
    connection_id, _ = depot(client, withholding="at_source")
    dividend = port.NormalizedDividend(
        external_id="dividend-1",
        occurred_at=PAID_AT,
        kind="dividend",
        amount=Decimal("7.36"),
        currency="EUR",
        security=APPLE,
        kapitalertragsteuer=Decimal("2.50"),
        solidarity_surcharge=Decimal("0.14"),
    )
    adapters["trading_212"] = (FakeBroker(harvest=harvest(dividends=(dividend,))),)

    sync(client, connection_id)

    (transaction,) = client.get("/api/transactions").json()
    declared = transaction["capital_income"]
    assert (declared["kapitalertragsteuer"], declared["solidarity_surcharge"]) == ("2.50", "0.14")
    assert declared["church_tax"] == "0"


def test_interest_cash_movements_and_an_account_fee_each_land_as_what_they_are(client, adapters):
    connection_id, _ = depot(client)
    adapters["trading_212"] = (
        FakeBroker(
            harvest=harvest(
                cash_movements=(a_deposit(),),
                dividends=(
                    port.NormalizedDividend(
                        external_id="transaction-2",
                        occurred_at=PAID_AT,
                        kind="interest",
                        amount=Decimal("0.42"),
                        currency="EUR",
                    ),
                ),
                account_fees=(
                    port.NormalizedAccountFee(
                        external_id="transaction-3",
                        occurred_at=PULLED_AT,
                        amount=Decimal("1.00"),
                        currency="EUR",
                    ),
                ),
            )
        ),
    )

    result = sync(client, connection_id)

    assert result["imported"]["created"] == 3
    landed = {row["type"]: legs_of(client, row) for row in client.get("/api/transactions").json()}
    assert landed == {
        "transfer_in": [("in", "EUR", "1000", None)],
        "interest": [("in", "EUR", "0.42", None)],
        "fee": [("fee", "EUR", "1.00", None)],
    }
    # Interest on uninvested cash names no payer and states nothing withheld.
    assert all(row["capital_income"] is None for row in client.get("/api/transactions").json())


def test_syncing_again_changes_nothing(client, adapters):
    connection_id, _ = depot(client)
    adapters["trading_212"] = (
        FakeBroker(harvest=harvest(trades=(a_purchase(),), cash_movements=(a_deposit(),))),
    )
    sync(client, connection_id)

    again = sync(client, connection_id)

    assert (again["imported"]["created"], again["imported"]["duplicates"]) == (0, 2)
    assert len(client.get("/api/transactions").json()) == 2


# --- What is passed over, and the period covered ---


def test_an_event_passed_over_is_named_beside_what_landed(client, adapters):
    """A split is not a transaction the port can express: the rest of the
    history lands, and the split is named for the Admin to record."""
    connection_id, _ = depot(client)
    split = port.PassedOver(
        external_id="fill-9",
        occurred_at=PULLED_AT,
        description="STOCK_SPLIT of 6 Apple (US0378331005) — no trade; record it"
        " as the Corporate Action it is.",
    )
    adapters["trading_212"] = (
        FakeBroker(harvest=harvest(trades=(a_purchase(),), passed_over=(split,))),
    )

    result = sync(client, connection_id)

    assert result["ok"] is True and result["imported"]["created"] == 1
    assert result["passed_over"] == [
        "2031-06-02: STOCK_SPLIT of 6 Apple (US0378331005) — no trade; record it"
        " as the Corporate Action it is."
    ]


def test_a_sync_reports_the_period_it_covered(client, adapters):
    """An unbounded venue covers the Depot's history from its beginning; a
    capped one states where its window opened."""
    connection_id, _ = depot(client)
    adapters["trading_212"] = (FakeBroker(),)

    unbounded = sync(client, connection_id)

    assert unbounded["covered_period"] == {"start": None, "end": "2031-06-02T12:00:00Z"}

    opened = datetime(2031, 3, 4, 12, 0, tzinfo=UTC)
    adapters["trading_212"] = (
        FakeBroker(
            harvest=port.BrokerHarvest(covered=port.CoveredPeriod(opened, PULLED_AT)),
            lookback_days=90,
        ),
    )

    capped = sync(client, connection_id)

    assert capped["covered_period"] == {
        "start": "2031-03-04T12:00:00Z",
        "end": "2031-06-02T12:00:00Z",
    }


def test_a_depot_whose_withholding_is_unset_refuses_the_sync_and_claims_no_coverage(
    client, adapters
):
    connection_id, _ = depot(client, withholding=None)
    adapters["trading_212"] = (FakeBroker(harvest=harvest(trades=(a_purchase(),))),)

    result = sync(client, connection_id)

    assert result["ok"] is False and "withholding" in result["error"]
    assert result["covered_period"] is None
    assert client.get("/api/transactions").json() == []


def test_the_venue_registry_lists_the_broker_kind_with_its_lookback(client, adapters):
    adapters["trading_212"] = (FakeBroker(),)

    venues = {venue["venue"]: venue for venue in client.get("/api/connections/venues").json()}

    assert venues["trading_212"]["adapters"] == [{"kind": "securities", "lookback_days": None}]
    assert venues["trading_212"]["requires_secret"] is True


# --- Positions: for reconciliation only ---


def position(symbol, quantity, isin=None):
    return port.NormalizedPosition(
        symbol=symbol, quantity=Decimal(quantity), as_of=PULLED_AT, isin=isin
    )


def test_positions_never_become_transactions(client, adapters):
    """A position snapshot is not history: syncing a Depot whose venue holds
    shares the history does not explain writes nothing for them."""
    connection_id, _ = depot(client)
    adapters["trading_212"] = (
        FakeBroker(positions=(position("AAPL", "2", "US0378331005"), position("EUR", "500"))),
    )

    result = sync(client, connection_id)

    assert result["ok"] is True and result["imported"] is None
    assert client.get("/api/transactions").json() == []
    assert "AAPL" not in instruments_by_symbol(client)


def test_reconciliation_compares_securities_by_isin_and_cash_by_currency(client, adapters):
    connection_id, account_id = depot(client)
    adapters["trading_212"] = (
        FakeBroker(
            harvest=harvest(trades=(a_purchase(fees=()),), cash_movements=(a_deposit(),)),
            # The venue labels the paper differently than the ledger does;
            # the ISIN is what matches. One share is unaccounted for.
            positions=(position("APPLE-US", "3", "US0378331005"), position("EUR", "666.67")),
        ),
    )
    sync(client, connection_id)

    (reconciled,) = client.post(f"/api/connections/{connection_id}/reconcile").json()

    assert reconciled["ok"] is True and reconciled["account_id"] == account_id
    lines = {line["symbol"]: line for line in reconciled["lines"]}
    assert (lines["AAPL"]["family"], lines["AAPL"]["status"]) == ("security", "gap")
    assert (lines["AAPL"]["live"], lines["AAPL"]["tracked"], lines["AAPL"]["difference"]) == (
        "3",
        "2",
        "1",
    )
    assert lines["AAPL"]["resolutions"] == ["import_history", "opening_balance"]
    assert (lines["EUR"]["status"], lines["EUR"]["difference"]) == ("matched", "0.00")
    assert len(client.get("/api/transactions").json()) == 2


def test_a_position_in_a_security_the_ledger_never_saw_is_unresolved_not_minted(client, adapters):
    connection_id, _ = depot(client)
    adapters["trading_212"] = (FakeBroker(positions=(position("AAPL", "2", "US0378331005"),)),)

    (reconciled,) = client.post(f"/api/connections/{connection_id}/reconcile").json()

    (line,) = reconciled["lines"]
    assert (line["status"], line["instrument_id"], line["live"]) == ("unresolved", None, "2")
    assert "US0378331005" in line["detail"]
    assert "AAPL" not in instruments_by_symbol(client)


# --- One Depot, both ports (ticket 49) ---


class FakeExchange:
    """A fake of the exchange port: one kind and a scripted harvest."""

    kind = "spot"
    lookback_days = None

    def __init__(self, harvest):
        self.harvest = harvest

    def test(self, credentials):
        return "Authenticated."

    def pull(self, credentials):
        return self.harvest


def a_coin_purchase() -> exchange_port.NormalizedTrade:
    return exchange_port.NormalizedTrade(
        external_id="trade-1",
        occurred_at=BOUGHT_AT,
        base_symbol="BTC",
        quote_symbol="EUR",
        side="buy",
        base_quantity=Decimal("0.01"),
        quote_quantity=Decimal("400"),
    )


def test_both_kinds_of_one_connection_write_into_the_same_depot(client, adapters, db):
    """A venue that holds coins beside securities ships a kind of each port.
    Paired with one Depot they are one ingestion mode — the same credentialed
    link to the same venue account — so whichever commits first does not
    lock the other out."""
    instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    instruments.create_cash(db, symbol="EUR", name="Euro")
    connection_id, account_id = depot(client)
    client.put(f"/api/connections/{connection_id}/pairings/spot", json={"account_id": account_id})
    adapters["trading_212"] = (
        FakeExchange(exchange_port.Harvest(trades=(a_coin_purchase(),))),
        FakeBroker(harvest=harvest(trades=(a_purchase(fees=()),))),
    )

    spot, securities = client.post(f"/api/connections/{connection_id}/sync").json()

    assert (spot["ok"], spot["error"]) == (True, None)
    assert (securities["ok"], securities["error"]) == (True, None)
    transactions = client.get("/api/transactions").json()
    assert {transaction["import_source"] for transaction in transactions} == {
        "trading_212:spot",
        "trading_212:securities",
    }
    assert {leg["account_id"] for t in transactions for leg in t["legs"]} == {account_id}


def test_another_connections_kind_still_may_not_write_into_a_claimed_depot(client, adapters):
    """Sharing an Account is for the kinds of one Connection alone: a second
    Connection is a second source, and may reconcile but not write."""
    connection_id, account_id = depot(client)
    adapters["trading_212"] = (FakeBroker(harvest=harvest(trades=(a_purchase(fees=()),))),)
    sync(client, connection_id)
    platform_id = client.get("/api/platforms").json()[0]["id"]
    other = client.post(
        "/api/connections",
        json=dict(platform_id=platform_id, venue="bitpanda", label="Other", key="another-key"),
    ).json()["id"]
    client.put(f"/api/connections/{other}/pairings/securities", json={"account_id": account_id})
    adapters["bitpanda"] = (FakeBroker(harvest=harvest(cash_movements=(a_deposit(),))),)

    result = sync(client, other)

    assert result["ok"] is False
    assert "trading_212:securities" in result["error"]
    assert len(client.get("/api/transactions").json()) == 1

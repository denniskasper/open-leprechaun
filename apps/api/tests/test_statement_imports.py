"""A broker's exported statement through the connector port (ticket 50,
ADR-0008): a connector whose file is a broker's statement states the same
Normalized records a Broker Adapter pulls, and they land the same way — a
security named by its ISIN, the Depot's cash, the income with what was
withheld beside it — through preview and commit, as one reversible batch.

The seam is the HTTP API over real Postgres with a fake of the connector port
standing in through the registry dependency, so a broker served by import
needs no service, router or screen of its own.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

import test_etoro_connector as etoro
from open_leprechaun.adapters import get_csv_connectors
from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.ports import broker as port
from open_leprechaun.ports.csv_connector import ParsedFile
from open_leprechaun.repositories import instruments

BOUGHT_AT = datetime(2031, 3, 4, 14, 31, 7, tzinfo=UTC)
PAID_AT = datetime(2031, 5, 16, 11, 20, tzinfo=UTC)
COVERED = port.CoveredPeriod(
    datetime(2031, 1, 1, tzinfo=UTC), datetime(2031, 12, 31, 23, 59, 59, tzinfo=UTC)
)

APPLE = port.NormalizedSecurity(isin="US0378331005", symbol="AAPL", name="Apple")


@dataclass(frozen=True)
class FakeStatementConnector:
    """The port's fake for a broker's statement: what the file states is set
    by the test — no file format involved."""

    connector: str = "fake_broker"
    name: str = "Fake broker"
    expects: str = "The account statement the fake broker exports."
    timezone: str = "UTC"
    file_format: str = "xlsx"
    parsed: ParsedFile = field(default_factory=ParsedFile)

    def parse(self, content: str) -> ParsedFile:
        return self.parsed


@pytest.fixture
def connectors() -> dict:
    return {}


@pytest.fixture
def client(db: Engine, connectors: dict) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_csv_connectors] = lambda: connectors
    with TestClient(app) as client:
        yield client


def depot(client: TestClient, *, withholding: str | None = "none") -> int:
    """A broker Platform with its withholding behaviour set and one Depot
    under it — no Connection anywhere."""
    platform_id = client.post("/api/platforms", json={"name": "Broker", "kind": "broker"}).json()[
        "id"
    ]
    if withholding is not None:
        client.put(f"/api/platforms/{platform_id}/withholding", json={"behaviour": withholding})
    return client.post(
        f"/api/platforms/{platform_id}/accounts", json={"name": "Depot", "base_currency": "USD"}
    ).json()["id"]


def statement(**records) -> ParsedFile:
    return ParsedFile(statement=port.BrokerHarvest(covered=COVERED, **records))


def a_purchase(**overrides) -> port.NormalizedSecurityTrade:
    fields = dict(
        external_id="position-1:open",
        occurred_at=BOUGHT_AT,
        security=APPLE,
        side="buy",
        quantity=Decimal("2"),
        settled_amount=Decimal("360.00"),
        settlement_currency="USD",
    )
    fields.update(overrides)
    return port.NormalizedSecurityTrade(**fields)


def a_dividend(**overrides) -> port.NormalizedDividend:
    fields = dict(
        external_id="position-1:dividend:2031-05-16",
        occurred_at=PAID_AT,
        kind="dividend",
        amount=Decimal("0.85"),
        currency="USD",
        security=APPLE,
        foreign_withholding=Decimal("0.15"),
        source_country="US",
    )
    fields.update(overrides)
    return port.NormalizedDividend(**fields)


def request(account_id: int, **extra) -> dict:
    return {"connector": "fake_broker", "account_id": account_id, "content": "whatever", **extra}


def commit(client: TestClient, account_id: int) -> dict:
    committed = client.post("/api/csv-imports", json=request(account_id, label="statement.xlsx"))
    assert committed.status_code == 201
    return committed.json()


def legs_of(client: TestClient, transaction: dict) -> list[tuple]:
    symbols = {row["id"]: row["symbol"] for row in client.get("/api/instruments").json()}
    return [
        (leg["role"], symbols[leg["instrument_id"]], leg["quantity"]) for leg in transaction["legs"]
    ]


def test_the_registry_says_which_file_format_a_connector_reads(client, connectors):
    """The picker learns from the registry alone that this connector's file
    is a workbook, not text — so the screen knows how to hand it over."""
    connectors["fake_broker"] = FakeStatementConnector()

    (listed,) = client.get("/api/csv-connectors").json()

    assert listed["file_format"] == "xlsx"


def test_the_preview_names_what_the_statement_would_create_and_writes_nothing(client, connectors):
    """A security the ledger has never seen is announced, not refused: a
    statement names it by ISIN, which is its identity."""
    account_id = depot(client)
    connectors["fake_broker"] = FakeStatementConnector(parsed=statement(trades=(a_purchase(),)))

    preview = client.post("/api/csv-imports/preview", json=request(account_id))

    assert preview.status_code == 200
    answered = preview.json()
    assert [row["external_id"] for row in answered["to_create"]] == ["position-1:open"]
    assert {spec["symbol"] for spec in answered["new_instruments"]} == {"AAPL", "USD"}
    assert client.get("/api/transactions").json() == []
    assert client.get("/api/import-batches").json() == []


def test_the_preview_states_the_period_the_statement_covers(client, connectors):
    """A broker served by import is current only as far as its last
    statement, so the preview says how far this one reaches — on the
    statement's own declared clock, the dates the broker printed."""
    account_id = depot(client)
    connectors["fake_broker"] = FakeStatementConnector(
        parsed=ParsedFile(
            statement=port.BrokerHarvest(covered=COVERED), warnings=("1 row was left out.",)
        )
    )

    preview = client.post("/api/csv-imports/preview", json=request(account_id))

    assert preview.json()["warnings"][:2] == [
        "The statement covers 2031-01-01 to 2031-12-31.",
        "1 row was left out.",
    ]


def test_a_purchase_and_a_sale_land_as_the_security_against_the_depots_cash(client, connectors):
    account_id = depot(client)
    sale = a_purchase(
        external_id="position-1:close",
        occurred_at=PAID_AT,
        side="sell",
        settled_amount=Decimal("400.00"),
    )
    connectors["fake_broker"] = FakeStatementConnector(
        parsed=statement(trades=(a_purchase(), sale))
    )

    committed = commit(client, account_id)

    assert committed["created"] == 2
    (batch,) = client.get("/api/import-batches").json()
    assert batch["source"] == f"fake_broker:{account_id}"
    bought, sold = sorted(
        client.get("/api/transactions").json(), key=lambda row: row["occurred_at"]
    )
    assert legs_of(client, bought) == [("in", "AAPL", "2"), ("out", "USD", "360.00")]
    assert legs_of(client, sold) == [("in", "USD", "400.00"), ("out", "AAPL", "2")]


def test_a_dividend_lands_net_with_its_foreign_withholding_and_source_country(client, connectors):
    """Foreign withholding is recorded per dividend with the country that
    withheld it (ADR-0022): the in-leg is the net, the rest is declared."""
    account_id = depot(client)
    connectors["fake_broker"] = FakeStatementConnector(parsed=statement(dividends=(a_dividend(),)))

    commit(client, account_id)

    (transaction,) = client.get("/api/transactions").json()
    assert transaction["type"] == "dividend"
    assert legs_of(client, transaction) == [("in", "USD", "0.85")]
    declared = transaction["capital_income"]
    assert declared["foreign_withholding"] == "0.15"
    assert declared["source_country"] == "US"


def test_german_tax_withheld_at_source_is_recorded_per_event(client, connectors):
    """Where the statement reports what a withholding broker took, each
    component stands on the event it was taken from."""
    account_id = depot(client, withholding="at_source")
    connectors["fake_broker"] = FakeStatementConnector(
        parsed=statement(
            dividends=(
                a_dividend(
                    foreign_withholding=None,
                    source_country=None,
                    kapitalertragsteuer=Decimal("0.25"),
                    solidarity_surcharge=Decimal("0.01"),
                ),
            )
        )
    )

    commit(client, account_id)

    (transaction,) = client.get("/api/transactions").json()
    declared = transaction["capital_income"]
    assert declared["kapitalertragsteuer"] == "0.25"
    assert declared["solidarity_surcharge"] == "0.01"
    assert declared["church_tax"] == "0"


def test_cash_movements_and_account_fees_land_in_the_depots_currency(client, connectors):
    account_id = depot(client)
    connectors["fake_broker"] = FakeStatementConnector(
        parsed=statement(
            cash_movements=(
                port.NormalizedCashMovement(
                    external_id="deposit-1",
                    occurred_at=BOUGHT_AT,
                    direction="in",
                    currency="USD",
                    amount=Decimal("1000"),
                ),
            ),
            account_fees=(
                port.NormalizedAccountFee(
                    external_id="fee-1", occurred_at=PAID_AT, amount=Decimal("5"), currency="USD"
                ),
            ),
        )
    )

    commit(client, account_id)

    by_type = {row["type"]: row for row in client.get("/api/transactions").json()}
    assert legs_of(client, by_type["transfer_in"]) == [("in", "USD", "1000")]
    assert legs_of(client, by_type["fee"]) == [("fee", "USD", "5")]


def test_what_the_statement_states_that_is_no_transaction_is_passed_over_by_name(
    client, connectors
):
    """Never landed and never dropped: the preview says what the Admin must
    record by hand, dated by its Berlin day."""
    account_id = depot(client)
    connectors["fake_broker"] = FakeStatementConnector(
        parsed=statement(
            passed_over=(
                port.PassedOver(
                    external_id="position-9",
                    occurred_at=BOUGHT_AT,
                    description="A leveraged position in EURUSD was left out.",
                ),
            )
        )
    )

    preview = client.post("/api/csv-imports/preview", json=request(account_id))

    assert "2031-03-04: A leveraged position in EURUSD was left out." in preview.json()["warnings"]
    assert preview.json()["to_create"] == []


# --- A security the statement names by its ticker alone ---

NVIDIA_BY_TICKER = port.NormalizedSecurity(isin=None, symbol="NVDA", name="NVDA")


def test_a_ticker_no_security_answers_to_leaves_its_rows_out_with_what_to_do(client, connectors):
    """A ticker is a resolution hint, never an identity (ADR-0010): nothing
    is minted from it. The rest of the statement still lands, and the
    sentence says how to bring the row in."""
    account_id = depot(client)
    connectors["fake_broker"] = FakeStatementConnector(
        parsed=statement(
            trades=(
                a_purchase(),
                a_purchase(external_id="position-5:open", security=NVIDIA_BY_TICKER),
            )
        )
    )

    preview = client.post("/api/csv-imports/preview", json=request(account_id)).json()

    assert [row["external_id"] for row in preview["to_create"]] == ["position-1:open"]
    assert (
        "The statement names 'NVDA' by its ticker alone, and no security in the ledger"
        " answers to it — 1 row was left out. Create the security with that symbol or"
        " ticker, then import again."
    ) in preview["warnings"]


def test_a_ticker_one_security_answers_to_lands_under_that_securitys_isin(client, connectors, db):
    """Once the ledger holds the paper — by its symbol or by a ticker alias
    — the same file lands the row it left out before, and re-importing
    brings in only that."""
    account_id = depot(client)
    connectors["fake_broker"] = FakeStatementConnector(
        parsed=statement(
            trades=(
                a_purchase(),
                a_purchase(external_id="position-5:open", security=NVIDIA_BY_TICKER),
            ),
            dividends=(
                a_dividend(
                    external_id="position-5:dividend:2031-05-16",
                    security=NVIDIA_BY_TICKER,
                    foreign_withholding=None,
                    source_country=None,
                ),
            ),
        )
    )
    assert commit(client, account_id)["created"] == 1
    nvidia = instruments.create_security(
        db,
        symbol="NVIDIA",
        name="NVIDIA Corporation",
        type="share",
        isin="US67066G1040",
        ticker="NVDA",
    )

    preview = client.post("/api/csv-imports/preview", json=request(account_id)).json()
    again = commit(client, account_id)

    assert (
        "The statement names 'NVDA' by its ticker alone; its rows land under the one"
        " security in the ledger answering to it, US67066G1040."
    ) in preview["warnings"]
    assert again["created"] == 2 and again["duplicates"] == 1
    assert again["instruments_created"] == 0
    landed = [
        row
        for row in client.get("/api/transactions").json()
        if any(leg["instrument_id"] == nvidia for leg in row["legs"])
        or (row["capital_income"] or {}).get("paying_instrument_id") == nvidia
    ]
    assert sorted(row["type"] for row in landed) == ["dividend", "trade"]


def test_a_ticker_several_securities_answer_to_is_not_chosen_between(client, connectors, db):
    account_id = depot(client)
    instruments.create_security(
        db, symbol="NVDA", name="NVIDIA Corporation", type="share", isin="US67066G1040"
    )
    instruments.create_security(
        db, symbol="NVDA", name="Another paper", type="share", isin="DE000A0D9PT0"
    )
    connectors["fake_broker"] = FakeStatementConnector(
        parsed=statement(
            trades=(a_purchase(external_id="position-5:open", security=NVIDIA_BY_TICKER),)
        )
    )

    preview = client.post("/api/csv-imports/preview", json=request(account_id)).json()

    assert preview["to_create"] == []
    assert (
        "The statement names 'NVDA' by its ticker alone, and several securities in the"
        " ledger answer to it — 1 row was left out, because the ledger cannot choose."
    ) in preview["warnings"]


def test_reimporting_an_overlapping_statement_changes_nothing(client, connectors):
    account_id = depot(client)
    connectors["fake_broker"] = FakeStatementConnector(parsed=statement(trades=(a_purchase(),)))
    commit(client, account_id)

    again = commit(client, account_id)

    assert again["batch_id"] is None
    assert again["created"] == 0 and again["duplicates"] == 1


def test_a_statement_declares_itself_authoritative_for_the_depot(client, connectors):
    """What the Platforms screen reads to say this broker is served by
    import: the Depot's one writing source is the statement connector."""
    account_id = depot(client)
    connectors["fake_broker"] = FakeStatementConnector(parsed=statement(trades=(a_purchase(),)))

    commit(client, account_id)

    (platform,) = client.get("/api/platforms").json()
    (account,) = platform["accounts"]
    assert account["authoritative_source"] == f"fake_broker:{account_id}"


def test_a_depot_without_its_withholding_behaviour_refuses_the_commit(client, connectors):
    account_id = depot(client, withholding=None)
    connectors["fake_broker"] = FakeStatementConnector(parsed=statement(trades=(a_purchase(),)))

    refused = client.post("/api/csv-imports", json=request(account_id, label="statement.xlsx"))

    assert refused.status_code == 409
    assert "withholding behaviour is not set" in refused.json()["detail"]


# --- The shipped statement connector, end to end ---


@pytest.fixture
def shipped(db: Engine) -> Iterator[TestClient]:
    """The API over the registry production reads — no fake anywhere."""
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    with TestClient(app) as client:
        yield client


def test_a_recorded_etoro_statement_lands_through_preview_and_commit(shipped):
    """The whole path a broker served by import takes: the workbook goes up
    in base64, the preview says what it would create and what it leaves out,
    and the commit lands exactly that as one batch."""
    account_id = depot(shipped)
    file = {
        "connector": "etoro",
        "account_id": account_id,
        "content": etoro.content_of(etoro.recorded()),
    }

    preview = shipped.post("/api/csv-imports/preview", json=file)

    assert preview.status_code == 200
    previewed = preview.json()
    assert len(previewed["to_create"]) == 9
    assert previewed["skipped"] == []
    assert {spec["symbol"] for spec in previewed["new_instruments"]} == {"AAPL", "VUSA.L", "USD"}
    assert previewed["warnings"][0] == "The statement covers 2031-01-01 to 2031-12-31."
    assert any("'NVDA' by its ticker alone" in warning for warning in previewed["warnings"])
    assert any("Position 2000000003 in EURUSD" in warning for warning in previewed["warnings"])
    assert shipped.get("/api/transactions").json() == []

    committed = shipped.post("/api/csv-imports", json={**file, "label": "statement.xlsx"})

    assert committed.status_code == 201
    assert committed.json()["created"] == 9
    assert committed.json()["instruments_created"] == 3
    (batch,) = shipped.get("/api/import-batches").json()
    assert batch["source"] == f"etoro:{account_id}"
    transactions = shipped.get("/api/transactions").json()
    assert sorted(row["type"] for row in transactions) == [
        "dividend",
        "dividend",
        "fee",
        "interest",
        "trade",
        "trade",
        "trade",
        "transfer_in",
        "transfer_out",
    ]
    symbols = {row["id"]: row for row in shipped.get("/api/instruments").json()}
    apple = next(row for row in symbols.values() if row["symbol"] == "AAPL")
    assert apple["isin"] == "US0378331005"
    withheld = next(
        row["capital_income"]
        for row in transactions
        if row["type"] == "dividend"
        and row["capital_income"]["paying_instrument_id"] == apple["id"]
    )
    assert withheld["foreign_withholding"] == "0.36"
    assert withheld["source_country"] == "US"
    # A stamp duty is a cost of the security it was charged on.
    stamped = next(
        row
        for row in transactions
        if any(leg["role"] == "fee" and leg["quantity"] == "4.5" for leg in row["legs"])
    )
    by_id = {leg["id"]: leg for leg in stamped["legs"]}
    fee = next(leg for leg in stamped["legs"] if leg["role"] == "fee")
    assert symbols[by_id[fee["charged_against_leg_id"]]["instrument_id"]]["symbol"] == "VUSA.L"


def test_reimporting_the_etoro_statement_changes_nothing(shipped):
    account_id = depot(shipped)
    file = {
        "connector": "etoro",
        "account_id": account_id,
        "content": etoro.content_of(etoro.recorded()),
        "label": "statement.xlsx",
    }
    shipped.post("/api/csv-imports", json=file)

    again = shipped.post("/api/csv-imports", json=file)

    assert again.json()["created"] == 0
    assert again.json()["duplicates"] == 9
    assert len(shipped.get("/api/import-batches").json()) == 1


def test_a_file_that_is_no_statement_is_refused_with_the_connectors_sentence(shipped):
    account_id = depot(shipped)

    refused = shipped.post(
        "/api/csv-imports/preview",
        json={"connector": "etoro", "account_id": account_id, "content": "Date,Type\n"},
    )

    assert refused.status_code == 422
    assert "not an eToro account statement" in refused.json()["detail"]

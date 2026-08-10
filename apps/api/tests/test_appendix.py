"""The appendix behind a report's headline figures (ticket 24): every figure
backed by the line items that produced it, exportable as CSV and as PDF that
state the same figures — built from the report's frozen JSON, never
recomputed, so a final report's appendix is as immutable as the report.

The seam is the HTTP API over real Postgres — the exports are downloads of a
stored report — with rates through the reference-rate port's fake. Every
number in this file is invented for the scenario; none derives from any
account.
"""

import csv
import io
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.rates import get_reference_rate_source
from open_leprechaun.repositories import (
    crypto_prices,
    instruments,
    platforms,
    stances,
    transactions,
)
from open_leprechaun.repositories.transactions import Leg

BOUGHT_LONG_AGO = datetime(2024, 3, 14, 12, 0, tzinfo=UTC)
OPENED = datetime(2025, 1, 10, 12, 0, tzinfo=UTC)
SOLD = datetime(2025, 6, 3, 12, 0, tzinfo=UTC)


class FakeReferenceRateSource:
    """The reference-rate port's fake: whatever rates the test hands it,
    answered per query window."""

    def __init__(self, rates=()):
        self.rates = list(rates)

    def daily_rates(self, currency, start, end):
        return [
            rate
            for rate in self.rates
            if rate.currency == currency and start <= rate.rate_date <= end
        ]


@pytest.fixture
def client(db):
    """The API bound to the migrated test database, rates through the fake."""
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_reference_rate_source] = FakeReferenceRateSource
    with TestClient(app) as client:
        yield client


def _account(db):
    platform_id = platforms.create_platform(db, name="Kraken", kind="exchange")
    created = platforms.create_account(db, platform_id, name="Main")
    assert isinstance(created, int)
    return created


def _eur(db):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    return eur


def _kept_coin(db, account, symbol="BTC", chain="bitcoin"):
    coin = instruments.create_native_coin(db, symbol=symbol, name=symbol, chain=chain)
    settled = stances.classify(db, coin, stance="kept", account_id=account)
    assert not isinstance(settled, stances.Refusal)
    return coin


def _transaction(db, type, occurred_at, legs, **declarations):
    created = transactions.create_transaction(
        db, type=type, occurred_at=occurred_at, note=None, legs=legs, **declarations
    )
    assert isinstance(created, int)
    return created


def _ledger(db):
    """One of everything a headline figure rests on: a purchase held beyond
    the Haltefrist, an Opening Balance with an estimated basis, one disposal
    consuming both lots with a fee against it, §22 income and a §20 dividend.

    The sale of 2 BTC for 24000 € (10 € fee) consumes FIFO: the 2024 lot
    (basis 10000, exempt — held beyond a year) and the estimated 2025 opening
    lot (basis 5000, taxable). Each consumption takes half the proceeds
    (12000) and half the fee (5.00): gains 1995.00 exempt, 6995.00 taxable —
    the year's counted total, all of it resting on the estimate."""
    account, eur = _account(db), _eur(db)
    btc = _kept_coin(db, account)
    crypto_prices.store_quote(
        db, instrument_id=btc, price_eur=Decimal("50000"), source="a test", as_of=SOLD
    )
    _transaction(
        db,
        "trade",
        BOUGHT_LONG_AGO,
        [
            Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal("10000")),
            Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("1")),
        ],
    )
    _transaction(
        db,
        "opening_balance",
        OPENED,
        [Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("1"))],
        reconstructed="basis",
        estimated_basis_eur=Decimal("5000"),
    )
    _transaction(
        db,
        "trade",
        SOLD,
        [
            Leg(account_id=account, instrument_id=btc, role="out", quantity=Decimal("2")),
            Leg(account_id=account, instrument_id=eur, role="in", quantity=Decimal("24000")),
            Leg(
                account_id=account,
                instrument_id=eur,
                role="fee",
                quantity=Decimal("10"),
                charged_against=0,
            ),
        ],
    )
    _transaction(
        db,
        "staking_reward",
        SOLD,
        [Leg(account_id=account, instrument_id=eur, role="in", quantity=Decimal("200"))],
    )
    _transaction(
        db,
        "dividend",
        SOLD,
        [Leg(account_id=account, instrument_id=eur, role="in", quantity=Decimal("500"))],
    )


def _report_id(client):
    generated = client.post("/api/reports", json={"year": 2025})
    assert generated.status_code == 201
    return generated.json()["id"]


def _parse(text):
    """The CSV split back into its two blocks: the summary pairs and the
    line-item table under its header row."""
    rows = list(csv.reader(io.StringIO(text)))
    split = rows.index([])
    summary = {label: value for label, value in rows[:split]}
    header, *lines = rows[split + 1 :]
    return summary, [dict(zip(header, line, strict=True)) for line in lines]


def _pdf_text(content):
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)


# --- The CSV: every headline figure backed by its line items -----------------


def test_each_disposal_line_states_its_working_and_the_lots_consumed(db, client):
    """One row per consumed lot slice, carrying the disposal it belongs to:
    acquisition and disposal dates, quantity, basis, proceeds, fees, holding
    period, exempt or taxable, category — the disposal's rows are its lots."""
    _ledger(db)
    report_id = _report_id(client)

    response = client.get(f"/api/reports/{report_id}/appendix.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    _, lines = _parse(response.text)
    exempt, taxable = [line for line in lines if line["section"] == "section23"]
    for consumed in (exempt, taxable):
        assert consumed["category"] == "private_sale"
        assert consumed["instrument"] == "BTC"
        assert consumed["account"] == "Kraken / Main"
        assert consumed["date"] == "2025-06-03"
        assert consumed["quantity"] == "1"
        assert consumed["proceeds_eur"] == "12000.00"
        assert consumed["fees_eur"] == "5.00"
        assert consumed["line"].startswith("leg:")
    assert exempt["acquired_on"] == "2024-03-14"
    assert exempt["basis_eur"] == "10000.00"
    assert exempt["amount_eur"] == "1995.00"
    assert exempt["holding_days"] == "446"
    assert exempt["treatment"] == "exempt"
    assert taxable["acquired_on"] == "2025-01-10"
    assert taxable["basis_eur"] == "5000.00"
    assert taxable["amount_eur"] == "6995.00"
    assert taxable["holding_days"] == "144"
    assert taxable["treatment"] == "taxable"


def test_estimated_bases_are_marked_and_their_exposure_totalled(db, client):
    """The line resting on the Opening Balance estimate wears the mark, the
    documented purchase does not, and the summary states how much of the
    counted gain rests on estimation."""
    _ledger(db)
    report_id = _report_id(client)

    summary, lines = _parse(client.get(f"/api/reports/{report_id}/appendix.csv").text)

    exempt, taxable = [line for line in lines if line["section"] == "section23"]
    assert exempt["estimated_basis"] == ""
    assert taxable["estimated_basis"] == "estimated"
    assert summary["section23.gain_on_estimated_basis_eur"] == "6995.00"


def test_the_exempt_disposal_is_visible_while_the_total_excludes_it(db, client):
    """The 1995.00 exempt gain stands in its line, and the summary's counted
    total is the taxable 6995.00 alone — visible working, correct figure."""
    _ledger(db)
    report_id = _report_id(client)

    summary, lines = _parse(client.get(f"/api/reports/{report_id}/appendix.csv").text)

    assert any(line["treatment"] == "exempt" for line in lines)
    assert summary["section23.total_gain_eur"] == "6995.00"
    assert summary["section23.tax_free"] == "no"
    assert summary["section23.taxable_gain_eur"] == "6995.00"


def test_income_and_capital_lines_back_their_sections_totals(db, client):
    """The §22 receipt and the §20 dividend each appear as a line wearing its
    own category, and the summary restates their frozen headline figures."""
    _ledger(db)
    report_id = _report_id(client)

    summary, lines = _parse(client.get(f"/api/reports/{report_id}/appendix.csv").text)

    (income,) = [line for line in lines if line["section"] == "section22"]
    assert income["category"] == "staking_reward"
    assert income["quantity"] == "200"
    assert income["amount_eur"] == "200.00"
    assert income["date"] == "2025-06-03"
    assert income["treatment"] == "counted"
    (dividend,) = [line for line in lines if line["section"] == "section20"]
    assert dividend["category"] == "sonstige"
    assert dividend["amount_eur"] == "500.00"
    assert dividend["line"].startswith("leg:")
    assert summary["section22.total_income_eur"] == "200.00"
    assert summary["section22.tax_free"] == "yes"
    assert summary["section20.balance.sonstige_eur"] == "500.00"
    assert summary["section20.taxable_eur"] == "0.00"


# --- The PDF: the same figures in archival form ------------------------------


def test_the_pdf_states_every_figure_the_csv_states(db, client):
    """Both exports render the one appendix built from the frozen figures —
    every summary value and every cell of every line appears in the PDF.
    Multi-word cells are checked word by word, since the PDF may wrap a cell
    across lines without changing what it states."""
    _ledger(db)
    report_id = _report_id(client)

    pdf = client.get(f"/api/reports/{report_id}/appendix.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    text = _pdf_text(pdf.content)

    summary, lines = _parse(client.get(f"/api/reports/{report_id}/appendix.csv").text)
    for label, value in summary.items():
        for word in value.split():
            assert word in text, f"{label}={value} missing from the PDF"
    for line in lines:
        for column, cell in line.items():
            for word in cell.split():
                assert word in text, f"{column}={cell} missing from the PDF"


# --- Awaiting valuation: carried, never guessed ------------------------------


def test_an_appendix_awaiting_valuation_says_so_instead_of_totals(db, client):
    """A crypto-for-crypto disposal whose proceeds no rate can state leaves
    the year without a §23 total — the line says awaiting valuation, and the
    summary states the condition instead of a number."""
    account, eur = _account(db), _eur(db)
    btc = _kept_coin(db, account)
    sol = _kept_coin(db, account, symbol="SOL", chain="solana")
    for coin in (btc, sol):
        crypto_prices.store_quote(
            db, instrument_id=coin, price_eur=Decimal("100"), source="a test", as_of=SOLD
        )
    _transaction(
        db,
        "trade",
        OPENED,
        [
            Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal("1000")),
            Leg(account_id=account, instrument_id=btc, role="in", quantity=Decimal("1")),
        ],
    )
    _transaction(
        db,
        "trade",
        SOLD,
        [
            Leg(account_id=account, instrument_id=btc, role="out", quantity=Decimal("1")),
            Leg(account_id=account, instrument_id=sol, role="in", quantity=Decimal("10")),
        ],
    )
    report_id = _report_id(client)

    summary, lines = _parse(client.get(f"/api/reports/{report_id}/appendix.csv").text)

    (disposal,) = [line for line in lines if line["section"] == "section23"]
    assert disposal["treatment"] == "awaiting_valuation"
    assert disposal["amount_eur"] == ""
    assert summary["section23.total_gain_eur"] == "awaiting valuation"


# --- Refusals ----------------------------------------------------------------


def test_an_unknown_report_has_no_appendix(db, client):
    assert client.get("/api/reports/12345/appendix.csv").status_code == 404
    assert client.get("/api/reports/12345/appendix.pdf").status_code == 404

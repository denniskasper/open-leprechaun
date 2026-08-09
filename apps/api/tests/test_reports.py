"""The report lifecycle (ticket 23): generating a report freezes its figures
together with a fingerprint of the inputs that produced them — the same
mechanism that guards the Tax Lot materialisation (ADR-0014), under the
report's own subject. A report moves draft → final, a final report never
changes, and a report whose fingerprint no longer matches the current data is
flagged stale naming what changed, by input class and count.

The seam is the HTTP API over real Postgres — generation and finalisation are
the Admin's explicit acts — with rates through the reference-rate port's fake.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.rates import get_reference_rate_source
from open_leprechaun.repositories import (
    crypto_prices,
    instruments,
    platforms,
    stances,
    statutory,
    transactions,
)
from open_leprechaun.repositories.transactions import Leg

BOUGHT = datetime(2025, 3, 14, 12, 0, tzinfo=UTC)
SOLD = datetime(2025, 6, 3, 12, 0, tzinfo=UTC)

# The statutory mutation years: 2030+ like test_statutory.py, so the
# migration-seeded rows other files rely on stay pristine across runs.
BOUGHT_2031 = datetime(2031, 3, 14, 12, 0, tzinfo=UTC)
SOLD_2031 = datetime(2031, 6, 3, 12, 0, tzinfo=UTC)


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
def store(db):
    """The migrated database with this file's statutory mutation years wiped —
    statutory rows outlive the shared `db` fixture, which resets only the
    ledger's tables."""
    with db.begin() as connection:
        connection.execute(text("DELETE FROM statutory_value WHERE year >= 2030"))
    return db


@pytest.fixture
def client(db):
    """The API bound to the migrated test database, rates through the fake."""
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_reference_rate_source] = FakeReferenceRateSource
    with TestClient(app) as client:
        yield client


def _account(db, platform_name="Kraken", kind="exchange", name="Main"):
    platform_id = platforms.create_platform(db, name=platform_name, kind=kind)
    created = platforms.create_account(db, platform_id, name=name)
    assert isinstance(created, int)
    return created


def _eur(db):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    return eur


def _btc(db):
    return instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")


def _keep(db, instrument, account):
    settled = stances.classify(db, instrument, stance="kept", account_id=account)
    assert not isinstance(settled, stances.Refusal)


def _trade(db, account, give, get, *, given, gotten, occurred_at):
    created = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=occurred_at,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=give, role="out", quantity=Decimal(given)),
            Leg(account_id=account, instrument_id=get, role="in", quantity=Decimal(gotten)),
        ],
    )
    assert isinstance(created, int)
    return created


def _limits(db, *, year):
    """Both engines' Freigrenzen for a year no migration seeds."""
    for key in ("private_sale_exemption_limit", "other_income_exemption_limit"):
        statutory.upsert_value(db, year=year, key=key, value=Decimal("1000"), source="a test value")


def _round_trip(db, *, bought_at=BOUGHT, sold_at=SOLD):
    """A ledger with one taxable private sale: bought for 10000, sold for
    12000 within the year — a gain of 2000. The coin carries a stored price,
    so finalisation meets no unpriced-Instrument blocker (ticket 25)."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    crypto_prices.store_quote(
        db, instrument_id=btc, price_eur=Decimal("50000"), source="a test", as_of=sold_at
    )
    purchase = _trade(db, account, eur, btc, given="10000", gotten="1", occurred_at=bought_at)
    sale = _trade(db, account, btc, eur, given="1", gotten="12000", occurred_at=sold_at)
    return account, eur, btc, purchase, sale


# --- Generation freezes the figures with a fingerprint ----------------------


def test_generating_a_report_stores_the_figures_and_answers_them_frozen(db, client):
    """Generation computes the year's §23 and §22 figures, freezes them on
    the report, and the report answers fresh — not stale — right after."""
    _round_trip(db)

    generated = client.post("/api/reports", json={"year": 2025})

    assert generated.status_code == 201
    report_id = generated.json()["id"]
    report = client.get(f"/api/reports/{report_id}").json()
    assert report["year"] == 2025
    assert report["status"] == "draft"
    assert report["finalised_at"] is None
    assert report["stale"] is False
    assert report["changed_inputs"] == []
    section23 = report["figures"]["section23"]
    assert section23["total_gain_eur"] == "2000"
    # The 2025 Freigrenze the migration chain seeds: 1000 €, overshot.
    assert section23["freigrenze"]["tax_free"] is False
    assert section23["freigrenze"]["taxable_gain_eur"] == "2000"
    (disposal,) = section23["disposals"]
    assert disposal["quantity"] == "1"
    assert disposal["proceeds_eur"] == "12000"
    section22 = report["figures"]["section22"]
    assert section22["total_income_eur"] == "0"
    assert section22["freigrenze"]["tax_free"] is True


def test_regenerating_creates_a_new_report_and_never_mutates_an_existing_one(db, client):
    """Regeneration is a new row: the earlier report keeps its identity, its
    status and its frozen figures — history is preserved."""
    account, eur, btc, _, _ = _round_trip(db)
    first = client.post("/api/reports", json={"year": 2025}).json()["id"]
    first_figures = client.get(f"/api/reports/{first}").json()["figures"]
    # The ledger moves between the generations: a second sale in the year.
    _trade(db, account, eur, btc, given="4000", gotten="0.5", occurred_at=BOUGHT)
    _trade(db, account, btc, eur, given="0.5", gotten="7000", occurred_at=SOLD)

    second = client.post("/api/reports", json={"year": 2025}).json()["id"]

    assert second != first
    assert [report["id"] for report in client.get("/api/reports").json()] == [second, first]
    older = client.get(f"/api/reports/{first}").json()
    assert older["figures"] == first_figures
    assert older["status"] == "draft"
    newer = client.get(f"/api/reports/{second}").json()
    assert newer["figures"]["section23"]["total_gain_eur"] == "5000"
    assert newer["stale"] is False


# --- Draft → final, one way -------------------------------------------------


def test_a_report_moves_draft_to_final_exactly_once(db, client):
    """Finalisation is explicit, one-way, and carries its instant; a second
    attempt is refused — a final report is immutable."""
    _round_trip(db)
    report_id = client.post("/api/reports", json={"year": 2025}).json()["id"]

    assert client.post(f"/api/reports/{report_id}/finalise").status_code == 204

    report = client.get(f"/api/reports/{report_id}").json()
    assert report["status"] == "final"
    assert report["finalised_at"] is not None
    assert client.post(f"/api/reports/{report_id}/finalise").status_code == 409


def test_finalising_an_unknown_report_is_not_found(db, client):
    assert client.post("/api/reports/12345/finalise").status_code == 404


# --- Staleness: flagged wherever shown, naming what moved -------------------


def test_a_ledger_change_flags_the_report_stale_naming_class_and_count(db, client):
    """A transaction recorded after generation makes the stored fingerprint a
    lie the report itself confesses: stale wherever it is shown — listing and
    detail alike — naming the drifted input classes with their counts."""
    account, eur, btc, _, _ = _round_trip(db)
    report_id = client.post("/api/reports", json={"year": 2025}).json()["id"]
    _trade(db, account, eur, btc, given="5000", gotten="0.5", occurred_at=SOLD)

    report = client.get(f"/api/reports/{report_id}").json()

    assert report["stale"] is True
    changed = {entry["input_class"]: entry for entry in report["changed_inputs"]}
    assert changed["transactions"]["stored_count"] == 2
    assert changed["transactions"]["current_count"] == 3
    assert "transaction_legs" in changed
    (listed,) = client.get("/api/reports").json()
    assert listed["stale"] is True
    assert listed["changed_inputs"] == report["changed_inputs"]


def test_correcting_a_statutory_rate_marks_the_report_resting_on_it_stale(store, client):
    """The fingerprint covers statutory configuration: correcting the
    Freigrenze changes every figure resting on it while no transaction has
    moved — the report says so."""
    _round_trip(store, bought_at=BOUGHT_2031, sold_at=SOLD_2031)
    _limits(store, year=2031)
    report_id = client.post("/api/reports", json={"year": 2031}).json()["id"]

    statutory.upsert_value(
        store,
        year=2031,
        key="private_sale_exemption_limit",
        value=Decimal("600"),
        source="a correction",
    )

    report = client.get(f"/api/reports/{report_id}").json()
    assert report["stale"] is True
    assert "statutory_configuration" in {entry["input_class"] for entry in report["changed_inputs"]}


def test_deleting_a_depended_on_transaction_never_silently_changes_a_final_figure(db, client):
    """Deleting a transaction a final report depends on is not blocked — the
    ledger stays editable — but the finalised figures stand untouched and the
    report is flagged stale, naming the loss."""
    _, _, _, _, sale = _round_trip(db)
    report_id = client.post("/api/reports", json={"year": 2025}).json()["id"]
    assert client.post(f"/api/reports/{report_id}/finalise").status_code == 204
    frozen = client.get(f"/api/reports/{report_id}").json()["figures"]

    assert client.delete(f"/api/transactions/{sale}").status_code == 204

    report = client.get(f"/api/reports/{report_id}").json()
    assert report["figures"] == frozen
    assert report["status"] == "final"
    assert report["stale"] is True
    changed = {entry["input_class"]: entry for entry in report["changed_inputs"]}
    assert changed["transactions"]["stored_count"] == 2
    assert changed["transactions"]["current_count"] == 1


def test_a_final_report_is_never_silently_recomputed(db, client):
    """Reading a stale final report answers the frozen figures with the
    staleness beside them; only an explicit regeneration computes anew, and
    it lands on a new report."""
    account, eur, btc, _, _ = _round_trip(db)
    report_id = client.post("/api/reports", json={"year": 2025}).json()["id"]
    assert client.post(f"/api/reports/{report_id}/finalise").status_code == 204
    _trade(db, account, eur, btc, given="4000", gotten="0.5", occurred_at=BOUGHT)
    _trade(db, account, btc, eur, given="0.5", gotten="7000", occurred_at=SOLD)

    stale = client.get(f"/api/reports/{report_id}").json()
    assert stale["figures"]["section23"]["total_gain_eur"] == "2000"
    assert stale["stale"] is True

    regenerated_id = client.post("/api/reports", json={"year": 2025}).json()["id"]
    assert regenerated_id != report_id
    regenerated = client.get(f"/api/reports/{regenerated_id}").json()
    assert regenerated["figures"]["section23"]["total_gain_eur"] == "5000"
    assert client.get(f"/api/reports/{report_id}").json()["figures"] == stale["figures"]


# --- Refusals ---------------------------------------------------------------


def test_generating_refuses_a_year_whose_limit_is_unset(store, client):
    """A year without its Freigrenze refuses to compute rather than assuming
    one — the refusal names the missing key and its statute."""
    _round_trip(store, bought_at=BOUGHT_2031, sold_at=SOLD_2031)

    refused = client.post("/api/reports", json={"year": 2031})

    assert refused.status_code == 409
    assert "private_sale_exemption_limit" in refused.json()["detail"]
    assert client.get("/api/reports").json() == []


def test_an_unknown_report_is_not_found(db, client):
    assert client.get("/api/reports/12345").status_code == 404

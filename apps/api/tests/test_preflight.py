"""Pre-flight blockers (ticket 25): the app refuses to finalise a report
while it already knows something is wrong — an unmatched transfer, an
unpriced Instrument with activity in the year, a disposal exceeding its lots,
an unacknowledged Instrument with activity, or missing statutory
configuration for the year. Each blocker names what stands in the way and
links the screen that resolves it. The Admin may override with an
acknowledgement, which is recorded on the report and shown wherever the
report is.

The seam is the HTTP API over real Postgres — finalisation is the Admin's
explicit act — with rates through the reference-rate port's fake.
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
SOON_AFTER = datetime(2025, 6, 3, 14, 0, tzinfo=UTC)

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
    """What generation itself reads, for a year no migration seeds: the
    §23/§22 Freigrenzen and the §20 assessment's values — the other required
    keys stay unset, which is exactly what the statutory blocker names."""
    for key, value in (
        ("private_sale_exemption_limit", "1000"),
        ("other_income_exemption_limit", "1000"),
        ("saver_allowance_single", "1000"),
        ("flat_rate", "0.25"),
        ("solidarity_surcharge_rate", "0.055"),
    ):
        statutory.upsert_value(db, year=year, key=key, value=Decimal(value), source="a test value")


def _round_trip(db, *, bought_at=BOUGHT, sold_at=SOLD):
    """A ledger with one taxable private sale: bought for 10000, sold for
    12000 within the year."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    purchase = _trade(db, account, eur, btc, given="10000", gotten="1", occurred_at=bought_at)
    sale = _trade(db, account, btc, eur, given="1", gotten="12000", occurred_at=sold_at)
    return account, eur, btc, purchase, sale


def _transfer_out(db, account, instrument, *, quantity, occurred_at):
    created = transactions.create_transaction(
        db,
        type="transfer_out",
        occurred_at=occurred_at,
        note=None,
        legs=[
            Leg(
                account_id=account, instrument_id=instrument, role="out", quantity=Decimal(quantity)
            )
        ],
    )
    assert isinstance(created, int)
    return _leg_of(db, created)


def _transfer_in(db, account, instrument, *, quantity, occurred_at):
    created = transactions.create_transaction(
        db,
        type="transfer_in",
        occurred_at=occurred_at,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=instrument, role="in", quantity=Decimal(quantity))
        ],
    )
    assert isinstance(created, int)
    return _leg_of(db, created)


def _leg_of(db, transaction_id):
    with db.connect() as connection:
        return connection.execute(
            text("SELECT id FROM transaction_leg WHERE transaction_id = :id"),
            {"id": transaction_id},
        ).scalar_one()


def _price(db, instrument, *, at=SOLD):
    """A stored last-known price, so the Instrument is no longer unpriced."""
    crypto_prices.store_quote(
        db, instrument_id=instrument, price_eur=Decimal("50000"), source="a test", as_of=at
    )


def _blockers(refused):
    assert refused.status_code == 409
    return {blocker["kind"]: blocker for blocker in refused.json()["detail"]["blockers"]}


# --- Finalisation is refused while any blocker is unresolved ----------------


def test_missing_statutory_configuration_blocks_finalisation(store, client):
    """A year holding only what generation itself reads generates, but
    finalising is refused while other required statutory values are missing —
    the blocker names the gap and links the statutory settings."""
    _round_trip(store, bought_at=BOUGHT_2031, sold_at=SOLD_2031)
    _limits(store, year=2031)
    report_id = client.post("/api/reports", json={"year": 2031}).json()["id"]

    refused = client.post(f"/api/reports/{report_id}/finalise")

    blockers = _blockers(refused)
    blocker = blockers["missing_statutory_configuration"]
    assert blocker["resolve_path"] == "/settings/statutory"
    assert "advance_lump_sum_base_rate" in blocker["detail"]
    assert "2031" in blocker["detail"]
    report = client.get(f"/api/reports/{report_id}").json()
    assert report["status"] == "draft"
    assert report["finalised_at"] is None


def test_an_unpriced_instrument_with_activity_in_the_year_blocks_finalisation(db, client):
    """An Instrument nothing has ever priced, moving in the report's year,
    blocks finalisation by name — and a stored price resolves the blocker."""
    _, _, btc, _, _ = _round_trip(db)
    report_id = client.post("/api/reports", json={"year": 2025}).json()["id"]

    refused = client.post(f"/api/reports/{report_id}/finalise")

    blocker = _blockers(refused)["unpriced_instruments"]
    assert blocker["resolve_path"] == "/instruments"
    assert "BTC" in blocker["detail"]
    assert blocker["count"] == 1

    _price(db, btc)
    assert client.post(f"/api/reports/{report_id}/finalise").status_code == 204


def test_activity_in_another_year_does_not_make_an_unpriced_instrument_block(db, client):
    """An unpriced Instrument whose activity all sits in an earlier year does
    not block this year's report — the check is scoped to the report's
    year."""
    _round_trip(
        db,
        bought_at=datetime(2024, 3, 14, 12, 0, tzinfo=UTC),
        sold_at=datetime(2024, 6, 3, 12, 0, tzinfo=UTC),
    )
    report_id = client.post("/api/reports", json={"year": 2025}).json()["id"]

    assert client.post(f"/api/reports/{report_id}/finalise").status_code == 204


def test_an_unmatched_transfer_blocks_finalisation(db, client):
    """Transfer legs no confirmed match carries block finalisation — and the
    Admin confirming the pair resolves the blocker."""
    account, eur, btc = _account(db), _eur(db), _btc(db)
    _keep(db, btc, account)
    _price(db, btc)
    _trade(db, account, eur, btc, given="10000", gotten="1", occurred_at=BOUGHT)
    cold = _account(db, platform_name="BitBox", kind="cold_storage", name="Vault")
    out_leg = _transfer_out(db, account, btc, quantity="0.5", occurred_at=SOLD)
    in_leg = _transfer_in(db, cold, btc, quantity="0.5", occurred_at=SOON_AFTER)
    report_id = client.post("/api/reports", json={"year": 2025}).json()["id"]

    refused = client.post(f"/api/reports/{report_id}/finalise")

    blocker = _blockers(refused)["unmatched_transfers"]
    assert blocker["resolve_path"] == "/transfers"
    assert blocker["count"] == 2

    confirmed = client.post(
        "/api/transfer-matches",
        json={"out_leg_id": out_leg, "in_leg_id": in_leg, "verdict": "confirmed"},
    )
    assert confirmed.status_code == 201
    assert client.post(f"/api/reports/{report_id}/finalise").status_code == 204


def test_an_unacknowledged_instrument_with_activity_blocks_finalisation(db, client):
    """An arrival nobody has classified blocks finalisation — it waits in the
    inbox, and the Admin's decision resolves the blocker."""
    account, _, btc, _, _ = _round_trip(db)
    _price(db, btc)
    token = instruments.create_crypto_token(
        db,
        symbol="AAA",
        name="Airdropped token",
        chain="ethereum",
        contract_address="0x" + "a" * 40,
    )
    _transfer_in(db, account, token, quantity="100", occurred_at=SOLD)
    report_id = client.post("/api/reports", json={"year": 2025}).json()["id"]

    refused = client.post(f"/api/reports/{report_id}/finalise")

    blocker = _blockers(refused)["unacknowledged_instruments"]
    assert blocker["resolve_path"] == "/inbox"
    assert blocker["count"] == 1
    assert "AAA" in blocker["detail"]

    # The Admin decides the arrival is dust to be ignored — ignored wherever
    # it appears, it stands outside every figure and blocks nothing.
    settled = stances.classify(db, token, stance="ignored", account_id=account)
    assert not isinstance(settled, stances.Refusal)
    assert client.post(f"/api/reports/{report_id}/finalise").status_code == 204


def test_a_lot_shortfall_blocks_finalisation(db, client):
    """A disposal exceeding the lots its Account holds blocks finalisation.
    Generation refuses over one, so the gap opens when the ledger moves under
    a draft — here the purchase behind a sale is deleted — and restoring the
    missing acquisition resolves the blocker."""
    account, eur, btc, purchase, _ = _round_trip(db)
    _price(db, btc)
    report_id = client.post("/api/reports", json={"year": 2025}).json()["id"]
    assert client.delete(f"/api/transactions/{purchase}").status_code == 204

    refused = client.post(f"/api/reports/{report_id}/finalise")

    blocker = _blockers(refused)["lot_shortfalls"]
    assert blocker["resolve_path"] == "/transactions"
    assert blocker["count"] == 1
    assert "BTC" in blocker["detail"]

    _trade(db, account, eur, btc, given="10000", gotten="1", occurred_at=BOUGHT)
    assert client.post(f"/api/reports/{report_id}/finalise").status_code == 204


# --- The override: acknowledged, recorded, shown wherever the report is -----


def test_an_override_finalises_and_is_recorded_on_the_report(store, client):
    """The Admin may override the blockers with an acknowledgement — the
    report finalises, and the acknowledgement travels with it together with
    what it overrode, in the listing and the detail alike."""
    _round_trip(store, bought_at=BOUGHT_2031, sold_at=SOLD_2031)
    _limits(store, year=2031)
    report_id = client.post("/api/reports", json={"year": 2031}).json()["id"]
    assert client.post(f"/api/reports/{report_id}/finalise").status_code == 409

    overridden = client.post(
        f"/api/reports/{report_id}/finalise",
        json={"override": {"acknowledgement": "The gaps are understood and accepted."}},
    )

    assert overridden.status_code == 204
    report = client.get(f"/api/reports/{report_id}").json()
    assert report["status"] == "final"
    assert report["override_acknowledgement"] == "The gaps are understood and accepted."
    kinds = {blocker["kind"] for blocker in report["overridden_blockers"]}
    assert "missing_statutory_configuration" in kinds
    assert "unpriced_instruments" in kinds
    (listed,) = client.get("/api/reports").json()
    assert listed["override_acknowledgement"] == report["override_acknowledgement"]
    assert listed["overridden_blockers"] == report["overridden_blockers"]


def test_an_override_without_an_acknowledgement_is_refused(store, client):
    """The acknowledgement is what makes an override deliberate — an empty
    one is no acknowledgement at all."""
    _round_trip(store, bought_at=BOUGHT_2031, sold_at=SOLD_2031)
    _limits(store, year=2031)
    report_id = client.post("/api/reports", json={"year": 2031}).json()["id"]

    refused = client.post(
        f"/api/reports/{report_id}/finalise", json={"override": {"acknowledgement": ""}}
    )

    assert refused.status_code == 422
    assert client.get(f"/api/reports/{report_id}").json()["status"] == "draft"


def test_a_clean_finalisation_records_no_override(db, client):
    """An acknowledgement offered where nothing blocks overrides nothing —
    the report finalises clean."""
    _, _, btc, _, _ = _round_trip(db)
    _price(db, btc)
    report_id = client.post("/api/reports", json={"year": 2025}).json()["id"]

    finalised = client.post(
        f"/api/reports/{report_id}/finalise",
        json={"override": {"acknowledgement": "Offered for nothing."}},
    )

    assert finalised.status_code == 204
    report = client.get(f"/api/reports/{report_id}").json()
    assert report["status"] == "final"
    assert report["override_acknowledgement"] is None
    assert report["overridden_blockers"] is None


# --- The registry is the extension point ------------------------------------


def test_a_registered_check_blocks_without_any_change_to_the_finalisation_flow(
    db, client, monkeypatch
):
    """A later ticket registers a further blocker by appending one check to
    the registry — the finalisation flow picks it up unchanged."""
    from open_leprechaun.services import preflight

    def _always_blocks(engine, year):
        return preflight.Blocker(
            kind="a_later_tickets_concern",
            detail=f"Something known to be wrong about {year}.",
            resolve_path="/somewhere",
            count=1,
        )

    monkeypatch.setattr(preflight, "CHECKS", (*preflight.CHECKS, _always_blocks))
    _, _, btc, _, _ = _round_trip(db)
    _price(db, btc)
    report_id = client.post("/api/reports", json={"year": 2025}).json()["id"]

    refused = client.post(f"/api/reports/{report_id}/finalise")

    blocker = _blockers(refused)["a_later_tickets_concern"]
    assert blocker["resolve_path"] == "/somewhere"

"""Security Instruments (ticket 44): a security added by search or by hand
carries its identifiers, its Listing and — for a fund — the Teilfreistellung
category its taxation depends on, with the source of that value shown. An
unknown identifier arriving by import auto-creates the Instrument flagged for
review rather than dropping the row, and an unclassified fund blocks report
finalisation rather than silently assuming a zero exemption.

The seams are the repository over real Postgres — the classification rules
under test are the schema's own constraints — the import evaluation, the
search service over the port's fake, and the pre-flight registry.
"""

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.ports.crypto_prices import ProviderOutageError, RateLimitedError
from open_leprechaun.ports.security_search import SecurityCandidate
from open_leprechaun.repositories import instruments, platforms, transactions
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.security_search import get_security_search
from open_leprechaun.services import securities
from open_leprechaun.services.imports import ImportLeg, ImportRow, InstrumentSpec, commit
from open_leprechaun.services.preflight import blockers

NOON = datetime(2025, 3, 14, 12, 0, tzinfo=UTC)

WORLD_ETF = {
    "symbol": "EUNL",
    "name": "iShares Core MSCI World UCITS ETF USD Acc.",
    "type": "etf",
    "isin": "IE00B4L5Y983",
}


def _fund(db, **overrides):
    created = instruments.create_security(db, **{**WORLD_ETF, **overrides})
    assert created is not None
    return created


def _row(db, instrument_id):
    return (
        db.connect()
        .execute(
            text(
                "SELECT type, symbol, name, isin, fund_category, fund_category_source,"
                " distribution_policy, needs_review FROM instrument WHERE id = :id"
            ),
            {"id": instrument_id},
        )
        .one()
    )


# --- The schema holds the classification rules --------------------------------


def test_an_unknown_typed_security_must_await_review(db):
    """Type `unknown` exists only for the auto-created row nobody has looked
    at — the schema refuses it as a settled state."""
    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO instrument (family, type, symbol, name, isin, needs_review)"
                " VALUES ('security', 'unknown', 'X', 'X', 'XS0000000000', false)"
            )
        )


def test_clearing_the_review_flag_requires_a_real_type(db):
    unknown = _fund(db, type="unknown", needs_review=True)
    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text("UPDATE instrument SET needs_review = false WHERE id = :id"), {"id": unknown}
        )


def test_classification_belongs_to_funds_alone(db):
    share = _fund(db, type="share", symbol="ALV", isin="DE0008404005", name="Allianz")
    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text(
                "UPDATE instrument SET fund_category = 'aktienfonds',"
                " fund_category_source = 'admin' WHERE id = :id"
            ),
            {"id": share},
        )


def test_a_category_always_names_its_source(db):
    fund = _fund(db)
    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text("UPDATE instrument SET fund_category = 'aktienfonds' WHERE id = :id"),
            {"id": fund},
        )


# --- Creation from a picked candidate or by hand ------------------------------


def test_a_created_security_carries_aliases_listing_and_classification(db):
    created = _fund(
        db,
        wkn="A0RPWH",
        ticker="EUNL",
        venue="gettex",
        quote_currency="EUR",
        fund_category="aktienfonds",
        fund_category_source="provider",
        distribution_policy="accumulating",
    )

    row = _row(db, created)
    assert row.fund_category == "aktienfonds"
    assert row.fund_category_source == "provider"
    assert row.distribution_policy == "accumulating"
    assert not row.needs_review
    # The WKN and ticker resolve as lookup aliases, per the identifier history.
    assert [r.id for r in instruments.find_by_identifier(db, "A0RPWH")] == [created]
    assert [r.id for r in instruments.find_by_identifier(db, "EUNL")] == [created]
    assert [
        (listing.venue, listing.quote_currency)
        for listing in instruments.list_listings(db)
        if listing.instrument_id == created
    ] == [("gettex", "EUR")]


def test_a_listing_names_venue_and_currency_together_or_not_at_all(db):
    with pytest.raises(ValueError, match="venue and quote currency"):
        instruments.create_security(db, **WORLD_ETF, venue="gettex")


def test_manual_creation_without_a_listing_is_possible(db):
    """No provider coverage: the Instrument exists with no Listing, so nothing
    can vouch for a value — unpriced, never zero."""
    created = _fund(db)
    assert [row for row in instruments.list_listings(db) if row.instrument_id == created] == []


# --- Classifying a fund -------------------------------------------------------


def test_classify_fund_records_category_source_and_policy(db):
    fund = _fund(db)

    assert instruments.classify_fund(
        db,
        fund,
        category="aktienfonds",
        source="admin",
        distribution_policy="accumulating",
    )

    row = _row(db, fund)
    assert (row.fund_category, row.fund_category_source) == ("aktienfonds", "admin")
    assert row.distribution_policy == "accumulating"


def test_the_admin_overrides_a_provider_prefill(db):
    fund = _fund(
        db,
        fund_category="mischfonds",
        fund_category_source="provider",
        distribution_policy="distributing",
    )

    assert instruments.classify_fund(
        db, fund, category="aktienfonds", source="admin", distribution_policy="distributing"
    )

    row = _row(db, fund)
    assert (row.fund_category, row.fund_category_source) == ("aktienfonds", "admin")


def test_classify_fund_refuses_a_share(db):
    share = _fund(db, type="share", symbol="ALV", isin="DE0008404005", name="Allianz")
    assert not instruments.classify_fund(
        db, share, category="aktienfonds", source="admin", distribution_policy="distributing"
    )


def test_classify_fund_refuses_a_missing_instrument(db):
    assert not instruments.classify_fund(
        db, 999999, category="aktienfonds", source="admin", distribution_policy="distributing"
    )


# --- Resolving a review -------------------------------------------------------


def test_resolving_a_review_chooses_a_type_and_clears_the_flag(db):
    unknown = _fund(db, type="unknown", needs_review=True)

    assert instruments.resolve_review(
        db, unknown, type="etf", symbol="EUNL", name=WORLD_ETF["name"]
    )

    row = _row(db, unknown)
    assert (row.type, row.needs_review) == ("etf", False)


def test_resolving_a_review_may_classify_the_fund_in_the_same_act(db):
    unknown = _fund(db, type="unknown", needs_review=True)

    assert instruments.resolve_review(
        db,
        unknown,
        type="fund",
        symbol="EUNL",
        name=WORLD_ETF["name"],
        fund_category="aktienfonds",
        fund_category_source="admin",
        distribution_policy="accumulating",
    )

    row = _row(db, unknown)
    assert (row.fund_category, row.needs_review) == ("aktienfonds", False)


def test_resolving_a_review_refuses_to_leave_the_type_unknown(db):
    unknown = _fund(db, type="unknown", needs_review=True)
    assert not instruments.resolve_review(db, unknown, type="unknown", symbol="EUNL", name="?")
    assert _row(db, unknown).needs_review


def test_a_settled_security_cannot_be_edited_through_the_review_door(db):
    """The review settles a flagged arrival — it is never a general rename or
    retype for a security nobody flagged."""
    settled = _fund(db)
    assert not instruments.resolve_review(db, settled, type="share", symbol="X", name="X")
    assert _row(db, settled).type == "etf"


def test_retyping_a_reviewed_fund_to_a_share_wipes_its_classification(db):
    """A share carries no Teilfreistellung — keeping a stale classification
    would misstate its taxation, so the review wipes it in the same act."""
    flagged = _fund(
        db,
        needs_review=True,
        fund_category="aktienfonds",
        fund_category_source="provider",
        distribution_policy="accumulating",
    )

    assert instruments.resolve_review(db, flagged, type="share", symbol="ALV", name="Allianz")

    row = _row(db, flagged)
    assert (row.type, row.fund_category, row.distribution_policy) == ("share", None, None)


# --- An unknown identifier arriving by import ---------------------------------


def _account(db):
    platform_id = platforms.create_platform(db, name="Broker", kind="broker")
    assert platform_id is not None
    # A Depot may hold nothing before its withholding behaviour is set
    # (ticket 43), so the fixture declares it the way the Admin would.
    assert platforms.set_withholding(db, platform_id, behaviour="at_source") is None
    account = platforms.create_account(db, platform_id, name="Depot")
    assert isinstance(account, int)
    return account


def _buy(external_id, eur_id, spec):
    return ImportRow(
        external_id=external_id,
        type="trade",
        occurred_at=NOON,
        legs=(
            ImportLeg(role="out", quantity=Decimal(100), instrument_id=eur_id),
            ImportLeg(role="in", quantity=Decimal("1"), instrument=spec),
        ),
    )


def test_an_imported_unknown_identifier_creates_the_instrument_flagged(db):
    """The row is never dropped: the unknown ISIN mints its Instrument, typed
    `unknown` where the source named no type, wearing the review flag."""
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    spec = InstrumentSpec(
        kind="security", symbol="EUNL", name=WORLD_ETF["name"], isin=WORLD_ETF["isin"]
    )

    committed = commit(
        db,
        source="broker-csv",
        label="a.csv",
        account_id=_account(db),
        rows=[_buy("r-1", eur, spec)],
    )

    assert committed.instruments_created == 1
    (created,) = [r.id for r in instruments.find_by_identifier(db, WORLD_ETF["isin"])]
    row = _row(db, created)
    assert (row.type, row.needs_review) == ("unknown", True)


def test_an_imported_known_identifier_resolves_without_a_flag(db):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    existing = _fund(db)
    spec = InstrumentSpec(
        kind="security",
        symbol="EUNL",
        name=WORLD_ETF["name"],
        isin=WORLD_ETF["isin"],
        security_type="etf",
    )

    committed = commit(
        db,
        source="broker-csv",
        label="a.csv",
        account_id=_account(db),
        rows=[_buy("r-1", eur, spec)],
    )

    assert committed.instruments_created == 0
    assert not _row(db, existing).needs_review


# --- Search candidates against the ledger -------------------------------------


class FakeSearch:
    name = "fake"

    def __init__(self, candidates):
        self.candidates = list(candidates)

    def search(self, query):
        return self.candidates


CANDIDATE = SecurityCandidate(
    isin=WORLD_ETF["isin"],
    wkn="A0RPWH",
    ticker="EUNL",
    name=WORLD_ETF["name"],
    type="etf",
    currency="EUR",
    venue="gettex",
    fund_category="aktienfonds",
    distribution_policy="accumulating",
)


def test_search_marks_candidates_already_in_the_ledger(db):
    existing = _fund(db)

    found = securities.search(db, FakeSearch([CANDIDATE]), "world")

    assert [entry.instrument_id for entry in found] == [existing]
    assert found[0].candidate == CANDIDATE


def test_search_marks_a_candidate_known_under_a_superseded_isin(db):
    existing = _fund(db)
    assert instruments.change_isin(db, existing, new_isin="IE0000000000")

    found = securities.search(db, FakeSearch([CANDIDATE]), "world")

    assert [entry.instrument_id for entry in found] == [existing]


def test_search_leaves_an_unknown_candidate_unmarked(db):
    found = securities.search(db, FakeSearch([CANDIDATE]), "world")
    assert [entry.instrument_id for entry in found] == [None]


# --- The unclassified fund blocks finalisation --------------------------------


def _activity(db, instrument_id, *, occurred_at=NOON):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    account = _account(db)
    created = transactions.create_transaction(
        db,
        type="trade",
        occurred_at=occurred_at,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=eur, role="out", quantity=Decimal(100)),
            Leg(account_id=account, instrument_id=instrument_id, role="in", quantity=Decimal(1)),
        ],
    )
    assert isinstance(created, int)


def _kinds(db, *, year=2025):
    return [blocker.kind for blocker in blockers(db, year=year)]


def test_an_unclassified_fund_with_activity_blocks_finalisation(db):
    fund = _fund(db)
    _activity(db, fund)

    found = [b for b in blockers(db, year=2025) if b.kind == "unclassified_funds"]

    assert len(found) == 1
    assert found[0].count == 1
    # The direct action: the screen where the fund is classified.
    assert found[0].resolve_path == "/instruments"
    assert "EUNL" in found[0].detail


def test_a_classified_fund_does_not_block(db):
    fund = _fund(db, fund_category="aktienfonds", fund_category_source="provider")
    _activity(db, fund)

    assert "unclassified_funds" not in _kinds(db)


def test_a_fund_without_activity_in_the_year_does_not_block(db):
    _fund(db)
    assert "unclassified_funds" not in _kinds(db)


def test_a_fund_bought_earlier_and_merely_held_still_blocks(db):
    """The bound is holding, not in-year trading: a held fund accrues
    Vorabpauschale, so its missing classification still moves the year."""
    fund = _fund(db)
    _activity(db, fund, occurred_at=datetime(2024, 3, 14, 12, 0, tzinfo=UTC))

    assert "unclassified_funds" in _kinds(db, year=2025)


def test_an_unknown_typed_security_with_activity_blocks(db):
    """Nothing can say whether it is a fund, so nothing can say its exemption
    — it blocks until the review settles the type."""
    unknown = _fund(db, type="unknown", needs_review=True)
    _activity(db, unknown)

    assert "unclassified_funds" in _kinds(db)


def test_a_share_with_activity_does_not_block(db):
    share = _fund(db, type="share", symbol="ALV", isin="DE0008404005", name="Allianz")
    _activity(db, share)

    assert "unclassified_funds" not in _kinds(db)


# --- The HTTP surface ---------------------------------------------------------


@pytest.fixture
def search_client(db):
    """The API bound to the test database, search through the port's fake."""
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_security_search] = lambda: FakeSearch([CANDIDATE])
    with TestClient(app) as client:
        yield client


def test_the_search_endpoint_answers_candidates_marked_where_known(search_client, db):
    existing = _fund(db)

    response = search_client.get("/api/securities/search", params={"query": "world"})

    assert response.status_code == 200
    (candidate,) = response.json()
    assert candidate["isin"] == WORLD_ETF["isin"]
    assert candidate["ticker"] == "EUNL"
    assert candidate["type"] == "etf"
    assert candidate["currency"] == "EUR"
    assert candidate["venue"] == "gettex"
    assert candidate["instrument_id"] == existing


def test_a_rate_limited_search_names_its_condition(db):
    class RateLimited:
        name = "fake"

        def search(self, query):
            raise RateLimitedError("fake asked for a pause (HTTP 429).")

    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_security_search] = lambda: RateLimited()
    with TestClient(app) as client:
        response = client.get("/api/securities/search", params={"query": "world"})

    assert response.status_code == 503
    assert "pause" in response.json()["detail"]


def test_creating_a_security_from_a_picked_candidate(client, db):
    response = client.post(
        "/api/securities",
        json={
            "isin": WORLD_ETF["isin"],
            "name": WORLD_ETF["name"],
            "symbol": "EUNL",
            "type": "etf",
            "wkn": "A0RPWH",
            "ticker": "EUNL",
            "venue": "gettex",
            "quote_currency": "EUR",
            "classification": {
                "fund_category": "aktienfonds",
                "fund_category_source": "provider",
                "distribution_policy": "accumulating",
            },
        },
    )

    assert response.status_code == 201
    created = response.json()["id"]
    row = _row(db, created)
    assert (row.fund_category, row.fund_category_source) == ("aktienfonds", "provider")
    listed = client.get("/api/instruments").json()
    (etf,) = [r for r in listed if r["id"] == created]
    (listing,) = etf["listings"]
    assert (listing["venue"], listing["quote_currency"]) == ("gettex", "EUR")
    # The picked candidate's primary listing takes the price source (ticket 45).
    assert listing["price_source"] is True
    assert etf["fund_category_source"] == "provider"
    assert not etf["needs_review"]


def test_creating_the_same_isin_twice_is_a_conflict(client, db):
    _fund(db)
    response = client.post(
        "/api/securities",
        json={"isin": WORLD_ETF["isin"], "name": "Again", "symbol": "EUNL", "type": "etf"},
    )
    assert response.status_code == 409


def test_a_classification_on_a_share_is_refused_at_creation(client):
    response = client.post(
        "/api/securities",
        json={
            "isin": "DE0008404005",
            "name": "Allianz",
            "symbol": "ALV",
            "type": "share",
            "classification": {
                "fund_category": "aktienfonds",
                "fund_category_source": "admin",
            },
        },
    )
    assert response.status_code == 422


def test_classifying_a_fund_over_the_api(client, db):
    fund = _fund(db)

    response = client.put(
        f"/api/securities/{fund}/classification",
        json={"fund_category": "aktienfonds", "distribution_policy": "accumulating"},
    )

    assert response.status_code == 204
    row = _row(db, fund)
    # The endpoint is the Admin's own act, so the server stamps the source —
    # a request cannot wear the provider's name.
    assert (row.fund_category, row.fund_category_source) == ("aktienfonds", "admin")


def test_classifying_a_share_is_refused_with_its_reason(client, db):
    share = _fund(db, type="share", symbol="ALV", isin="DE0008404005", name="Allianz")
    response = client.put(
        f"/api/securities/{share}/classification",
        json={"fund_category": "aktienfonds"},
    )
    assert response.status_code == 422
    assert "share" in response.json()["detail"]


def test_classifying_a_missing_instrument_is_not_found(client):
    response = client.put(
        "/api/securities/999999/classification",
        json={"fund_category": "aktienfonds"},
    )
    assert response.status_code == 404


def test_reviewing_an_auto_created_security_over_the_api(client, db):
    unknown = _fund(db, type="unknown", needs_review=True)

    response = client.put(
        f"/api/securities/{unknown}/review",
        json={
            "type": "etf",
            "symbol": "EUNL",
            "name": WORLD_ETF["name"],
            "classification": {
                "fund_category": "aktienfonds",
                "distribution_policy": "accumulating",
            },
        },
    )

    assert response.status_code == 204
    row = _row(db, unknown)
    assert (row.type, row.needs_review, row.fund_category) == ("etf", False, "aktienfonds")
    assert row.fund_category_source == "admin"


def test_reviewing_a_missing_security_is_not_found(client):
    response = client.put(
        "/api/securities/999999/review",
        json={"type": "share", "symbol": "X", "name": "X"},
    )
    assert response.status_code == 404


# --- The onvista implementation, against recorded responses -------------------

# Trimmed but structurally faithful answers: the query endpoint that accepts
# ISIN, WKN, ticker and name alike, and the per-candidate snapshot carrying
# currency, primary listing and — for a fund — the classification.
ONVISTA_QUERY = """{"list": [
  {"entityType": "FUND", "entitySubType": "ETF", "entityValue": "25096683",
   "name": "iShares Core MSCI World UCITS ETF USD Acc.",
   "isin": "IE00B4L5Y983", "wkn": "A0RPWH", "symbol": "EUNL"},
  {"entityType": "STOCK", "entityValue": "83219", "name": "Allianz",
   "isin": "DE0008404005", "wkn": "840400", "symbol": "ALV"},
  {"entityType": "INDEX", "entityValue": "12105789", "name": "MSCI World"}
]}"""

ONVISTA_FUND_SNAPSHOT = """{
  "quote": {"isoCurrency": "EUR", "market": {"name": "gettex"}},
  "fundsDetails": {"nameTypeFund": "Aktienfonds",
                   "fundsTypeCapitalisation": {"name": "Thesaurierend"}}
}"""

ONVISTA_STOCK_SNAPSHOT = '{"quote": {"isoCurrency": "EUR", "market": {"name": "gettex"}}}'


def _onvista(handler):
    from open_leprechaun.ports.onvista import OnvistaProvider

    return OnvistaProvider(httpx.Client(transport=httpx.MockTransport(handler)))


def _query_handler(request):
    if request.url.path.endswith("/instruments/query"):
        assert request.url.params["searchValue"] == "world"
        return httpx.Response(200, text=ONVISTA_QUERY)
    if request.url.path.endswith("/funds/25096683/snapshot"):
        return httpx.Response(200, text=ONVISTA_FUND_SNAPSHOT)
    assert request.url.path.endswith("/stocks/83219/snapshot")
    return httpx.Response(200, text=ONVISTA_STOCK_SNAPSHOT)


def test_onvista_answers_candidates_with_identity_listing_and_prefill():
    """One query, ISIN or WKN or ticker or name alike; each candidate carries
    what creation needs, and the fund's classification arrives as a prefill.
    An entity type the ledger has no security type for is skipped."""
    candidates = _onvista(_query_handler).search("world")

    assert candidates == [
        SecurityCandidate(
            isin="IE00B4L5Y983",
            wkn="A0RPWH",
            ticker="EUNL",
            name="iShares Core MSCI World UCITS ETF USD Acc.",
            type="etf",
            currency="EUR",
            venue="gettex",
            fund_category="aktienfonds",
            distribution_policy="accumulating",
        ),
        SecurityCandidate(
            isin="DE0008404005",
            wkn="840400",
            ticker="ALV",
            name="Allianz",
            type="share",
            currency="EUR",
            venue="gettex",
            fund_category=None,
            distribution_policy=None,
        ),
    ]


def test_onvista_degrades_a_candidate_whose_snapshot_fails():
    """A failing snapshot costs that candidate its enrichment, never the
    whole search — a picker with a gap beats no picker."""

    def handler(request):
        if request.url.path.endswith("/instruments/query"):
            return httpx.Response(200, text=ONVISTA_QUERY)
        return httpx.Response(503)

    candidates = _onvista(handler).search("world")

    assert [c.isin for c in candidates] == ["IE00B4L5Y983", "DE0008404005"]
    assert all(c.currency is None and c.venue is None for c in candidates)
    assert candidates[0].fund_category is None


def test_onvista_surfaces_a_rate_limit_as_its_own_condition():
    with pytest.raises(RateLimitedError):
        _onvista(lambda request: httpx.Response(429)).search("world")


def test_onvista_surfaces_any_other_failure_as_an_outage():
    with pytest.raises(ProviderOutageError):
        _onvista(lambda request: httpx.Response(500)).search("world")

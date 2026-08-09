"""Futures fills, positions and funding (ticket 28, ADR-0009): fills are the
immutable, deduplicated source of truth; positions are a pure derivation of
the ordered fill sequence per stream, rebuilt wholesale per source; funding
is attributed to the position open at its payment instant; and a closed
position emits one Section 20 Event in the termingeschaefte pot — computing
no tax of its own (ADR-0013).

Two seams: the pure derivation (`futures.derive` — fills in, positions and
issues out, no database), and the sync/attribution/emission path over real
Postgres.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.ports.reference_rates import ReferenceRate
from open_leprechaun.rates import get_reference_rate_source
from open_leprechaun.repositories import instruments, platforms, statutory
from open_leprechaun.services import futures, preflight, section20
from open_leprechaun.services.futures import NormalizedFill

AN_INSTANT = datetime(2031, 3, 2, 10, 0, tzinfo=UTC)


def _at(minutes):
    return AN_INSTANT + timedelta(minutes=minutes)


def _fill(
    side,
    price,
    size,
    *,
    minute=0,
    fee="0",
    symbol="BTC-PERP",
    account=1,
    settlement=7,
    external_id=None,
    position_side=None,
    reduce_only=None,
    realized=None,
):
    return NormalizedFill(
        external_id=external_id or f"fill-{minute}-{side}-{price}",
        account_id=account,
        symbol=symbol,
        side=side,
        price=Decimal(price),
        size=Decimal(size),
        fee=Decimal(fee),
        settlement_instrument_id=settlement,
        occurred_at=_at(minute),
        position_side=position_side,
        reduce_only=reduce_only,
        realized=Decimal(realized) if realized is not None else None,
    )


# --- The pure derivation: net accounting -------------------------------------


def test_a_buy_then_a_matching_sell_derives_one_closed_long():
    """The documented net accounting (ADR-0009): a buy opens a long, the
    matching sell closes it — realised result is the price difference, fees
    are the fills' summed, and the position wears the fills' instants."""
    derivation = futures.derive(
        [
            _fill("buy", "100", "2", minute=0, fee="1"),
            _fill("sell", "110", "2", minute=30, fee="1.5"),
        ]
    )

    assert derivation.issues == ()
    (position,) = derivation.positions
    assert position.side == "long"
    assert position.quantity == Decimal("2")
    assert position.realized == Decimal("20")
    assert position.fees == Decimal("2.5")
    assert position.opened_at == _at(0)
    assert position.closed_at == _at(30)
    assert position.symbol == "BTC-PERP"
    assert position.account_id == 1
    assert position.settlement_instrument_id == 7


def test_a_sell_first_opens_a_short_and_the_buy_back_closes_it():
    """Without enrichment a first sell can only mean a short: the buy-back
    realises entry minus exit."""
    derivation = futures.derive(
        [
            _fill("sell", "200", "1", minute=0),
            _fill("buy", "150", "1", minute=10),
        ]
    )

    (position,) = derivation.positions
    assert position.side == "short"
    assert position.closed_at == _at(10)
    assert position.realized == Decimal("50")


def test_extending_fills_average_the_entry_price():
    """Net accounting values a reduction against the average entry of what
    is open — 1 @ 100 and 1 @ 200 close at 180 for 60, not for 80 + (-20)
    fill by fill."""
    derivation = futures.derive(
        [
            _fill("buy", "100", "1", minute=0),
            _fill("buy", "200", "1", minute=5),
            _fill("sell", "180", "2", minute=10),
        ]
    )

    (position,) = derivation.positions
    assert position.realized == Decimal("60")
    assert position.quantity == Decimal("2")


def test_a_fill_crossing_zero_closes_the_long_and_opens_a_short():
    """A sell larger than the long both closes it and opens a short with the
    remainder — the crossing fill's fee splits pro rata, so no fee is
    counted twice."""
    derivation = futures.derive(
        [
            _fill("buy", "100", "2", minute=0, fee="2"),
            _fill("sell", "110", "5", minute=20, fee="5"),
        ]
    )

    assert derivation.issues == ()
    closed, opened = derivation.positions
    assert closed.side == "long"
    assert closed.realized == Decimal("20")
    assert closed.fees == Decimal("4")
    assert closed.closed_at == _at(20)
    assert opened.side == "short"
    assert opened.quantity == Decimal("3")
    assert opened.closed_at is None
    assert opened.fees == Decimal("3")
    assert opened.opened_at == _at(20)


def test_an_open_position_carries_no_close_and_keeps_partial_realisation():
    """A partly reduced position stays one open position: what the partial
    close realised is recorded on it, and it counts in no year until the
    position itself closes (ticket 28)."""
    derivation = futures.derive(
        [
            _fill("buy", "100", "2", minute=0),
            _fill("sell", "130", "1", minute=15),
        ]
    )

    (position,) = derivation.positions
    assert position.closed_at is None
    assert position.realized == Decimal("30")
    assert position.quantity == Decimal("2")


def test_streams_are_separate_per_account_and_symbol():
    derivation = futures.derive(
        [
            _fill("buy", "100", "1", minute=0, symbol="BTC-PERP"),
            _fill("buy", "10", "1", minute=1, symbol="ETH-PERP"),
            _fill("sell", "110", "1", minute=2, symbol="BTC-PERP"),
            _fill("sell", "12", "1", minute=3, symbol="ETH-PERP"),
            _fill("buy", "100", "1", minute=0, symbol="BTC-PERP", account=2),
        ]
    )

    assert {(p.symbol, p.account_id) for p in derivation.positions} == {
        ("BTC-PERP", 1),
        ("ETH-PERP", 1),
        ("BTC-PERP", 2),
    }


def test_fills_derive_in_timestamp_order_regardless_of_input_order():
    """Derivation is a function of the ordered fill sequence (ADR-0009) —
    the order fills arrived in a sync window must not matter."""
    fills = [
        _fill("sell", "110", "1", minute=30),
        _fill("buy", "100", "1", minute=0),
    ]

    (position,) = futures.derive(fills).positions

    assert position.side == "long"
    assert position.realized == Decimal("10")


# --- Enrichment: position side, reduce-only, per-fill realised result --------


def test_the_venue_s_per_fill_realised_result_is_used_where_stated():
    """Where the venue states a fill's realised result, derivation uses it
    verbatim rather than computing (ADR-0009) — the venue knows its own
    accounting exactly."""
    derivation = futures.derive(
        [
            _fill("buy", "100", "1", minute=0),
            _fill("sell", "110", "1", minute=10, realized="9.87"),
        ]
    )

    (position,) = derivation.positions
    assert position.realized == Decimal("9.87")


def test_position_side_separates_hedge_mode_streams():
    """A venue in hedge mode runs a long and a short on the same symbol at
    once; position side keeps the streams apart instead of netting them into
    nothing."""
    derivation = futures.derive(
        [
            _fill("buy", "100", "1", minute=0, position_side="long"),
            _fill("sell", "100", "1", minute=1, position_side="short"),
            _fill("sell", "120", "1", minute=10, position_side="long"),
            _fill("buy", "90", "1", minute=11, position_side="short"),
        ]
    )

    assert derivation.issues == ()
    by_side = {position.side: position for position in derivation.positions}
    assert by_side["long"].realized == Decimal("20")
    assert by_side["short"].realized == Decimal("10")
    assert by_side["long"].closed_at == _at(10)


def test_a_reduce_only_fill_with_nothing_open_is_an_issue_not_a_guess():
    """A reduce-only fill that the reconstruction would have open a position
    contradicts the venue's own flag — the opening fills predate what the
    source returned, so the stream is flagged for manual handling rather
    than guessed (ADR-0009)."""
    derivation = futures.derive([_fill("sell", "110", "1", minute=0, reduce_only=True)])

    assert derivation.positions == ()
    (issue,) = derivation.issues
    assert issue.symbol == "BTC-PERP"
    assert issue.account_id == 1


def test_a_hedge_stream_reduction_exceeding_the_open_quantity_is_an_issue():
    """In a position-side stream nothing can flip: closing more than is open
    means missing history, never a new position in the other direction."""
    derivation = futures.derive(
        [
            _fill("buy", "100", "1", minute=0, position_side="long"),
            _fill("sell", "110", "3", minute=10, position_side="long"),
        ]
    )

    assert derivation.positions == ()
    (issue,) = derivation.issues
    assert issue.position_side == "long"


def test_a_reduce_only_fill_that_would_flip_is_an_issue():
    """Reduce-only caps a fill at the open quantity; a stored size beyond it
    cannot be reconciled with the flag, so nothing is derived for the
    stream."""
    derivation = futures.derive(
        [
            _fill("buy", "100", "1", minute=0),
            _fill("sell", "110", "3", minute=10, reduce_only=True),
        ]
    )

    assert derivation.positions == ()
    assert len(derivation.issues) == 1


def test_an_issue_withdraws_the_whole_stream_but_no_other():
    """A stream that does not reconcile derives nothing at all — a half
    truth would wear the confidence of a whole one — while other streams
    stand untouched."""
    derivation = futures.derive(
        [
            _fill("sell", "110", "1", minute=0, reduce_only=True, symbol="BTC-PERP"),
            _fill("buy", "100", "1", minute=0, symbol="ETH-PERP"),
            _fill("sell", "110", "1", minute=5, symbol="ETH-PERP"),
        ]
    )

    (position,) = derivation.positions
    assert position.symbol == "ETH-PERP"
    (issue,) = derivation.issues
    assert issue.symbol == "BTC-PERP"


# --- Storage: dedupe, wholesale rebuild, one shared position model -----------


def _account(db, platform_name="OKX", name="Main"):
    platform_id = platforms.create_platform(db, name=platform_name, kind="exchange")
    created = platforms.create_account(db, platform_id, name=name)
    assert isinstance(created, int)
    return created


def _usd(db):
    created = instruments.create_cash(db, symbol="USD", name="US Dollar")
    assert isinstance(created, int)
    return created


def _eur_numeraire(db):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    return eur


def _funding(
    minute,
    amount,
    *,
    symbol="BTC-PERP",
    account=1,
    settlement=7,
    external_id=None,
    position_side=None,
):
    return futures.NormalizedFunding(
        external_id=external_id or f"funding-{minute}",
        account_id=account,
        symbol=symbol,
        amount=Decimal(amount),
        settlement_instrument_id=settlement,
        occurred_at=_at(minute),
        position_side=position_side,
    )


def test_a_resync_over_an_overlapping_window_stores_and_counts_nothing_twice(db):
    """ADR-0009: fills are deduplicated on source and external identifier
    and positions are rebuilt wholesale — the same window synced twice
    leaves exactly the rows one sync left."""
    account, usd = _account(db), _usd(db)
    fills = [
        _fill("buy", "100", "2", minute=0, fee="1", account=account, settlement=usd),
        _fill("sell", "110", "2", minute=30, fee="1", account=account, settlement=usd),
    ]

    first = futures.sync(db, source="okx:futures", fills=fills)
    second = futures.sync(db, source="okx:futures", fills=fills)

    assert first.new_fills == 2
    assert second.new_fills == 0
    (position,) = futures.overview(db).positions
    assert position.realized == Decimal("20")
    assert position.origin == "derived"
    assert position.source == "okx:futures"


def test_a_rebuild_replaces_one_source_and_leaves_the_other_standing(db):
    """Derived positions are wiped and rebuilt per source — another source's
    reconstruction is a different venue's statement and stays untouched."""
    account, usd = _account(db), _usd(db)
    futures.sync(
        db,
        source="okx:futures",
        fills=[
            _fill("buy", "100", "1", minute=0, account=account, settlement=usd),
            _fill("sell", "110", "1", minute=5, account=account, settlement=usd),
        ],
    )
    futures.sync(
        db,
        source="coinbase:futures",
        fills=[
            _fill("buy", "50", "1", minute=0, symbol="ETH-PERP", account=account, settlement=usd),
        ],
    )

    late = futures.sync(
        db,
        source="okx:futures",
        fills=[_fill("buy", "90", "1", minute=60, account=account, settlement=usd)],
    )

    assert late.new_fills == 1
    positions = futures.overview(db).positions
    assert {(p.source, p.symbol) for p in positions} == {
        ("okx:futures", "BTC-PERP"),
        ("coinbase:futures", "ETH-PERP"),
    }
    # The okx reconstruction now spans all three fills: one closed, one open.
    okx = [p for p in positions if p.source == "okx:futures"]
    assert {p.closed_at is None for p in okx} == {True, False}


def test_manual_and_derived_positions_share_one_model(db):
    """Only the origin differs (ADR-0009): a manually entered position sits
    in the same table, shows in the same overview, and will meet the same
    tax treatment."""
    account, usd = _account(db), _usd(db)
    created = futures.record_manual_position(
        db,
        futures.FuturesPosition(
            account_id=account,
            symbol="BTC-PERP",
            side="long",
            quantity=Decimal("1"),
            settlement_instrument_id=usd,
            opened_at=_at(0),
            closed_at=_at(120),
            realized=Decimal("250"),
            fees=Decimal("3"),
        ),
    )

    assert isinstance(created, int)
    (position,) = futures.overview(db).positions
    assert position.origin == "manual"
    assert position.source is None
    assert position.net == Decimal("247")


def test_a_manual_position_against_a_missing_foundation_is_refused_by_name(db):
    account, usd = _account(db), _usd(db)
    manual = futures.FuturesPosition(
        account_id=account,
        symbol="BTC-PERP",
        side="long",
        quantity=Decimal("1"),
        settlement_instrument_id=usd,
        opened_at=_at(0),
        closed_at=None,
        realized=Decimal("0"),
        fees=Decimal("0"),
    )

    assert (
        futures.record_manual_position(db, replace(manual, account_id=999999))
        is futures.Refusal.no_such_account
    )
    assert (
        futures.record_manual_position(db, replace(manual, settlement_instrument_id=999999))
        is futures.Refusal.no_such_instrument
    )


def test_a_derived_position_refuses_manual_revision_and_removal(db):
    """A derived position is the fills' statement — corrected by correcting
    the fills, never edited in place."""
    account, usd = _account(db), _usd(db)
    futures.sync(
        db,
        source="okx:futures",
        fills=[_fill("buy", "100", "1", minute=0, account=account, settlement=usd)],
    )
    (derived,) = futures.overview(db).positions
    manual = futures.FuturesPosition(
        account_id=account,
        symbol="BTC-PERP",
        side="long",
        quantity=Decimal("1"),
        settlement_instrument_id=usd,
        opened_at=_at(0),
        closed_at=None,
        realized=Decimal("0"),
        fees=Decimal("0"),
    )

    assert futures.replace_manual_position(db, derived.id, manual) is futures.Refusal.not_manual
    assert futures.delete_manual_position(db, derived.id) is futures.Refusal.not_manual
    assert futures.replace_manual_position(db, 999999, manual) is futures.Refusal.no_such_position
    assert futures.delete_manual_position(db, 999999) is futures.Refusal.no_such_position


# --- Funding: attributed to the position open at the payment instant ---------


def test_funding_is_attributed_to_the_position_open_at_the_payment_instant(db):
    """A payment inside the open interval lands on that position and counts
    toward its net; funding, fees and realised result stay separately
    stated."""
    account, usd = _account(db), _usd(db)
    futures.sync(
        db,
        source="okx:futures",
        fills=[
            _fill("buy", "100", "1", minute=0, fee="1", account=account, settlement=usd),
            _fill("sell", "110", "1", minute=60, fee="1", account=account, settlement=usd),
        ],
        funding=[
            _funding(30, "-0.75", account=account, settlement=usd),
            _funding(45, "0.25", account=account, settlement=usd),
        ],
    )

    overview = futures.overview(db)
    assert overview.unattributable_funding == ()
    (position,) = overview.positions
    assert position.realized == Decimal("10")
    assert position.fees == Decimal("2")
    assert position.funding == Decimal("-0.5")
    assert position.net == Decimal("7.5")


def test_funding_outside_any_open_interval_is_surfaced_never_dropped(db):
    """A payment with no position open for its symbol at its instant stays
    stored and is surfaced as unattributable — including one at the closing
    instant, which the half-open interval no longer covers."""
    account, usd = _account(db), _usd(db)
    futures.sync(
        db,
        source="okx:futures",
        fills=[
            _fill("buy", "100", "1", minute=0, account=account, settlement=usd),
            _fill("sell", "110", "1", minute=60, account=account, settlement=usd),
        ],
        funding=[
            _funding(60, "-0.10", account=account, settlement=usd),
            _funding(600, "-0.20", account=account, settlement=usd),
        ],
    )

    overview = futures.overview(db)
    (position,) = overview.positions
    assert position.funding == Decimal("0")
    assert [payment.amount for payment in overview.unattributable_funding] == [
        Decimal("-0.10"),
        Decimal("-0.20"),
    ]


def test_funding_with_both_hedge_positions_open_is_unattributable(db):
    """With a hedge-mode long and short both open at the payment instant no
    single position can claim the payment — it is surfaced rather than
    guessed onto one of them."""
    account, usd = _account(db), _usd(db)
    futures.sync(
        db,
        source="okx:futures",
        fills=[
            _fill(
                "buy",
                "100",
                "1",
                minute=0,
                account=account,
                settlement=usd,
                position_side="long",
                external_id="l1",
            ),
            _fill(
                "sell",
                "100",
                "1",
                minute=0,
                account=account,
                settlement=usd,
                position_side="short",
                external_id="s1",
            ),
        ],
        funding=[_funding(30, "-0.30", account=account, settlement=usd)],
    )

    overview = futures.overview(db)
    assert len(overview.positions) == 2
    (payment,) = overview.unattributable_funding
    assert payment.amount == Decimal("-0.30")


def test_funding_wearing_a_position_side_attributes_between_open_hedge_positions(db):
    """Enrichment resolves the hedge-mode tie: a payment the venue marks as
    the short side's lands on the short position even while the long stands
    open beside it."""
    account, usd = _account(db), _usd(db)
    futures.sync(
        db,
        source="okx:futures",
        fills=[
            _fill(
                "buy",
                "100",
                "1",
                minute=0,
                account=account,
                settlement=usd,
                position_side="long",
                external_id="l1",
            ),
            _fill(
                "sell",
                "100",
                "1",
                minute=0,
                account=account,
                settlement=usd,
                position_side="short",
                external_id="s1",
            ),
        ],
        funding=[_funding(30, "0.30", account=account, settlement=usd, position_side="short")],
    )

    overview = futures.overview(db)
    assert overview.unattributable_funding == ()
    funded = {position.side: position.funding for position in overview.positions}
    assert funded == {"short": Decimal("0.30"), "long": Decimal("0")}


def test_funding_attributes_to_a_manual_position_like_a_derived_one(db):
    """One model, one attribution rule: a payment inside a manual position's
    open interval lands on it exactly as it would on a derived one."""
    account, usd = _account(db), _usd(db)
    futures.record_manual_position(
        db,
        futures.FuturesPosition(
            account_id=account,
            symbol="BTC-PERP",
            side="short",
            quantity=Decimal("2"),
            settlement_instrument_id=usd,
            opened_at=_at(0),
            closed_at=_at(120),
            realized=Decimal("40"),
            fees=Decimal("1"),
        ),
    )
    futures.sync(
        db,
        source="okx:futures",
        funding=[_funding(30, "0.60", account=account, settlement=usd)],
    )

    (position,) = futures.overview(db).positions
    assert position.funding == Decimal("0.60")
    assert position.net == Decimal("39.60")


def test_a_rebuild_reattributes_funding_to_the_moved_interval(db):
    """Attribution is recomputed on every rebuild: a late-arriving closing
    fill that shortens the reconstruction's open interval takes the payment
    with it."""
    account, usd = _account(db), _usd(db)
    futures.sync(
        db,
        source="okx:futures",
        fills=[_fill("buy", "100", "1", minute=0, account=account, settlement=usd)],
        funding=[_funding(90, "-0.40", account=account, settlement=usd)],
    )
    assert futures.overview(db).unattributable_funding == ()

    futures.sync(
        db,
        source="okx:futures",
        fills=[_fill("sell", "110", "1", minute=60, account=account, settlement=usd)],
    )

    overview = futures.overview(db)
    (position,) = overview.positions
    assert position.funding == Decimal("0")
    (payment,) = overview.unattributable_funding
    assert payment.amount == Decimal("-0.40")


def test_an_unreconcilable_stream_is_stored_as_an_issue(db):
    """ADR-0009: a stream the flags contradict derives nothing and stands
    flagged for manual handling until its fills say otherwise."""
    account, usd = _account(db), _usd(db)
    futures.sync(
        db,
        source="okx:futures",
        fills=[
            _fill("sell", "110", "1", minute=0, account=account, settlement=usd, reduce_only=True)
        ],
    )

    overview = futures.overview(db)
    assert overview.positions == ()
    (issue,) = overview.derivation_issues
    assert issue.source == "okx:futures"
    assert issue.symbol == "BTC-PERP"
    assert "predate" in issue.reason


# --- The emitter: a closed position becomes one Section 20 Event -------------


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


def _statutes(store, *, year):
    """What the §20 assessment reads, plus the §23/§22 Freigrenzen the whole
    report generation requires."""
    for key, value in (
        ("saver_allowance_single", "1000"),
        ("flat_rate", "0.25"),
        ("solidarity_surcharge_rate", "0.055"),
        ("private_sale_exemption_limit", "1000"),
        ("other_income_exemption_limit", "1000"),
    ):
        statutory.upsert_value(
            store, year=year, key=key, value=Decimal(value), source="a test value"
        )


def _usd_rate(on, rate="1.25"):
    return ReferenceRate(currency="USD", rate_date=on, rate=Decimal(rate))


def _pots(report):
    return {balance.category: balance for balance in report.balances}


def test_a_closed_position_emits_one_termingeschaefte_event_and_no_tax(store):
    """§20 Abs. 2 Satz 1 Nr. 3 EStG: the gain from a Termingeschäft is
    capital income in its own pot (ADR-0013). The emitted gross is the net
    figure — realised result less trading fees plus attributed funding —
    converted by the reference rate of the close date, and nothing here
    states a euro of tax: the engine alone decides."""
    _statutes(store, year=2031)
    account, usd = _account(store), _usd(store)
    futures.sync(
        store,
        source="okx:futures",
        fills=[
            _fill("buy", "100", "1", minute=0, fee="1", account=account, settlement=usd),
            _fill("sell", "150", "1", minute=60, fee="1", account=account, settlement=usd),
        ],
        funding=[_funding(30, "-8", account=account, settlement=usd)],
    )

    report = section20.year_report(
        store, FakeReferenceRateSource([_usd_rate(AN_INSTANT.date())]), year=2031
    )

    assert report.awaiting_valuation == ()
    pots = _pots(report)
    # (50 - 2 - 8) USD at 1.25 per EUR = 32 EUR.
    assert pots["termingeschaefte"].balance_eur == Decimal("32")
    (entry,) = pots["termingeschaefte"].entries
    (position,) = futures.overview(store).positions
    assert entry.event.source == f"futures_position:{position.id}"
    assert entry.event.category == "termingeschaefte"
    assert pots["aktien"].balance_eur == Decimal(0)
    assert pots["sonstige"].balance_eur == Decimal(0)


def test_an_open_position_counts_in_no_year(store):
    """An open position has realised nothing the year can tax — it emits no
    event, however much a partial reduction already realised."""
    _statutes(store, year=2031)
    account, usd = _account(store), _usd(store)
    futures.sync(
        store,
        source="okx:futures",
        fills=[
            _fill("buy", "100", "2", minute=0, account=account, settlement=usd),
            _fill("sell", "150", "1", minute=60, account=account, settlement=usd),
        ],
    )

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    assert _pots(report)["termingeschaefte"].balance_eur == Decimal(0)
    assert _pots(report)["termingeschaefte"].entries == ()


def test_a_position_counts_in_the_berlin_year_it_closed(store):
    """The Tax Year follows the close's Europe/Berlin local date: a close in
    the first UTC hour of New Year's Eve midnight already belongs to the new
    year, and the opening year never sees it."""
    _statutes(store, year=2031)
    _statutes(store, year=2032)
    account, eur = _account(store), _eur_numeraire(store)
    futures.record_manual_position(
        store,
        futures.FuturesPosition(
            account_id=account,
            symbol="EUR-BTC-PERP",
            side="long",
            quantity=Decimal("1"),
            settlement_instrument_id=eur,
            opened_at=datetime(2031, 11, 1, 12, 0, tzinfo=UTC),
            # 23:30 UTC on New Year's Eve is 00:30 in Berlin, 2032.
            closed_at=datetime(2031, 12, 31, 23, 30, tzinfo=UTC),
            realized=Decimal("400"),
            fees=Decimal("0"),
        ),
    )

    closing_year = section20.year_report(store, FakeReferenceRateSource(), year=2031)
    new_year = section20.year_report(store, FakeReferenceRateSource(), year=2032)

    assert _pots(closing_year)["termingeschaefte"].balance_eur == Decimal(0)
    assert _pots(new_year)["termingeschaefte"].balance_eur == Decimal("400")


def test_a_manual_and_a_derived_close_meet_one_tax_treatment(store):
    """One model, one treatment: both origins reduce to the same event shape
    in the same pot, and net within it like any two events."""
    _statutes(store, year=2031)
    account, eur = _account(store), _eur_numeraire(store)
    futures.sync(
        store,
        source="okx:futures",
        fills=[
            _fill("buy", "100", "1", minute=0, account=account, settlement=eur),
            _fill("sell", "150", "1", minute=60, account=account, settlement=eur),
        ],
    )
    futures.record_manual_position(
        store,
        futures.FuturesPosition(
            account_id=account,
            symbol="ETH-PERP",
            side="short",
            quantity=Decimal("2"),
            settlement_instrument_id=eur,
            opened_at=_at(0),
            closed_at=_at(90),
            realized=Decimal("-20"),
            fees=Decimal("1"),
        ),
    )

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    pot = _pots(report)["termingeschaefte"]
    assert pot.balance_eur == Decimal("29")
    assert len(pot.entries) == 2


def test_a_settlement_only_a_crypto_price_can_value_waits_named(store):
    """A settlement the reference-rate universe cannot state — a coin, not a
    stablecoin — leaves the year unstated exactly like an unvalued leg, and
    the report names the position it waits on."""
    _statutes(store, year=2031)
    account = _account(store)
    _eur_numeraire(store)
    btc = instruments.create_native_coin(store, symbol="BTC", name="Bitcoin", chain="bitcoin")
    created = futures.record_manual_position(
        store,
        futures.FuturesPosition(
            account_id=account,
            symbol="BTC-USD-INVERSE",
            side="long",
            quantity=Decimal("1"),
            settlement_instrument_id=btc,
            opened_at=_at(0),
            closed_at=_at(60),
            realized=Decimal("0.01"),
            fees=Decimal("0"),
        ),
    )

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    assert report.balances is None
    assert report.assessment is None
    assert report.awaiting_valuation == (f"futures_position:{created}",)


# --- Pre-flight: what the app already knows is wrong blocks finalisation ----


def test_unattributable_funding_blocks_the_year_it_falls_in(db):
    """A payment no position could claim is part of some net figure the year
    cannot state — it blocks finalisation up to its own Berlin year and not
    before."""
    account, usd = _account(db), _usd(db)
    futures.sync(
        db,
        source="okx:futures",
        funding=[_funding(0, "-0.50", account=account, settlement=usd)],
    )

    kinds_2031 = {blocker.kind for blocker in preflight.blockers(db, year=2031)}
    kinds_2030 = {blocker.kind for blocker in preflight.blockers(db, year=2030)}

    assert "unattributable_funding" in kinds_2031
    assert "unattributable_funding" not in kinds_2030


def test_a_derivation_issue_blocks_every_year(db):
    """A stream flagged for manual handling (ADR-0009) could move any
    year's figures — its missing history has no year of its own."""
    account, usd = _account(db), _usd(db)
    futures.sync(
        db,
        source="okx:futures",
        fills=[
            _fill("sell", "110", "1", minute=0, account=account, settlement=usd, reduce_only=True)
        ],
    )

    blockers = {blocker.kind: blocker for blocker in preflight.blockers(db, year=2025)}

    assert "futures_derivation_issues" in blockers
    assert "BTC-PERP" in blockers["futures_derivation_issues"].detail


# --- Staleness: a report rests on the futures inputs that produced it --------


def test_a_new_fill_marks_a_generated_report_stale(store, client):
    """The report fingerprint covers the futures inputs (ADR-0014): a fill
    arriving after generation says the ground moved — the frozen figures
    stand, flagged, never silently recomputed."""
    _statutes(store, year=2031)
    account, eur = _account(store), _eur_numeraire(store)
    futures.sync(
        store,
        source="okx:futures",
        fills=[
            _fill("buy", "100", "1", minute=0, account=account, settlement=eur),
            _fill("sell", "150", "1", minute=60, account=account, settlement=eur),
        ],
    )
    generated = client.post("/api/reports", json={"year": 2031})
    assert generated.status_code == 201
    report_id = generated.json()["id"]
    assert client.get(f"/api/reports/{report_id}").json()["stale"] is False

    futures.sync(
        store,
        source="okx:futures",
        fills=[_fill("buy", "90", "1", minute=120, account=account, settlement=eur)],
    )

    report = client.get(f"/api/reports/{report_id}").json()
    assert report["stale"] is True
    assert "futures_fills" in {entry["input_class"] for entry in report["changed_inputs"]}


# --- The API: manual entry and the surfaced overview -------------------------


def test_the_api_records_lists_revises_and_removes_a_manual_position(db, client):
    account, usd = _account(db), _usd(db)
    payload = {
        "account_id": account,
        "symbol": "BTC-PERP",
        "side": "long",
        "quantity": "1.5",
        "settlement_instrument_id": usd,
        "opened_at": "2031-03-02T10:00:00Z",
        "closed_at": "2031-04-02T10:00:00Z",
        "realized": "120",
        "fees": "2.5",
    }

    created = client.post("/api/futures/positions", json=payload)
    assert created.status_code == 201
    position_id = created.json()["id"]

    listed = client.get("/api/futures")
    assert listed.status_code == 200
    (position,) = listed.json()["positions"]
    assert position["origin"] == "manual"
    assert position["source"] is None
    assert position["realized"] == "120"
    assert position["fees"] == "2.5"
    assert position["funding"] == "0"
    assert position["net"] == "117.5"

    revised = client.put(
        f"/api/futures/positions/{position_id}", json={**payload, "realized": "-30"}
    )
    assert revised.status_code == 204
    (position,) = client.get("/api/futures").json()["positions"]
    assert position["net"] == "-32.5"

    removed = client.delete(f"/api/futures/positions/{position_id}")
    assert removed.status_code == 204
    assert client.get("/api/futures").json()["positions"] == []


def test_the_api_refuses_to_touch_a_derived_position(db, client):
    account, usd = _account(db), _usd(db)
    futures.sync(
        db,
        source="okx:futures",
        fills=[_fill("buy", "100", "1", minute=0, account=account, settlement=usd)],
    )
    (derived,) = futures.overview(db).positions

    revised = client.put(
        f"/api/futures/positions/{derived.id}",
        json={
            "account_id": account,
            "symbol": "BTC-PERP",
            "side": "long",
            "quantity": "1",
            "settlement_instrument_id": usd,
            "opened_at": "2031-03-02T10:00:00Z",
            "closed_at": None,
            "realized": "0",
            "fees": "0",
        },
    )
    removed = client.delete(f"/api/futures/positions/{derived.id}")

    assert revised.status_code == 409
    assert removed.status_code == 409
    assert "fills" in revised.json()["detail"]


def test_the_api_surfaces_unattributable_funding_and_issues(db, client):
    account, usd = _account(db), _usd(db)
    futures.sync(
        db,
        source="okx:futures",
        fills=[
            _fill("sell", "110", "1", minute=0, account=account, settlement=usd, reduce_only=True)
        ],
        funding=[_funding(0, "-0.50", symbol="ETH-PERP", account=account, settlement=usd)],
    )

    answered = client.get("/api/futures").json()

    (payment,) = answered["unattributable_funding"]
    assert payment["amount"] == "-0.50"
    assert payment["symbol"] == "ETH-PERP"
    (issue,) = answered["derivation_issues"]
    assert issue["symbol"] == "BTC-PERP"
    assert issue["reason"]


def test_the_api_refuses_an_amount_arriving_as_a_json_number(db, client):
    """A JSON number has been through a binary float — an amount crosses as
    a fixed-point decimal string or not at all."""
    account, usd = _account(db), _usd(db)

    refused = client.post(
        "/api/futures/positions",
        json={
            "account_id": account,
            "symbol": "BTC-PERP",
            "side": "long",
            "quantity": 1.5,
            "settlement_instrument_id": usd,
            "opened_at": "2031-03-02T10:00:00Z",
            "closed_at": None,
            "realized": "0",
            "fees": "0",
        },
    )

    assert refused.status_code == 422


def test_the_api_refuses_a_close_before_the_opening(db, client):
    account, usd = _account(db), _usd(db)

    refused = client.post(
        "/api/futures/positions",
        json={
            "account_id": account,
            "symbol": "BTC-PERP",
            "side": "long",
            "quantity": "1",
            "settlement_instrument_id": usd,
            "opened_at": "2031-03-02T10:00:00Z",
            "closed_at": "2031-03-01T10:00:00Z",
            "realized": "0",
            "fees": "0",
        },
    )

    assert refused.status_code == 422

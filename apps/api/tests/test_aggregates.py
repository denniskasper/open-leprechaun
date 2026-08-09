"""Aggregates: bots and dust sweeps (ticket 30). Two cases where thousands
of tiny records would otherwise drown the ledger — a bot-run strategy's
futures activity, and a venue sweeping many dust balances into one coin —
are each summarised as one Aggregate whose constituents remain retrievable.

An Aggregate is presentation only: its figures are sums over its
constituents, never recomputations; the tax engines never read it; no
disposal leaves any total — only the summary presentation collapses. Tagging
membership therefore changes no figure and marks no report stale.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.rates import get_reference_rate_source
from open_leprechaun.repositories import instruments, platforms, stances
from open_leprechaun.repositories.transactions import Leg, create_transaction
from open_leprechaun.services import aggregates, futures, section20, section23
from open_leprechaun.services import transactions as transactions_service
from open_leprechaun.services.futures import NormalizedFill, NormalizedFunding

AN_INSTANT = datetime(2031, 3, 2, 10, 0, tzinfo=UTC)


def _at(minutes):
    return AN_INSTANT + timedelta(minutes=minutes)


class FakeReferenceRateSource:
    """The reference-rate port's fake: nothing here needs a foreign rate —
    settlements and sweeps are stated in the numéraire or an EUR peg."""

    def daily_rates(self, currency, start, end):
        return []


@pytest.fixture
def client(db):
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_reference_rate_source] = FakeReferenceRateSource
    with TestClient(app) as client:
        yield client


def _account(db, platform_name="Pionex", name="Main"):
    platform_id = platforms.create_platform(db, name=platform_name, kind="exchange")
    created = platforms.create_account(db, platform_id, name=name)
    assert isinstance(created, int)
    return created


def _eur(db):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    return eur


def _coin(db, symbol, chain):
    created = instruments.create_native_coin(db, symbol=symbol, name=symbol, chain=chain)
    assert isinstance(created, int)
    return created


def _keep(db, instrument, account):
    settled = stances.classify(db, instrument, stance="kept", account_id=account)
    assert not isinstance(settled, stances.Refusal)


def _euro_stablecoin(db, symbol="EURC"):
    """A token the reference-rate universe can value by identity, so a sweep
    into it needs no crypto price."""
    created = instruments.create_crypto_token(
        db,
        symbol=symbol,
        name=symbol,
        chain="ethereum",
        contract_address=f"0x{symbol.lower()}",
        pegged_currency="EUR",
    )
    assert isinstance(created, int)
    return created


def _fill(side, price, size, *, minute, account, settlement, symbol="BTC-PERP", fee="0"):
    return NormalizedFill(
        external_id=f"fill-{symbol}-{minute}-{side}",
        account_id=account,
        symbol=symbol,
        side=side,
        price=Decimal(price),
        size=Decimal(size),
        fee=Decimal(fee),
        settlement_instrument_id=settlement,
        occurred_at=_at(minute),
        inverse=False,
    )


def _funding(minute, amount, *, account, settlement, symbol="BTC-PERP"):
    return NormalizedFunding(
        external_id=f"funding-{minute}",
        account_id=account,
        symbol=symbol,
        amount=Decimal(amount),
        settlement_instrument_id=settlement,
        occurred_at=_at(minute),
    )


def _bot_cycles(db, account, settlement, *, source="pionex:bot:grid-1"):
    """Two closed cycles with fees and one attributed funding payment — the
    smallest activity whose summary already sums over several positions."""
    futures.sync(
        db,
        source=source,
        fills=[
            _fill("buy", "100", "1", minute=0, fee="1", account=account, settlement=settlement),
            _fill("sell", "110", "1", minute=30, fee="1", account=account, settlement=settlement),
            _fill("buy", "105", "2", minute=60, fee="2", account=account, settlement=settlement),
            _fill("sell", "115", "2", minute=90, fee="2", account=account, settlement=settlement),
        ],
        funding=[_funding(70, "-1", account=account, settlement=settlement)],
    )


def _trade(db, account, *, out_instrument, out_quantity, in_instrument, in_quantity, minute=0):
    created = create_transaction(
        db,
        type="trade",
        occurred_at=_at(minute),
        note=None,
        legs=[
            Leg(
                account_id=account,
                instrument_id=out_instrument,
                role="out",
                quantity=Decimal(out_quantity),
            ),
            Leg(
                account_id=account,
                instrument_id=in_instrument,
                role="in",
                quantity=Decimal(in_quantity),
            ),
        ],
    )
    assert isinstance(created, int)
    return created


def _sweep_fixture(db):
    """Two dust balances bought for EUR, then swept into an EUR stablecoin
    as two constituent trades at one instant."""
    account, eur = _account(db), _eur(db)
    pepe = _coin(db, "PEPE", "ethereum")
    shib = _coin(db, "SHIB", "shibarium")
    eurc = _euro_stablecoin(db)
    _keep(db, pepe, account)
    _keep(db, shib, account)
    _keep(db, eurc, account)
    _trade(
        db,
        account,
        out_instrument=eur,
        out_quantity="10",
        in_instrument=pepe,
        in_quantity="1000",
        minute=0,
    )
    _trade(
        db,
        account,
        out_instrument=eur,
        out_quantity="20",
        in_instrument=shib,
        in_quantity="2000",
        minute=1,
    )
    sweeps = [
        _trade(
            db,
            account,
            out_instrument=pepe,
            out_quantity="1000",
            in_instrument=eurc,
            in_quantity="12",
            minute=100,
        ),
        _trade(
            db,
            account,
            out_instrument=shib,
            out_quantity="2000",
            in_instrument=eurc,
            in_quantity="15",
            minute=100,
        ),
    ]
    return account, eur, eurc, sweeps


def _statutes(db, *, year):
    from open_leprechaun.repositories import statutory

    for key, value in (
        ("saver_allowance_single", "1000"),
        ("flat_rate", "0.25"),
        ("solidarity_surcharge_rate", "0.055"),
        ("private_sale_exemption_limit", "1000"),
        ("other_income_exemption_limit", "1000"),
    ):
        statutory.upsert_value(db, year=year, key=key, value=Decimal(value), source="a test value")


@pytest.fixture
def store(db):
    from sqlalchemy import text

    with db.begin() as connection:
        connection.execute(text("DELETE FROM statutory_value WHERE year >= 2030"))
    return db


# --- Bots: a strategy's activity summarised, its fills retrievable -----------


def test_a_bot_s_activity_is_summarised_with_its_constituent_fills_retrievable(db):
    """One aggregate summarises a source's whole derived activity — counts
    and per-settlement sums — and the fills behind it stay retrievable."""
    account, eur = _account(db), _eur(db)
    _bot_cycles(db, account, eur)

    created = aggregates.record_bot(db, label="BTC grid bot", source="pionex:bot:grid-1")

    assert isinstance(created, int)
    overview = aggregates.overview(db)
    assert overview.dust_sweeps == ()
    (bot,) = overview.bots
    assert bot.id == created
    assert bot.label == "BTC grid bot"
    assert bot.source == "pionex:bot:grid-1"
    assert bot.symbol is None
    assert bot.fill_count == 4
    assert bot.closed_positions == 2
    assert bot.open_positions == 0
    (totals,) = bot.closed_totals
    assert totals.settlement_instrument_id == eur
    assert totals.realized == Decimal("30")
    assert totals.fees == Decimal("6")
    assert totals.funding == Decimal("-1")
    assert totals.net == Decimal("23")

    constituents = aggregates.constituents(db, created)
    assert isinstance(constituents, aggregates.BotConstituents)
    assert len(constituents.fills) == 4
    assert {fill.symbol for fill in constituents.fills} == {"BTC-PERP"}
    assert len(constituents.positions) == 2
    assert all(position.aggregate_id == created for position in constituents.positions)


def test_the_capital_income_figure_from_an_aggregate_equals_the_sum_over_its_constituents(store):
    """Summarising never changes a number: the aggregate's figure is the sum
    of its constituent positions' emissions, and the pot still counts every
    event — members and non-members alike — exactly as without it."""
    _statutes(store, year=2031)
    account, eur = _account(store), _eur(store)
    _bot_cycles(store, account, eur)
    outside = futures.record_manual_position(
        store,
        futures.FuturesPosition(
            account_id=account,
            symbol="ETH-PERP",
            side="short",
            quantity=Decimal("1"),
            settlement_instrument_id=eur,
            opened_at=_at(0),
            closed_at=_at(200),
            realized=Decimal("100"),
            fees=Decimal("0"),
        ),
    )
    assert isinstance(outside, int)
    before = section20.year_report(store, FakeReferenceRateSource(), year=2031)

    created = aggregates.record_bot(store, label="BTC grid bot", source="pionex:bot:grid-1")
    assert isinstance(created, int)

    report = section20.year_report(store, FakeReferenceRateSource(), year=2031)
    pot = {balance.category: balance for balance in report.balances}["termingeschaefte"]
    member_ids = {position.id for position in aggregates.constituents(store, created).positions}
    member_events = [
        entry
        for entry in pot.entries
        if entry.event.source in {f"futures_position:{id}" for id in member_ids}
    ]
    (bot,) = aggregates.overview(store).bots
    (totals,) = bot.closed_totals
    # The aggregate's figure is the sum over its constituents (EUR
    # settlement, so the emitted gross is the net figure itself)...
    assert sum(entry.counted_eur for entry in member_events) == totals.net == Decimal("23")
    # ...and no constituent left the pot: every position still counts, and
    # nothing about the year moved by being summarised.
    assert len(pot.entries) == 3
    assert pot.balance_eur == Decimal("123")
    assert report.balances == before.balances


def test_a_foreign_settled_bot_states_its_totals_in_the_settlement_currency(db):
    """The sum-over-constituents identity holds in any settlement currency:
    the totals stay in the coin's own unit — the EUR view is the §20
    report's, where each constituent event converts at its own close date —
    and each is exactly the sum of the member positions' figures."""
    account = _account(db)
    usd = instruments.create_cash(db, symbol="USD", name="US Dollar")
    _bot_cycles(db, account, usd)

    created = aggregates.record_bot(db, label="BTC grid bot", source="pionex:bot:grid-1")
    assert isinstance(created, int)

    (bot,) = aggregates.overview(db).bots
    (totals,) = bot.closed_totals
    members = aggregates.constituents(db, created).positions
    assert totals.settlement_instrument_id == usd
    assert totals.realized == sum((position.realized for position in members), Decimal(0))
    assert totals.fees == sum((position.fees for position in members), Decimal(0))
    assert totals.funding == sum((position.funding for position in members), Decimal(0))
    assert totals.net == sum((position.net for position in members), Decimal(0)) == Decimal("23")


def test_a_bot_aggregate_narrowed_to_a_symbol_covers_only_that_stream(db):
    account, eur = _account(db), _eur(db)
    futures.sync(
        db,
        source="okx:futures",
        fills=[
            _fill("buy", "100", "1", minute=0, account=account, settlement=eur),
            _fill("sell", "110", "1", minute=30, account=account, settlement=eur),
            _fill("buy", "10", "1", minute=0, symbol="ETH-PERP", account=account, settlement=eur),
            _fill("sell", "12", "1", minute=30, symbol="ETH-PERP", account=account, settlement=eur),
        ],
    )

    created = aggregates.record_bot(db, label="BTC bot", source="okx:futures", symbol="BTC-PERP")
    assert isinstance(created, int)

    (bot,) = aggregates.overview(db).bots
    assert bot.fill_count == 2
    assert bot.closed_positions == 1
    marked = {position.symbol: position.aggregate_id for position in futures.overview(db).positions}
    assert marked == {"BTC-PERP": created, "ETH-PERP": None}


def test_overlapping_bot_scopes_are_refused(db):
    _account(db), _eur(db)

    whole = aggregates.record_bot(db, label="Whole source", source="pionex:bot:grid-1")
    assert isinstance(whole, int)

    duplicate = aggregates.record_bot(db, label="Again", source="pionex:bot:grid-1")
    narrowed = aggregates.record_bot(
        db, label="One symbol", source="pionex:bot:grid-1", symbol="BTC-PERP"
    )
    other = aggregates.record_bot(db, label="Another source", source="pionex:bot:grid-2")

    assert isinstance(duplicate, str) and "already summarises" in duplicate
    assert isinstance(narrowed, str) and "already summarises" in narrowed
    assert isinstance(other, int)


def test_two_symbol_scoped_bots_share_a_source_and_a_source_wide_bot_is_then_refused(db):
    _account(db), _eur(db)

    btc = aggregates.record_bot(db, label="BTC", source="okx:futures", symbol="BTC-PERP")
    eth = aggregates.record_bot(db, label="ETH", source="okx:futures", symbol="ETH-PERP")
    whole = aggregates.record_bot(db, label="All", source="okx:futures")

    assert isinstance(btc, int)
    assert isinstance(eth, int)
    assert isinstance(whole, str) and "already summarises" in whole


# --- Dust sweeps: one aggregate disposal, constituents retrievable -----------


def test_a_dust_sweep_is_recorded_as_one_aggregate_disposal_into_the_received_instrument(db):
    account, _eur, eurc, sweeps = _sweep_fixture(db)

    created = aggregates.record_dust_sweep(db, label="March dust sweep", transaction_ids=sweeps)

    assert isinstance(created, int)
    overview = aggregates.overview(db)
    assert overview.bots == ()
    (sweep,) = overview.dust_sweeps
    assert sweep.id == created
    assert sweep.label == "March dust sweep"
    assert sweep.constituent_count == 2
    assert sweep.received_instrument_id == eurc
    assert sweep.received_account_id == account
    assert sweep.received_quantity == Decimal("27")
    assert sweep.first_occurred_at == _at(100)
    assert sweep.last_occurred_at == _at(100)

    constituents = aggregates.constituents(db, created)
    assert isinstance(constituents, aggregates.DustSweepConstituents)
    assert {transaction.id for transaction in constituents.transactions} == set(sweeps)
    assert all(transaction.aggregate_id == created for transaction in constituents.transactions)
    # The ledger overview marks the members, so the presentation can
    # collapse them without a second lookup.
    marked = {
        transaction.id: transaction.aggregate_id
        for transaction in transactions_service.overview(db)
    }
    assert all(marked[transaction_id] == created for transaction_id in sweeps)
    assert sum(1 for aggregate in marked.values() if aggregate is None) == 2


def test_each_constituent_disposal_still_consumes_its_lots_correctly(store):
    """Aggregation is presentation: every constituent disposal keeps its own
    FIFO consumption against its own Instrument's lots, wearing the
    aggregate only as a marker."""
    _statutes(store, year=2031)
    _account, _eur, _eurc, sweeps = _sweep_fixture(store)

    created = aggregates.record_dust_sweep(store, label="Dust", transaction_ids=sweeps)
    assert isinstance(created, int)

    report = section23.year_report(store, FakeReferenceRateSource(), year=2031)
    assert len(report.disposals) == 2
    by_gain = sorted(report.disposals, key=lambda disposal: disposal.consumptions[0].gain_eur)
    # PEPE: bought for 10, swept for 12 — gain 2; SHIB: 20 in, 15 out — loss 5.
    (pepe, shib) = by_gain[1], by_gain[0]
    (pepe_consumption,) = pepe.consumptions
    assert pepe_consumption.basis_eur == Decimal("10")
    assert pepe_consumption.proceeds_eur == Decimal("12")
    assert pepe_consumption.gain_eur == Decimal("2")
    (shib_consumption,) = shib.consumptions
    assert shib_consumption.basis_eur == Decimal("20")
    assert shib_consumption.gain_eur == Decimal("-5")
    assert {disposal.aggregate_id for disposal in report.disposals} == {created}
    # Nothing is suppressed from the totals — only from the summary
    # presentation: the Gesamtgewinn still sums every constituent.
    assert report.total_gain_eur == Decimal("-3")


def test_recording_a_sweep_changes_no_figure_and_marks_no_report_stale(store, client):
    """Membership is presentation, deliberately outside the fingerprint: a
    report generated before the sweep was recorded still rests on exactly
    the inputs that produced it."""
    _statutes(store, year=2031)
    _account, _eur, _eurc, sweeps = _sweep_fixture(store)
    generated = client.post("/api/reports", json={"year": 2031})
    assert generated.status_code == 201
    report_id = generated.json()["id"]

    created = aggregates.record_dust_sweep(store, label="Dust", transaction_ids=sweeps)
    assert isinstance(created, int)

    report = client.get(f"/api/reports/{report_id}").json()
    assert report["stale"] is False


def test_a_dust_sweep_of_anything_but_trades_is_refused(db):
    account = _account(db)
    _eur(db)
    pepe = _coin(db, "PEPE", "ethereum")
    windfall = create_transaction(
        db,
        type="windfall",
        occurred_at=_at(0),
        note=None,
        legs=[Leg(account_id=account, instrument_id=pepe, role="in", quantity=Decimal("5"))],
    )
    assert isinstance(windfall, int)

    refused = aggregates.record_dust_sweep(db, label="Dust", transaction_ids=[windfall])

    assert isinstance(refused, str) and "trade" in refused


def test_a_dust_sweep_whose_trades_disagree_on_the_received_instrument_is_refused(db):
    account, eur = _account(db), _eur(db)
    pepe = _coin(db, "PEPE", "ethereum")
    shib = _coin(db, "SHIB", "shibarium")
    into_pepe = _trade(
        db, account, out_instrument=eur, out_quantity="1", in_instrument=pepe, in_quantity="10"
    )
    into_shib = _trade(
        db, account, out_instrument=eur, out_quantity="1", in_instrument=shib, in_quantity="10"
    )

    refused = aggregates.record_dust_sweep(db, label="Dust", transaction_ids=[into_pepe, into_shib])

    assert isinstance(refused, str) and "one Instrument" in refused


def test_a_dust_sweep_naming_a_transaction_the_ledger_does_not_hold_is_refused(db):
    _account(db), _eur(db)

    refused = aggregates.record_dust_sweep(db, label="Dust", transaction_ids=[999999])

    assert isinstance(refused, str) and "does not hold" in refused


def test_a_transaction_already_aggregated_is_refused_a_second_aggregate(db):
    _account, _eur, _eurc, sweeps = _sweep_fixture(db)
    first = aggregates.record_dust_sweep(db, label="First", transaction_ids=sweeps)
    assert isinstance(first, int)

    refused = aggregates.record_dust_sweep(db, label="Second", transaction_ids=[sweeps[0]])

    assert isinstance(refused, str) and "already belongs" in refused


def test_disbanding_an_aggregate_leaves_its_constituents_standing(db):
    _account, _eur, _eurc, sweeps = _sweep_fixture(db)
    created = aggregates.record_dust_sweep(db, label="Dust", transaction_ids=sweeps)
    assert isinstance(created, int)

    assert aggregates.disband(db, created) is True

    assert aggregates.overview(db).dust_sweeps == ()
    remaining = {
        transaction.id: transaction.aggregate_id
        for transaction in transactions_service.overview(db)
    }
    assert set(sweeps) <= set(remaining)
    assert all(aggregate is None for aggregate in remaining.values())
    assert aggregates.disband(db, created) is False


# --- The API -----------------------------------------------------------------


def test_the_api_records_lists_details_and_disbands_a_bot_aggregate(db, client):
    account, eur = _account(db), _eur(db)
    _bot_cycles(db, account, eur)

    created = client.post(
        "/api/aggregates/bots",
        json={"label": "BTC grid bot", "source": "pionex:bot:grid-1"},
    )
    assert created.status_code == 201
    aggregate_id = created.json()["id"]

    listed = client.get("/api/aggregates")
    assert listed.status_code == 200
    (bot,) = listed.json()["bots"]
    assert bot["id"] == aggregate_id
    assert bot["fill_count"] == 4
    assert bot["closed_positions"] == 2
    (totals,) = bot["closed_totals"]
    assert totals["net"] == "23"

    detailed = client.get(f"/api/aggregates/{aggregate_id}")
    assert detailed.status_code == 200
    answered = detailed.json()
    assert answered["kind"] == "bot"
    assert len(answered["fills"]) == 4
    assert answered["fills"][0]["source"] == "pionex:bot:grid-1"
    assert len(answered["positions"]) == 2

    disbanded = client.delete(f"/api/aggregates/{aggregate_id}")
    assert disbanded.status_code == 204
    assert client.get("/api/aggregates").json()["bots"] == []
    assert client.get(f"/api/aggregates/{aggregate_id}").status_code == 404


def test_the_api_records_and_details_a_dust_sweep(db, client):
    _account, _eur, eurc, sweeps = _sweep_fixture(db)

    created = client.post(
        "/api/aggregates/dust-sweeps",
        json={"label": "March dust sweep", "transaction_ids": sweeps},
    )
    assert created.status_code == 201
    aggregate_id = created.json()["id"]

    (sweep,) = client.get("/api/aggregates").json()["dust_sweeps"]
    assert sweep["received_instrument_id"] == eurc
    assert sweep["received_quantity"] == "27"
    assert sweep["constituent_count"] == 2

    answered = client.get(f"/api/aggregates/{aggregate_id}").json()
    assert answered["kind"] == "dust_sweep"
    assert {transaction["id"] for transaction in answered["transactions"]} == set(sweeps)

    # The ledger listing wears the membership.
    listed = client.get("/api/transactions").json()
    assert {row["aggregate_id"] for row in listed if row["id"] in set(sweeps)} == {aggregate_id}


def test_the_api_answers_a_defect_with_the_service_s_sentence(db, client):
    _account(db), _eur(db)
    client.post("/api/aggregates/bots", json={"label": "Bot", "source": "okx:futures"})

    refused = client.post(
        "/api/aggregates/bots", json={"label": "Bot again", "source": "okx:futures"}
    )

    assert refused.status_code == 422
    assert "already summarises" in refused.json()["detail"]

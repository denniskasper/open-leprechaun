"""Portfolio snapshots and results (ticket 54): the portfolio measured on a
schedule and stored, served beside the live measurement, with what the Admin
put in and took out kept apart from what the holdings did — so a deposit
never reads as a gain — and the realised result stated apart from the
unrealised one.

The seams are the HTTP API over real Postgres with the real task catalogue,
and the snapshot service itself where a test chooses the clock. Prices and
rates are seeded into the store; no provider is ever called.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from open_leprechaun.db import get_engine
from open_leprechaun.main import create_app
from open_leprechaun.ports.reference_rates import ReferenceRate
from open_leprechaun.rates import get_reference_rate_source
from open_leprechaun.repositories import crypto_prices as crypto_prices_repo
from open_leprechaun.repositories import (
    instruments,
    platforms,
    stances,
    transactions,
    transfer_matches,
)
from open_leprechaun.repositories.transactions import Leg
from open_leprechaun.services import futures, snapshots

BOUGHT = datetime(2025, 3, 14, 12, 0, tzinfo=UTC)
LATER = datetime(2025, 6, 3, 12, 0, tzinfo=UTC)
QUOTED = datetime(2025, 7, 1, 9, 30, tzinfo=UTC)

MONDAY = datetime(2025, 7, 7, 4, 0, tzinfo=UTC)
TUESDAY = datetime(2025, 7, 8, 4, 0, tzinfo=UTC)


class NoRates:
    def daily_rates(self, currency, start, end):
        return []


class FakeRates:
    def __init__(self, rates):
        self.rates = rates

    def daily_rates(self, currency, start, end):
        return [
            rate
            for rate in self.rates
            if rate.currency == currency and start <= rate.rate_date <= end
        ]


@pytest.fixture
def client(db: Engine) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: db
    app.dependency_overrides[get_reference_rate_source] = NoRates
    with TestClient(app) as client:
        yield client


def _account(db, platform_name="Kraken", kind="exchange", name="Main"):
    platform_id = platforms.create_platform(db, name=platform_name, kind=kind)
    created = platforms.create_account(db, platform_id, name=name, access_software=None)
    assert isinstance(created, int)
    return created


def _eur(db):
    eur = instruments.create_cash(db, symbol="EUR", name="Euro")
    assert instruments.designate_numeraire(db, eur)
    return eur


def _btc(db, account):
    btc = instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    _keep(db, btc, account)
    return btc


def _keep(db, instrument, account):
    settled = stances.classify(db, instrument, stance="kept", account_id=account)
    assert not isinstance(settled, stances.Refusal)


def _record(db, type, legs, *, occurred_at=BOUGHT, **declared):
    created = transactions.create_transaction(
        db,
        type=type,
        occurred_at=occurred_at,
        note=None,
        legs=[
            Leg(account_id=account, instrument_id=instrument, role=role, quantity=Decimal(quantity))
            for account, instrument, role, quantity in legs
        ],
        **declared,
    )
    assert isinstance(created, int)
    return created


def _deposit(db, account, instrument, quantity, *, occurred_at=BOUGHT):
    return _record(
        db, "transfer_in", [(account, instrument, "in", quantity)], occurred_at=occurred_at
    )


def _withdraw(db, account, instrument, quantity, *, occurred_at=LATER):
    return _record(
        db, "transfer_out", [(account, instrument, "out", quantity)], occurred_at=occurred_at
    )


def _buy(db, account, instrument, eur, *, quantity, cost, occurred_at=BOUGHT):
    return _record(
        db,
        "trade",
        [(account, instrument, "in", quantity), (account, eur, "out", cost)],
        occurred_at=occurred_at,
    )


def _sell(db, account, instrument, eur, *, quantity, proceeds, occurred_at=LATER):
    return _record(
        db,
        "trade",
        [(account, instrument, "out", quantity), (account, eur, "in", proceeds)],
        occurred_at=occurred_at,
    )


def _quote(db, instrument, price, *, as_of=QUOTED):
    crypto_prices_repo.store_quote(
        db, instrument_id=instrument, price_eur=Decimal(price), source="coingecko", as_of=as_of
    )


def _close(db, instrument, price, *, on):
    crypto_prices_repo.store_daily_closes(
        db, instrument, source="coingecko", closes=[(on, Decimal(price))]
    )


def _development(client):
    response = client.get("/api/portfolio/development")
    assert response.status_code == 200
    return response.json()


# --- Snapshots are taken on a schedule and stored ----------------------------


def test_the_snapshot_task_is_on_offer_and_scheduled_daily(client):
    tasks = {task["key"]: task for task in client.get("/api/scheduled-tasks").json()}

    assert tasks["portfolio_snapshot"]["enabled"]
    assert tasks["portfolio_snapshot"]["cron"] == "55 23 * * *"


def test_a_run_of_the_snapshot_task_stores_what_the_portfolio_is_worth(client, db):
    account = _account(db)
    eur = _eur(db)
    _deposit(db, account, eur, "1000")

    ran = client.post("/api/scheduled-tasks/portfolio_snapshot/run").json()

    assert ran["outcome"] == "ok"
    assert ran["detail"] == "Snapshot stored: 1 of 1 positions counted."
    development = _development(client)
    (snapshot,) = development["snapshots"]
    assert snapshot["value_eur"] == "1000.00"
    assert snapshot["positions_held"] == 1
    assert snapshot["positions_counted"] == 1
    assert development["current"]["value_eur"] == "1000.00"


def test_a_day_keeps_one_snapshot_and_the_series_runs_oldest_first(db):
    account = _account(db)
    eur = _eur(db)
    _deposit(db, account, eur, "1000")
    snapshots.take(db, NoRates(), now=TUESDAY)
    snapshots.take(db, NoRates(), now=MONDAY)
    _deposit(db, account, eur, "500")

    # Later on the same Berlin day: the day's point is replaced, not doubled.
    snapshots.take(db, NoRates(), now=MONDAY.replace(hour=20))

    series = snapshots.development(db, now=TUESDAY).snapshots
    assert [(entry.snapshot_date, entry.value_eur) for entry in series] == [
        (date(2025, 7, 7), Decimal("1500.00")),
        (date(2025, 7, 8), Decimal("1000.00")),
    ]


def test_a_snapshot_is_filed_under_the_berlin_date_of_its_instant(db):
    _eur(db)

    # 22:30 UTC in July is already half past midnight in Berlin.
    taken = snapshots.take(db, NoRates(), now=datetime(2025, 7, 7, 22, 30, tzinfo=UTC))

    assert taken.snapshot_date == date(2025, 7, 8)


def test_an_empty_portfolio_is_worth_nothing_which_is_a_figure(client):
    current = _development(client)["current"]

    assert current["value_eur"] == "0.00"
    assert current["positions_held"] == 0


def test_a_portfolio_nothing_counts_in_states_no_value_rather_than_zero(client, db):
    """A figure that cannot be computed says so: an unacknowledged coin is
    held, but nothing vouches for a value."""
    account = _account(db)
    coin = instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    _deposit(db, account, coin, "1")

    current = _development(client)["current"]

    assert current["value_eur"] is None
    assert current["result_eur"] is None
    assert (current["positions_held"], current["positions_counted"]) == (1, 0)


# --- Value change apart from contributions and withdrawals -------------------


def test_a_deposit_raises_value_and_contributions_alike_and_is_no_gain(db):
    account = _account(db)
    eur = _eur(db)
    _deposit(db, account, eur, "1000")
    before = snapshots.take(db, NoRates(), now=MONDAY)
    _deposit(db, account, eur, "500", occurred_at=LATER)

    after = snapshots.take(db, NoRates(), now=TUESDAY)

    assert (before.value_eur, after.value_eur) == (Decimal("1000.00"), Decimal("1500.00"))
    assert after.contributions_eur == Decimal("1500.00")
    assert (before.result_eur, after.result_eur) == (Decimal("0.00"), Decimal("0.00"))


def test_a_price_move_is_result_and_never_a_contribution(db):
    account = _account(db)
    eur = _eur(db)
    btc = _btc(db, account)
    _deposit(db, account, eur, "1000")
    _buy(db, account, btc, eur, quantity="1", cost="1000")
    _quote(db, btc, "1500")

    measured = snapshots.measure(db, now=MONDAY)

    assert measured.value_eur == Decimal("1500.00")
    assert measured.contributions_eur == Decimal("1000.00")
    assert measured.result_eur == Decimal("500.00")


def test_a_transfer_out_nothing_matches_is_a_withdrawal_and_no_loss(db):
    account = _account(db)
    eur = _eur(db)
    _deposit(db, account, eur, "1000")
    _withdraw(db, account, eur, "400")

    measured = snapshots.measure(db, now=MONDAY)

    assert measured.value_eur == Decimal("600.00")
    assert measured.withdrawals_eur == Decimal("400.00")
    assert measured.net_contributions_eur == Decimal("600.00")
    assert measured.result_eur == Decimal("0.00")


def test_a_confirmed_self_transfer_is_neither_withdrawal_nor_contribution(db):
    exchange = _account(db)
    bank = _account(db, platform_name="Sparkasse", kind="bank", name="Giro")
    eur = _eur(db)
    _deposit(db, bank, eur, "1000")
    sent = _withdraw(db, bank, eur, "300")
    arrived = _deposit(db, exchange, eur, "300", occurred_at=LATER)
    leg_of = {leg.transaction_id: leg.id for leg in transactions.list_legs(db)}
    matched = transfer_matches.decide(
        db, out_leg_id=leg_of[sent], in_leg_id=leg_of[arrived], verdict="confirmed"
    )
    assert isinstance(matched, int)

    measured = snapshots.measure(db, now=MONDAY)

    assert measured.contributions_eur == Decimal("1000.00")
    assert measured.withdrawals_eur == Decimal("0.00")


def test_an_opening_balance_contributes_the_estimate_the_admin_declared(db):
    account = _account(db)
    _eur(db)
    btc = _btc(db, account)
    _record(
        db,
        "opening_balance",
        [(account, btc, "in", "1")],
        reconstructed="basis",
        estimated_basis_eur=Decimal("20000"),
    )
    _quote(db, btc, "30000")

    measured = snapshots.measure(db, now=MONDAY)

    assert measured.contributions_eur == Decimal("20000.00")
    assert measured.result_eur == Decimal("10000.00")


def test_a_coin_arriving_from_outside_contributes_the_close_of_its_day(db):
    account = _account(db)
    _eur(db)
    btc = _btc(db, account)
    _deposit(db, account, btc, "2")
    _close(db, btc, "25000", on=BOUGHT.date())
    _quote(db, btc, "26000")

    measured = snapshots.measure(db, now=MONDAY)

    assert measured.contributions_eur == Decimal("50000.00")
    assert measured.result_eur == Decimal("2000.00")
    assert measured.unvalued_flows == 0


def test_a_spend_is_a_withdrawal_at_the_close_of_its_day(db):
    account = _account(db)
    eur = _eur(db)
    btc = _btc(db, account)
    _deposit(db, account, eur, "1000")
    _buy(db, account, btc, eur, quantity="1", cost="1000")
    _record(db, "spend", [(account, btc, "out", "0.5")], occurred_at=LATER)
    _close(db, btc, "3000", on=LATER.date())
    _quote(db, btc, "3000")

    measured = snapshots.measure(db, now=MONDAY)

    assert measured.withdrawals_eur == Decimal("1500.00")
    # Worth 1500 still held, 1500 taken out, 1000 put in.
    assert measured.result_eur == Decimal("2000.00")


def test_a_flow_nothing_stored_can_value_is_counted_and_left_out_of_the_sum(client, db):
    account = _account(db)
    eur = _eur(db)
    btc = _btc(db, account)
    _deposit(db, account, eur, "1000")
    _deposit(db, account, btc, "2")

    ran = client.post("/api/scheduled-tasks/portfolio_snapshot/run").json()

    assert ran["detail"] == (
        "Snapshot stored: 1 of 2 positions counted."
        " 1 contribution or withdrawal could not be valued."
    )
    (snapshot,) = _development(client)["snapshots"]
    assert snapshot["contributions_eur"] == "1000.00"
    assert snapshot["unvalued_flows"] == 1


def test_income_is_what_the_holdings_earned_and_no_contribution(db):
    account = _account(db)
    eur = _eur(db)
    _deposit(db, account, eur, "1000")
    _record(db, "interest", [(account, eur, "in", "10")], occurred_at=LATER)

    measured = snapshots.measure(db, now=MONDAY)

    assert measured.value_eur == Decimal("1010.00")
    assert measured.contributions_eur == Decimal("1000.00")
    assert measured.result_eur == Decimal("10.00")


def test_a_position_outside_the_totals_takes_its_flows_out_with_it(db):
    """Value and contributions describe the same holdings: a coin still
    waiting in the Inbox counts on neither side."""
    account = _account(db)
    eur = _eur(db)
    _deposit(db, account, eur, "1000")
    coin = instruments.create_native_coin(db, symbol="BTC", name="Bitcoin", chain="bitcoin")
    _deposit(db, account, coin, "1")
    _close(db, coin, "25000", on=BOUGHT.date())

    measured = snapshots.measure(db, now=MONDAY)

    assert (measured.positions_held, measured.positions_counted) == (2, 1)
    assert measured.contributions_eur == Decimal("1000.00")
    assert measured.unvalued_flows == 0


def test_only_the_scheduled_run_asks_the_source_for_a_rate_the_store_lacks(db):
    """The request path reads the store alone (ADR-0019); the task may fetch,
    and what it fetched answers every read after it."""
    account = _account(db)
    _eur(db)
    usd = instruments.create_cash(db, symbol="USD", name="US dollar")
    _keep(db, usd, account)
    _deposit(db, account, usd, "1100")
    published = FakeRates([ReferenceRate("USD", BOUGHT.date(), Decimal("1.10"))])

    assert snapshots.measure(db, now=MONDAY).unvalued_flows == 1

    taken = snapshots.take(db, published, now=MONDAY)

    assert taken.contributions_eur == Decimal("1000.00")
    assert snapshots.measure(db, now=MONDAY).contributions_eur == Decimal("1000.00")


def test_a_rate_the_source_never_published_leaves_the_flow_unvalued_not_the_run_failed(db):
    account = _account(db)
    _eur(db)
    usd = instruments.create_cash(db, symbol="USD", name="US dollar")
    _keep(db, usd, account)
    _deposit(db, account, usd, "1100")

    taken = snapshots.take(db, NoRates(), now=MONDAY)

    assert taken.unvalued_flows == 1
    assert taken.contributions_eur == Decimal("0.00")


# --- The realised result, apart from the unrealised one ----------------------


def _depot(db):
    platform_id = platforms.create_platform(db, name="Scalable Capital", kind="broker")
    assert platforms.set_withholding(db, platform_id, behaviour="none") is None
    created = platforms.create_account(db, platform_id, name="Depot")
    assert isinstance(created, int)
    return created


def _realised(client):
    response = client.get("/api/portfolio/realised")
    assert response.status_code == 200
    return response.json()


def _component(realised, kind):
    (component,) = [entry for entry in realised["components"] if entry["kind"] == kind]
    return component


def test_nothing_sold_is_a_realised_result_of_nothing(client, db):
    _eur(db)

    realised = _realised(client)

    assert realised["result_eur"] == "0.00"
    assert [component["kind"] for component in realised["components"]] == [
        "private_sales",
        "securities",
        "futures",
    ]
    assert all(component["events"] == 0 for component in realised["components"])


def test_a_coin_sold_states_its_gain_as_realised(client, db):
    account = _account(db)
    eur = _eur(db)
    btc = _btc(db, account)
    _buy(db, account, btc, eur, quantity="1", cost="1000")
    _sell(db, account, btc, eur, quantity="1", proceeds="1500")

    realised = _realised(client)

    assert _component(realised, "private_sales") == {
        "kind": "private_sales",
        "result_eur": "500.00",
        "stated": 1,
        "events": 1,
        "refusal": None,
    }
    assert realised["result_eur"] == "500.00"


def test_a_gain_the_haltefrist_exempts_is_realised_all_the_same(client, db):
    """The realised result is what the sale made, not what is taxable."""
    account = _account(db)
    eur = _eur(db)
    btc = _btc(db, account)
    _buy(
        db,
        account,
        btc,
        eur,
        quantity="1",
        cost="1000",
        occurred_at=datetime(2023, 1, 5, tzinfo=UTC),
    )
    _sell(db, account, btc, eur, quantity="1", proceeds="1500")

    assert _component(_realised(client), "private_sales")["result_eur"] == "500.00"


def test_a_share_sold_at_a_loss_states_it_under_securities(client, db):
    depot = _depot(db)
    eur = _eur(db)
    share = instruments.create_security(
        db, symbol="SAP", name="SAP", type="share", isin="DE0007164600"
    )
    _keep(db, share, depot)
    _buy(db, depot, share, eur, quantity="10", cost="1000")
    _sell(db, depot, share, eur, quantity="10", proceeds="800")

    realised = _realised(client)

    assert _component(realised, "securities")["result_eur"] == "-200.00"
    assert realised["result_eur"] == "-200.00"


def test_a_closed_futures_position_states_its_net_figure(client, db):
    account = _account(db)
    eur = _eur(db)
    recorded = futures.record_manual_position(
        db,
        futures.FuturesPosition(
            account_id=account,
            symbol="BTC-PERP",
            side="long",
            quantity=Decimal("1"),
            settlement_instrument_id=eur,
            opened_at=BOUGHT,
            closed_at=LATER,
            realized=Decimal("100"),
            fees=Decimal("10"),
        ),
    )
    assert isinstance(recorded, int)

    realised = _realised(client)

    assert _component(realised, "futures")["result_eur"] == "90.00"
    assert realised["result_eur"] == "90.00"


def test_a_sale_awaiting_a_valuation_is_counted_and_left_unstated(client, db):
    """A coin swapped for another with no stored close: the gain cannot be
    stated, so the figure says how many it covers instead of assuming zero."""
    account = _account(db)
    eur = _eur(db)
    btc = _btc(db, account)
    eth = instruments.create_native_coin(db, symbol="ETH", name="Ether", chain="ethereum")
    _keep(db, eth, account)
    _buy(db, account, btc, eur, quantity="2", cost="2000")
    _sell(db, account, btc, eur, quantity="1", proceeds="1500")
    _record(
        db, "trade", [(account, btc, "out", "1"), (account, eth, "in", "20")], occurred_at=LATER
    )

    realised = _realised(client)

    private_sales = _component(realised, "private_sales")
    assert (private_sales["stated"], private_sales["events"]) == (1, 2)
    assert private_sales["result_eur"] == "500.00"
    assert (realised["stated"], realised["events"]) == (1, 2)


def test_a_result_no_sale_can_state_is_unstated_never_zero(client, db):
    account = _account(db)
    eur = _eur(db)
    btc = _btc(db, account)
    eth = instruments.create_native_coin(db, symbol="ETH", name="Ether", chain="ethereum")
    _keep(db, eth, account)
    _buy(db, account, btc, eur, quantity="1", cost="2000")
    _record(
        db, "trade", [(account, btc, "out", "1"), (account, eth, "in", "20")], occurred_at=LATER
    )

    realised = _realised(client)

    assert _component(realised, "private_sales")["result_eur"] is None
    assert realised["result_eur"] is None


def test_a_sale_no_lot_vouches_for_refuses_its_regime_and_says_why(client, db):
    account = _account(db)
    depot = _depot(db)
    eur = _eur(db)
    btc = _btc(db, account)
    share = instruments.create_security(
        db, symbol="SAP", name="SAP", type="share", isin="DE0007164600"
    )
    _keep(db, share, depot)
    _sell(db, account, btc, eur, quantity="1", proceeds="1500")
    _buy(db, depot, share, eur, quantity="10", cost="1000")
    _sell(db, depot, share, eur, quantity="10", proceeds="1200")

    realised = _realised(client)

    private_sales = _component(realised, "private_sales")
    assert private_sales["result_eur"] is None
    assert "an acquisition is missing from the ledger" in private_sales["refusal"]
    # The regime beside it still answers; the whole does not.
    assert _component(realised, "securities")["result_eur"] == "200.00"
    assert realised["result_eur"] is None


def test_a_reward_sold_after_the_haltefrist_still_states_what_it_made(client, db):
    """The tax engine leaves an exempt slice's basis unvalued — nothing
    taxable rests on it — but what the sale made does."""
    account = _account(db)
    eur = _eur(db)
    btc = _btc(db, account)
    received = datetime(2023, 1, 5, 12, 0, tzinfo=UTC)
    _record(db, "staking_reward", [(account, btc, "in", "1")], occurred_at=received)
    _close(db, btc, "1000", on=received.date())
    _sell(db, account, btc, eur, quantity="1", proceeds="1500")

    private_sales = _component(_realised(client), "private_sales")

    assert private_sales["result_eur"] == "500.00"
    assert (private_sales["stated"], private_sales["events"]) == (1, 1)


def test_a_windfall_sold_realises_its_whole_proceeds(client, db):
    """Received for nothing: outside §23, but the sale made what it made."""
    account = _account(db)
    eur = _eur(db)
    btc = _btc(db, account)
    _record(db, "windfall", [(account, btc, "in", "1")])
    _sell(db, account, btc, eur, quantity="1", proceeds="300")

    assert _component(_realised(client), "private_sales")["result_eur"] == "300.00"

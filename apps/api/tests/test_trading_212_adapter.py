"""The Trading 212 adapter against recorded venue responses (ticket 48): raw
payloads in the venue's documented shapes in, normalized records out. No live
call is ever made — the seam is the broker port, fed through a mock transport
that answers what the venue answers.

The payloads (fixtures/trading_212/recorded.json) are authored from the
schemas of the venue's published OpenAPI document, which prints no example
responses; there was no account to record from. The mock venue honours the
documented contract: HTTP Basic authentication with the key as username and
the secret as password, and pagination by the `nextPagePath` each answer
states, null on the last page.
"""

import base64
import copy
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from open_leprechaun.adapters import get_venue_adapters
from open_leprechaun.ports import trading_212
from open_leprechaun.ports.broker import (
    AdapterError,
    BrokerHarvest,
    CoveredPeriod,
    NormalizedAccountFee,
    NormalizedCashMovement,
    NormalizedDividend,
    NormalizedFee,
    NormalizedOriginalAmount,
    NormalizedPosition,
    NormalizedSecurity,
    NormalizedSecurityTrade,
)
from open_leprechaun.ports.trading_212 import Trading212Adapter
from open_leprechaun.ports.venues import VENUES
from open_leprechaun.services.connections import Credentials

RECORDED = json.loads(
    (Path(__file__).parent / "fixtures" / "trading_212" / "recorded.json").read_text()
)

KEY = "20000000ZabcdefGHIJKLmnopqrSTUVwxyz0"
SECRET = "s3cr3t-never-a-real-one"
CREDENTIALS = Credentials(key=KEY, secret=SECRET, passphrase=None)
NOW = datetime(2024, 6, 2, 12, 0, tzinfo=UTC)

APPLE = NormalizedSecurity(isin="US0378331005", symbol="AAPL", name="Apple")
SAP = NormalizedSecurity(isin="DE0007164600", symbol="SAPd", name="SAP")
VODAFONE = NormalizedSecurity(isin="GB00BH4HKS39", symbol="VODl", name="Vodafone Group")

_PATHS = {
    "/api/v0/equity/account/summary": "summary",
    "/api/v0/equity/positions": "positions",
    "/api/v0/equity/history/orders": "orders",
    "/api/v0/equity/history/dividends": "dividends",
    "/api/v0/equity/history/transactions": "transactions",
}


def recorded() -> dict:
    return copy.deepcopy(RECORDED)


def venue(payloads: dict | None = None, *, refuse: dict | None = None):
    """A mock of the venue over the recorded payloads: a paged list answers
    its first page to a request without a cursor and the page after to the
    `nextPagePath` it stated. `refuse` answers a status for a path instead.
    Returns the adapter and the requests it made."""
    payloads = RECORDED if payloads is None else payloads
    refuse = refuse or {}
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        name = _PATHS[request.url.path]
        if name in refuse:
            return httpx.Response(refuse[name])
        payload = payloads[name]
        if name in ("summary", "positions"):
            return httpx.Response(200, json=payload)
        asked = f"{request.url.path}?{request.url.query.decode()}"
        for index, page in enumerate(payload[:-1]):
            if page["nextPagePath"] == asked:
                return httpx.Response(200, json=payload[index + 1])
        return httpx.Response(200, json=payload[0])

    adapter = Trading212Adapter(
        client=httpx.Client(transport=httpx.MockTransport(answer)),
        throttle_seconds=0,
        now=lambda: NOW,
    )
    return adapter, requests


def one_order(**fill_overrides) -> dict:
    """The recorded payloads narrowed to the one Apple purchase, its fill
    amended."""
    payloads = recorded()
    item = payloads["orders"][1]["items"][1]
    item["fill"].update(fill_overrides)
    payloads["orders"] = [{"items": [item], "nextPagePath": None}]
    return payloads


# --- Authentication ---


def test_every_request_authenticates_with_the_key_pair_as_http_basic():
    adapter, requests = venue()

    adapter.pull(CREDENTIALS)

    expected = "Basic " + base64.b64encode(f"{KEY}:{SECRET}".encode()).decode()
    assert requests and all(request.headers["Authorization"] == expected for request in requests)
    assert all(request.url.host == "live.trading212.com" for request in requests)


def test_a_missing_secret_is_refused_before_any_request():
    adapter, requests = venue()

    with pytest.raises(AdapterError, match="secret"):
        adapter.test(Credentials(key=KEY, secret=None, passphrase=None))

    assert requests == []


def test_a_successful_test_states_the_settlement_currency_and_what_it_cannot_prove():
    """The venue's API has no way to state a key's own scopes, so the test
    can prove the read scopes are there but never that the trading ones are
    not — and says so rather than claiming read-only."""
    adapter, requests = venue()

    detail = adapter.test(CREDENTIALS)

    assert "EUR" in detail
    assert "cannot state" in detail
    # Every endpoint a sync or a reconciliation reads is opened once.
    assert {request.url.path for request in requests} == set(_PATHS)


def test_a_test_names_every_read_scope_the_key_lacks():
    adapter, _ = venue(refuse={"dividends": 403, "positions": 403})

    with pytest.raises(AdapterError) as refused:
        adapter.test(CREDENTIALS)

    assert "history:dividends" in str(refused.value)
    assert "portfolio" in str(refused.value)
    assert "history:orders" not in str(refused.value)


def test_a_refused_key_becomes_an_adapter_error():
    adapter, _ = venue(refuse={"summary": 401})

    with pytest.raises(AdapterError, match="401"):
        adapter.test(CREDENTIALS)


def test_no_secret_material_ever_reaches_an_error_sentence():
    adapter, _ = venue(refuse={"orders": 500})

    with pytest.raises(AdapterError) as failed:
        adapter.pull(CREDENTIALS)

    assert SECRET not in str(failed.value) and KEY not in str(failed.value)


# --- Trades ---


def test_a_foreign_currency_purchase_states_what_settled_and_what_was_priced():
    """The Depot settles in EUR; the security was priced in USD. The record
    states the euros that moved for the security, the dollars it was priced
    at and the rate the broker applied — and the conversion fee apart, as a
    cost of the cash."""
    adapter, _ = venue()

    harvest = adapter.pull(CREDENTIALS)

    assert harvest.trades[-1] == NormalizedSecurityTrade(
        external_id="fill-50000000000",
        occurred_at=datetime(2024, 3, 4, 14, 31, 7, tzinfo=UTC),
        security=APPLE,
        side="buy",
        quantity=Decimal("2"),
        # The wallet was debited 333.83 in all, 0.50 of it the fee.
        settled_amount=Decimal("333.33"),
        settlement_currency="EUR",
        original=NormalizedOriginalAmount(
            amount=Decimal("360.00"), currency="USD", fx_rate=Decimal("1.08")
        ),
        fees=(
            NormalizedFee(
                name="CURRENCY_CONVERSION_FEE",
                amount=Decimal("0.5"),
                currency="EUR",
                charged_against="cash",
            ),
        ),
    )


def test_a_sale_in_the_settlement_currency_states_no_original_amount():
    adapter, _ = venue()

    harvest = adapter.pull(CREDENTIALS)

    assert harvest.trades[1] == NormalizedSecurityTrade(
        external_id="fill-50000000002",
        occurred_at=datetime(2024, 3, 20, 10, 2, 1, tzinfo=UTC),
        security=SAP,
        side="sell",
        # The venue states a sale's quantity negative; the port states the
        # direction as the side.
        quantity=Decimal("1"),
        settled_amount=Decimal("170.0"),
        settlement_currency="EUR",
    )


def test_a_transaction_tax_is_a_cost_of_the_security_and_a_conversion_fee_of_the_cash():
    adapter, _ = venue()

    trade = adapter.pull(CREDENTIALS).trades[0]

    assert trade.security == VODAFONE
    assert trade.settled_amount == Decimal("86.31")
    # Priced in pence, stated in pounds: the port carries whole units. The
    # venue's rate is per penny and explains nothing in pounds, so the rate
    # the fill's own amounts imply stands in.
    assert (trade.original.amount, trade.original.currency) == (Decimal("72.5"), "GBP")
    assert trade.original.fx_rate == Decimal("72.5") / Decimal("86.31")
    assert trade.fees == (
        NormalizedFee("STAMP_DUTY_RESERVE_TAX", Decimal("0.43"), "EUR", "security"),
        NormalizedFee("CURRENCY_CONVERSION_FEE", Decimal("0.13"), "EUR", "cash"),
    )


def test_a_sales_fees_come_out_of_what_the_wallet_received():
    """On a sale the wallet is credited net of the fees, so what the
    security itself fetched is the credit plus them."""
    payloads = one_order()
    item = payloads["orders"][0]["items"][0]
    item["order"]["side"] = "SELL"
    item["fill"]["quantity"] = -2
    item["fill"]["walletImpact"]["netValue"] = 332.83

    (trade,) = venue(payloads)[0].pull(CREDENTIALS).trades

    assert (trade.side, trade.quantity) == ("sell", Decimal("2"))
    assert trade.settled_amount == Decimal("333.33")


def test_a_rate_stated_the_other_way_round_is_normalized_to_the_ports_direction():
    """The venue documents `fxRate` as a number and nothing more. The port's
    rate is units of the original currency per one of the settlement
    currency, so the adapter keeps whichever direction reproduces the fill."""
    payloads = one_order()
    payloads["orders"][0]["items"][0]["fill"]["walletImpact"]["fxRate"] = 0.925926

    (trade,) = venue(payloads)[0].pull(CREDENTIALS).trades

    assert trade.original.fx_rate.quantize(Decimal("0.0001")) == Decimal("1.0800")


@pytest.mark.parametrize("stated", [3.5, None])
def test_a_rate_that_cannot_explain_the_fill_gives_way_to_the_one_its_amounts_imply(stated):
    """A stated rate that reproduces the fill in neither direction — or none
    stated at all — is not what the broker applied; the fill's own amounts
    say what was, and the trade still lands."""
    payloads = one_order()
    wallet = payloads["orders"][0]["items"][0]["fill"]["walletImpact"]
    if stated is None:
        del wallet["fxRate"]
    else:
        wallet["fxRate"] = stated

    (trade,) = venue(payloads)[0].pull(CREDENTIALS).trades

    assert trade.original.fx_rate == Decimal("360.00") / Decimal("333.33")


def test_an_order_that_never_filled_states_nothing():
    adapter, _ = venue()

    harvest = adapter.pull(CREDENTIALS)

    assert [trade.external_id for trade in harvest.trades] == [
        "fill-50000000003",
        "fill-50000000002",
        "fill-50000000000",
    ]


def test_a_fill_that_is_no_trade_is_passed_over_by_name_never_landed():
    """A split or a spin-off reaches the history as a fill, but it is a
    Corporate Action, not a trade — named for the Admin to record, never
    booked as a purchase."""
    payloads = one_order(type="STOCK_SPLIT")

    harvest = venue(payloads)[0].pull(CREDENTIALS)

    assert harvest.trades == ()
    (passed,) = harvest.passed_over
    assert passed.external_id == "fill-50000000000"
    assert "STOCK_SPLIT" in passed.description and "US0378331005" in passed.description


def test_a_fill_on_a_side_the_venue_does_not_document_is_refused_not_booked_as_a_sale():
    payloads = one_order()
    payloads["orders"][0]["items"][0]["order"]["side"] = "SHORT"

    with pytest.raises(AdapterError, match="SHORT"):
        venue(payloads)[0].pull(CREDENTIALS)


def test_a_fee_charged_outside_the_settlement_currency_is_refused():
    payloads = one_order()
    payloads["orders"][0]["items"][0]["fill"]["walletImpact"]["taxes"][0]["currency"] = "USD"

    with pytest.raises(AdapterError, match="CURRENCY_CONVERSION_FEE"):
        venue(payloads)[0].pull(CREDENTIALS)


# --- Dividends ---


def test_a_dividend_states_the_net_that_arrived_and_the_gross_as_declared():
    adapter, _ = venue()

    harvest = adapter.pull(CREDENTIALS)

    assert harvest.dividends[0] == NormalizedDividend(
        external_id="dividend-c1f0e6a2-0001",
        occurred_at=datetime(2024, 5, 16, 11, 20, tzinfo=UTC),
        kind="dividend",
        amount=Decimal("0.39"),
        currency="EUR",
        security=APPLE,
        # 0.25 a share on two shares, in the currency it was declared in.
        # The venue states neither what was withheld nor by whom.
        gross_amount=Decimal("0.50"),
        gross_currency="USD",
    )


def test_a_payment_that_is_no_income_is_passed_over_by_name():
    """A return of capital reduces a cost basis — a Corporate Action — and
    booking it as a dividend would tax it."""
    payloads = recorded()
    payloads["dividends"][0]["items"][0]["type"] = "RETURN_OF_CAPITAL"

    harvest = venue(payloads)[0].pull(CREDENTIALS)

    assert [dividend.kind for dividend in harvest.dividends] == ["interest"]
    assert any("RETURN_OF_CAPITAL" in passed.description for passed in harvest.passed_over)


def test_a_dividend_taken_back_is_passed_over_never_booked_as_income():
    payloads = recorded()
    payloads["dividends"][0]["items"][0]["amount"] = -0.39

    harvest = venue(payloads)[0].pull(CREDENTIALS)

    assert [dividend.kind for dividend in harvest.dividends] == ["interest"]
    assert any("taken back" in passed.description for passed in harvest.passed_over)


# --- Cash ---


def test_cash_transactions_become_movements_a_fee_and_interest():
    adapter, _ = venue()

    harvest = adapter.pull(CREDENTIALS)

    assert harvest.cash_movements == (
        NormalizedCashMovement(
            external_id="transaction-t-0003",
            occurred_at=datetime(2024, 5, 10, 9, 0, tzinfo=UTC),
            direction="out",
            currency="EUR",
            amount=Decimal("50.0"),
        ),
        NormalizedCashMovement(
            external_id="transaction-t-0002",
            occurred_at=datetime(2024, 4, 2, 12, 0, tzinfo=UTC),
            direction="out",
            currency="EUR",
            amount=Decimal("200.0"),
        ),
        NormalizedCashMovement(
            external_id="transaction-t-0001",
            occurred_at=datetime(2024, 3, 1, 8, 30, tzinfo=UTC),
            direction="in",
            currency="EUR",
            amount=Decimal("1000.0"),
        ),
    )
    assert harvest.account_fees == (
        NormalizedAccountFee(
            external_id="transaction-t-0004",
            occurred_at=datetime(2024, 5, 20, 9, 0, tzinfo=UTC),
            amount=Decimal("1.0"),
            currency="EUR",
        ),
    )
    assert harvest.dividends[-1] == NormalizedDividend(
        external_id="transaction-t-0005",
        occurred_at=datetime(2024, 6, 1, 2, 0, tzinfo=UTC),
        kind="interest",
        amount=Decimal("0.42"),
        currency="EUR",
    )


def test_a_cash_transaction_of_an_undocumented_type_refuses_the_pull_by_name():
    payloads = recorded()
    payloads["transactions"][0]["items"][0]["type"] = "CASHBACK"

    with pytest.raises(AdapterError, match="CASHBACK"):
        venue(payloads)[0].pull(CREDENTIALS)


# --- Lookback, coverage, pagination ---


def test_the_adapter_declares_an_unbounded_lookback_and_reports_the_period_covered():
    adapter, _ = venue()

    harvest = adapter.pull(CREDENTIALS)

    assert adapter.lookback_days is None
    # The venue pages its whole history, so the period starts at the Depot's
    # beginning and ends when the pull was made.
    assert harvest.covered == CoveredPeriod(start=None, end=NOW)


def test_every_page_is_followed_by_the_path_the_last_answer_stated():
    adapter, requests = venue()

    adapter.pull(CREDENTIALS)

    asked = [f"{request.url.path}?{request.url.query.decode()}" for request in requests]
    assert "/api/v0/equity/history/orders?limit=50&cursor=1712000000000" in asked
    assert "/api/v0/equity/history/transactions?limit=50&cursor=abc123" in asked
    assert len(requests) == 5


def test_a_next_page_outside_the_history_api_is_never_followed():
    payloads = recorded()
    payloads["orders"][0]["nextPagePath"] = "//evil.example/api/v0/equity/history/orders"

    with pytest.raises(AdapterError, match="refused"):
        venue(payloads)[0].pull(CREDENTIALS)


def test_exhausting_the_page_budget_raises_rather_than_truncates(monkeypatch):
    monkeypatch.setattr(trading_212, "_MAX_PAGES", 1)

    with pytest.raises(AdapterError, match="truncated"):
        venue()[0].pull(CREDENTIALS)


def test_a_rate_limited_request_waits_for_the_reset_the_venue_states_and_asks_again():
    answers = iter(
        [
            httpx.Response(429, headers={"x-ratelimit-reset": str(int(NOW.timestamp()) + 7)}),
            httpx.Response(200, json=RECORDED["summary"]),
            httpx.Response(200, json=RECORDED["positions"]),
        ]
    )
    slept: list[float] = []
    adapter = Trading212Adapter(
        client=httpx.Client(transport=httpx.MockTransport(lambda request: next(answers))),
        throttle_seconds=0,
        now=lambda: NOW,
        sleep=slept.append,
    )

    assert len(adapter.normalized_positions(CREDENTIALS)) == 3
    assert slept == [8]


def test_a_request_still_limited_after_waiting_is_an_adapter_error():
    adapter = Trading212Adapter(
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(429))),
        throttle_seconds=0,
        now=lambda: NOW,
        sleep=lambda seconds: None,
    )

    with pytest.raises(AdapterError, match="rate limit"):
        adapter.test(CREDENTIALS)


def test_a_row_the_adapter_cannot_read_is_an_adapter_error():
    payloads = one_order()
    del payloads["orders"][0]["items"][0]["fill"]["walletImpact"]["netValue"]

    with pytest.raises(AdapterError, match="could not read"):
        venue(payloads)[0].pull(CREDENTIALS)


def test_an_empty_depot_pulls_a_clean_empty_harvest():
    empty = {"items": [], "nextPagePath": None}
    payloads = {**recorded(), "orders": [empty], "dividends": [empty], "transactions": [empty]}

    harvest = venue(payloads)[0].pull(CREDENTIALS)

    assert harvest == BrokerHarvest(covered=CoveredPeriod(start=None, end=NOW))


# --- Positions: for reconciliation only ---


def test_positions_state_each_security_by_isin_and_the_cash_by_currency():
    adapter, _ = venue()

    positions = adapter.normalized_positions(CREDENTIALS)

    assert positions == (
        NormalizedPosition(symbol="AAPL", quantity=Decimal("2"), as_of=NOW, isin="US0378331005"),
        NormalizedPosition(symbol="VODl", quantity=Decimal("100"), as_of=NOW, isin="GB00BH4HKS39"),
        # Free, reserved for orders and waiting in pies: all of it is cash
        # the Depot holds.
        NormalizedPosition(symbol="EUR", quantity=Decimal("447.07"), as_of=NOW),
    )


def test_a_harvest_has_no_place_for_a_position():
    """Positions are for reconciliation only: nothing that lands records can
    be handed a snapshot, because the harvest cannot carry one."""
    assert not any("position" in name for name in BrokerHarvest.__dataclass_fields__)


# --- The registry ---


def test_trading_212_ships_as_one_adapter_plus_a_registry_entry():
    entry = VENUES["trading_212"]

    (adapter,) = get_venue_adapters()["trading_212"]
    assert isinstance(adapter, Trading212Adapter)
    assert adapter.kind == "securities"
    assert entry.requires_secret is True
    # The setup screen names the exact scopes to grant — and the ones not to.
    for scope in ("account", "portfolio", "history:orders", "history:dividends"):
        assert scope in entry.required_scope
    assert "history:transactions" in entry.required_scope
    assert "orders:execute" in entry.required_scope


def test_the_recorded_payloads_are_json_clean():
    assert json.loads(json.dumps(RECORDED)) == RECORDED

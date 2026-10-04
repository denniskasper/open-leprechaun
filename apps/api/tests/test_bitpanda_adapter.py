"""The Bitpanda adapters against recorded venue responses (ticket 49): raw
payloads in the venue's documented shapes in, normalized records out. No live
call is ever made — the seams are the exchange port and the broker port, each
served by one kind, fed through a mock transport that answers what the venue
answers.

The payloads (fixtures/bitpanda/recorded.json) are of two origins. The asset
and currency rows are the venue's own, read from its public, unauthenticated
endpoints. The operations and the portfolio are authored from the schemas of
its published OpenAPI document, which prints no example responses and
documents no vocabulary for an operation's type; there was no account to
record from. The mock venue honours the documented contract: the key in the
`x-api-key` header on the account's endpoints, and pagination by the
`next_cursor` each answer states while `has_next_page` holds.
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
from open_leprechaun.ports import bitpanda
from open_leprechaun.ports.bitpanda import BitpandaSecuritiesAdapter, BitpandaSpotAdapter
from open_leprechaun.ports.broker import (
    AdapterError,
    BrokerHarvest,
    CoveredPeriod,
    NormalizedAccountFee,
    NormalizedCashMovement,
    NormalizedDividend,
    NormalizedFee,
    NormalizedPosition,
    NormalizedSecurity,
    NormalizedSecurityTrade,
)
from open_leprechaun.ports.exchange import (
    Harvest,
    NormalizedTrade,
    NormalizedTransfer,
    StatesNormalizedPositions,
)
from open_leprechaun.ports.venues import VENUES
from open_leprechaun.services.connections import Credentials

RECORDED = json.loads(
    (Path(__file__).parent / "fixtures" / "bitpanda" / "recorded.json").read_text()
)

KEY = "bp-read-only-never-a-real-one"
CREDENTIALS = Credentials(key=KEY, secret=None, passphrase=None)
NOW = datetime(2024, 6, 2, 12, 0, tzinfo=UTC)

MICROSOFT = NormalizedSecurity(isin="US5949181045", symbol="MSFT", name="Microsoft Corp")
SP500 = NormalizedSecurity(
    isin="IE00B5BMR087", symbol="SXR8", name="iShares Core S&P 500 UCITS ETF"
)

EUR_ID = "b88b8466-efe3-11eb-b56f-0691764446a7"
BTC_ID = "b86c034b-efe3-11eb-b56f-0691764446a7"
MSFT_ID = "1f0ea510-24fe-6f72-aec7-39e58f1b6f06"

_ACCOUNT_PATHS = {"/v1/operations": "operations", "/v1/portfolio": "portfolio"}
_PUBLIC_PATHS = {"/v1/assets": "assets", "/v1/currencies": "currencies"}


def recorded() -> dict:
    return copy.deepcopy(RECORDED)


def transaction_id(number: int) -> str:
    return f"transaction-7a000000-0000-4000-8000-{number:012d}"


def trade_id(number: int) -> str:
    return f"trade-7d000000-0000-4000-8000-{number:012d}"


def venue(payloads: dict | None = None, *, refuse: dict | None = None):
    """A mock of the venue over the recorded payloads. The operations answer
    their first page to a request without a cursor and the page after to the
    cursor the last one stated; the asset list answers the ids asked for.
    `refuse` answers a status for a path instead. Returns both kinds, served
    by one client, and the requests they made."""
    payloads = RECORDED if payloads is None else payloads
    refuse = refuse or {}
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        name = _ACCOUNT_PATHS.get(path) or _PUBLIC_PATHS[path]
        if name in refuse:
            return httpx.Response(refuse[name])
        if path in _ACCOUNT_PATHS and request.headers.get("x-api-key") != KEY:
            return httpx.Response(401, json={"errors": [{"code": "unauthorized", "status": 401}]})
        if name == "assets":
            asked = request.url.params["id"].split(",")
            rows = [row for row in payloads["assets"] if row["id"] in asked]
            return httpx.Response(200, json={"data": rows, "has_next_page": False})
        if name == "operations":
            pages = payloads["operations"]
            cursor = request.url.params.get("cursor")
            for index, page in enumerate(pages[:-1]):
                if cursor is not None and cursor == _accepted(page["next_cursor"]):
                    return httpx.Response(200, json=pages[index + 1])
            return httpx.Response(200, json=pages[0])
        return httpx.Response(200, json=payloads[name])

    client = httpx.Client(transport=httpx.MockTransport(answer))
    spot = BitpandaSpotAdapter(client=client, now=lambda: NOW, sleep=lambda seconds: None)
    securities = BitpandaSecuritiesAdapter(
        client=client, now=lambda: NOW, sleep=lambda seconds: None
    )
    return spot, securities, requests


def _accepted(cursor: str) -> str:
    """The cursor as the venue takes it back: one that is a timestamp of
    whole seconds restarts the listing unless it returns with milliseconds —
    seen by an integration that reads the live API."""
    stated = base64.b64decode(cursor).decode()
    if stated.endswith("Z") and "." not in stated:
        return base64.b64encode(f"{stated[:-1]}.000Z".encode()).decode()
    return cursor


def only(*operation_numbers: int, **amend) -> dict:
    """The recorded payloads narrowed to the operations of these numbers, on
    one page."""
    payloads = recorded()
    wanted = {f"09000000-0000-4000-8000-{number:012d}" for number in operation_numbers}
    kept = [
        operation
        for page in payloads["operations"]
        for operation in page["data"]
        if operation["operation_id"] in wanted
    ]
    payloads["operations"] = [{"data": kept, "has_next_page": False}]
    payloads.update(amend)
    return payloads


# --- Authentication and scope ---


def test_the_key_travels_in_its_header_to_the_accounts_endpoints_alone():
    """The asset and currency lists are public; the key is never sent where
    it is not needed, and never to another host."""
    spot, securities, requests = venue()

    spot.pull(CREDENTIALS)
    securities.normalized_positions(CREDENTIALS)

    assert requests and all(
        request.url.host == "api.public.bitpanda.com" and request.method == "GET"
        for request in requests
    )
    for request in requests:
        if request.url.path in _ACCOUNT_PATHS:
            assert request.headers["x-api-key"] == KEY
        else:
            assert "x-api-key" not in request.headers


def test_a_successful_test_says_what_it_cannot_prove():
    """The API cannot state a key's own scopes, so a test proves the read
    scopes are there but never that the write ones are not — and says so."""
    spot, securities, _ = venue()

    for adapter in (spot, securities):
        detail = adapter.test(CREDENTIALS)
        assert "Trade (Write)" in detail and "Earn (Write)" in detail


def test_the_securities_kind_names_the_scope_the_key_lacks():
    _, securities, _ = venue(refuse={"portfolio": 401})

    with pytest.raises(AdapterError, match="Balances") as refused:
        securities.test(CREDENTIALS)

    assert "Transaction" not in str(refused.value)


def test_the_spot_kind_needs_the_transaction_scope_alone():
    spot, _, requests = venue(refuse={"portfolio": 401, "operations": 403})

    with pytest.raises(AdapterError, match="Transaction"):
        spot.test(CREDENTIALS)

    assert {request.url.path for request in requests} == {"/v1/operations"}


def test_a_key_that_opens_nothing_is_named_as_refused():
    _, securities, _ = venue()

    with pytest.raises(AdapterError, match="refused the key"):
        securities.test(Credentials(key="wrong", secret=None, passphrase=None))


def test_no_key_material_ever_reaches_an_error_sentence():
    spot, securities, _ = venue(refuse={"operations": 500, "portfolio": 500})

    for call in (spot.pull, securities.pull, securities.normalized_positions, spot.test):
        with pytest.raises(AdapterError) as failed:
            call(CREDENTIALS)
        assert KEY not in str(failed.value)


# --- The spot kind: what the Depot did in crypto ---


def test_the_spot_kind_states_crypto_trades_with_the_fee_apart():
    """The cash a trade moved includes the venue's fee — its own two rates
    say so — and the fee is stated apart, in the currency it was charged."""
    spot, _, _ = venue()

    harvest = spot.pull(CREDENTIALS)

    assert isinstance(harvest, Harvest)
    trades = {trade.external_id: trade for trade in harvest.trades}
    assert trades[trade_id(2)] == NormalizedTrade(
        external_id=trade_id(2),
        occurred_at=datetime(2024, 3, 4, 14, 31, 7, 482000, tzinfo=UTC),
        base_symbol="BTC",
        quote_symbol="EUR",
        side="buy",
        base_quantity=Decimal("0.01"),
        # The wallet was debited 500.00, 7.35 of it the fee.
        quote_quantity=Decimal("492.65"),
        fee_symbol="EUR",
        fee_quantity=Decimal("7.35"),
    )
    assert trades[trade_id(8)] == NormalizedTrade(
        external_id=trade_id(8),
        occurred_at=datetime(2024, 5, 10, 9, 45, tzinfo=UTC),
        base_symbol="BTC",
        quote_symbol="EUR",
        side="sell",
        base_quantity=Decimal("0.004"),
        # The wallet was credited 236.40 after the fee of 3.60.
        quote_quantity=Decimal("240.00"),
        fee_symbol="EUR",
        fee_quantity=Decimal("3.60"),
    )


def test_a_swap_is_one_coin_for_another_and_a_fee_no_leg_paid_is_no_leg():
    """A fee stated in a currency no leg moved was taken inside the rate —
    there is no balance it could have left."""
    spot, _, _ = venue(only(6))

    (swap,) = spot.pull(CREDENTIALS).trades

    assert swap == NormalizedTrade(
        external_id=trade_id(6),
        occurred_at=datetime(2024, 4, 1, 10, 15, 30, 120000, tzinfo=UTC),
        base_symbol="ETH",
        quote_symbol="BTC",
        side="buy",
        base_quantity=Decimal("0.05"),
        quote_quantity=Decimal("0.002"),
    )


def test_a_trade_whose_rates_say_the_fee_was_not_in_the_cash_states_none():
    """Where the cash leg reproduces the rate before the fee rather than the
    one after it, the fee did not come out of it — so none is subtracted."""
    payloads = only(2)
    payloads["operations"][0]["data"][0]["transactions"][0]["asset_amount"]["value"] = "492.65"

    spot, _, _ = venue(payloads)
    (trade,) = spot.pull(CREDENTIALS).trades

    assert trade.quote_quantity == Decimal("492.65")
    assert (trade.fee_symbol, trade.fee_quantity) == (None, None)


def test_a_coin_leaving_the_venue_is_a_transfer_with_its_network_fee():
    spot, _, _ = venue()

    harvest = spot.pull(CREDENTIALS)

    assert harvest.transfers == (
        NormalizedTransfer(
            external_id=transaction_id(21),
            occurred_at=datetime(2024, 4, 20, 12, 0, tzinfo=UTC),
            direction="out",
            symbol="BTC",
            quantity=Decimal("0.001"),
            fee_quantity=Decimal("0.0001"),
        ),
    )


def test_the_spot_kind_states_nothing_that_is_not_crypto():
    """Securities, cash movements and income are the securities kind's; the
    spot kind lands coins and what was paid for them, nothing else."""
    spot, _, _ = venue()

    harvest = spot.pull(CREDENTIALS)

    assert len(harvest.trades) == 3
    assert {trade.base_symbol for trade in harvest.trades} == {"BTC", "ETH"}
    assert harvest.cash_movements == () and harvest.fills == () and harvest.funding == ()


def test_a_coin_is_told_from_a_security_by_the_venues_asset_never_by_its_symbol():
    """The venue lists a share under the very symbol of a coin. What an
    operation moved is read from the asset it names."""
    payloads = only(6)
    payloads["assets"].append(
        {
            "id": "1f0f13b6-8630-6a24-b2e4-859c8eda3240",
            "name": "Eurotech SpA",
            "symbol": "ETH",
            "isin": "IT0003895668",
            "group": "equity_stock",
            "type": "equity_security",
        }
    )
    spot, securities, _ = venue(payloads)

    assert len(spot.pull(CREDENTIALS).trades) == 1
    assert securities.pull(CREDENTIALS).trades == ()


# --- The securities kind: securities, cash and income ---


def test_the_securities_kind_states_trades_by_isin_with_the_fee_a_cost_of_the_security():
    _, securities, _ = venue()

    harvest = securities.pull(CREDENTIALS)

    assert isinstance(harvest, BrokerHarvest)
    trades = {trade.external_id: trade for trade in harvest.trades}
    assert trades[trade_id(3)] == NormalizedSecurityTrade(
        external_id=trade_id(3),
        occurred_at=datetime(2024, 3, 5, 15, 31, 7, tzinfo=UTC),
        security=MICROSOFT,
        side="buy",
        quantity=Decimal("1"),
        # Debited 401.00, 1.00 of it the fee.
        settled_amount=Decimal("400.00"),
        settlement_currency="EUR",
        fees=(NormalizedFee("TRADE_FEE", Decimal("1.00"), "EUR", "security"),),
    )
    assert trades[trade_id(10)] == NormalizedSecurityTrade(
        external_id=trade_id(10),
        occurred_at=datetime(2024, 5, 20, 16, 0, tzinfo=UTC),
        security=MICROSOFT,
        side="sell",
        quantity=Decimal("0.5"),
        # Credited 219.00 after the fee of 1.00.
        settled_amount=Decimal("220.00"),
        settlement_currency="EUR",
        fees=(NormalizedFee("TRADE_FEE", Decimal("1.00"), "EUR", "security"),),
    )


def test_a_savings_plan_purchase_is_a_trade_like_any_other():
    """Only a savings plan's transactions carry a type of their own; what
    makes a trade is one thing leaving and another arriving under one trade."""
    _, securities, _ = venue(only(4))

    (trade,) = securities.pull(CREDENTIALS).trades

    assert (trade.security, trade.side, trade.quantity) == (SP500, "buy", Decimal("0.2"))
    assert (trade.settled_amount, trade.fees) == (Decimal("100.00"), ())


def test_a_dividend_names_the_security_that_paid_and_interest_names_none():
    _, securities, _ = venue()

    harvest = securities.pull(CREDENTIALS)

    assert set(harvest.dividends) == {
        NormalizedDividend(
            external_id=transaction_id(17),
            occurred_at=datetime(2024, 5, 16, 11, 20, tzinfo=UTC),
            kind="dividend",
            # 0.62 was paid and 0.17 of it taken as tax before it arrived:
            # the net lands, the gross stands beside it.
            amount=Decimal("0.45"),
            currency="EUR",
            security=MICROSOFT,
            gross_amount=Decimal("0.62"),
            gross_currency="EUR",
        ),
        NormalizedDividend(
            external_id=transaction_id(13),
            occurred_at=datetime(2024, 6, 1, 3, 0, tzinfo=UTC),
            kind="interest",
            amount=Decimal("1.25"),
            currency="EUR",
        ),
    }


def test_cash_entering_and_a_standalone_fee_each_arrive_as_what_they_are():
    _, securities, _ = venue()

    harvest = securities.pull(CREDENTIALS)

    assert harvest.cash_movements == (
        NormalizedCashMovement(
            external_id=transaction_id(12),
            occurred_at=datetime(2024, 3, 1, 8, 30, tzinfo=UTC),
            direction="in",
            currency="EUR",
            amount=Decimal("2000.00"),
        ),
    )
    assert harvest.account_fees == (
        NormalizedAccountFee(
            external_id=transaction_id(14),
            occurred_at=datetime(2024, 5, 30, 3, 0, tzinfo=UTC),
            amount=Decimal("1.50"),
            currency="EUR",
        ),
    )


def test_a_fee_charged_with_a_cash_withdrawal_is_a_fee_of_its_own():
    payloads = only(1)
    (moved,) = payloads["operations"][0]["data"][0]["transactions"]
    payloads["operations"][0]["data"][0]["operation_type"] = "withdrawal"
    moved.update(flow="OUTGOING", fee_amount={"value": "0.90", "currency_id": EUR_ID})
    _, securities, _ = venue(payloads)

    harvest = securities.pull(CREDENTIALS)

    (movement,) = harvest.cash_movements
    assert (movement.direction, movement.amount) == ("out", Decimal("2000.00"))
    (fee,) = harvest.account_fees
    assert (fee.external_id, fee.amount, fee.currency) == (
        f"{transaction_id(12)}-fee",
        Decimal("0.90"),
        "EUR",
    )


def test_what_neither_port_can_express_is_passed_over_by_name():
    """A metal has no ISIN and is no coin; a reward is income the exchange
    port has no record for. Each is named for the Admin — never landed,
    never dropped — and the securities kind speaks for the whole Depot."""
    spot, securities, _ = venue()

    passed = {event.external_id: event for event in securities.pull(CREDENTIALS).passed_over}

    assert set(passed) == {trade_id(5), transaction_id(22)}
    assert "Gold" in passed[trade_id(5)].description
    assert "35.50 EUR" in passed[trade_id(5)].description
    assert "reward" in passed[transaction_id(22)].description
    assert "0.0003 ETH" in passed[transaction_id(22)].description
    assert passed[transaction_id(22)].occurred_at == datetime(2024, 4, 10, tzinfo=UTC)
    # Nothing of them reaches the spot kind's records either.
    harvest = spot.pull(CREDENTIALS)
    assert all(trade.base_symbol != "XAU" for trade in harvest.trades)
    assert all(transfer.direction == "out" for transfer in harvest.transfers)


def test_a_tax_with_no_income_beside_it_is_passed_over_by_name():
    """A withholding is declared on what it was withheld from, never booked
    as a cost — and here nothing says what that was."""
    payloads = only(11)
    del payloads["operations"][0]["data"][0]["transactions"][0]
    _, securities, _ = venue(payloads)

    harvest = securities.pull(CREDENTIALS)

    assert harvest.dividends == ()
    (passed,) = harvest.passed_over
    assert passed.external_id == transaction_id(18)
    assert "tax" in passed.description and "0.17 EUR" in passed.description


def test_staking_moves_nothing_in_or_out_of_the_depot():
    """Staked coins stay the Admin's and stay at the venue: no record, and
    nothing to record by hand."""
    spot, securities, _ = venue(only(7))

    assert spot.pull(CREDENTIALS) == Harvest()
    assert securities.pull(CREDENTIALS).passed_over == ()


def test_an_operation_type_the_adapter_does_not_know_is_passed_over_never_guessed():
    """The venue documents no vocabulary for an operation's type. One the
    adapter cannot read is named with the sync rather than booked as
    something it may not be — and the rest of the history still lands."""
    payloads = only(1, 3)
    payloads["operations"][0]["data"][1]["operation_type"] = "bonus"
    _, securities, _ = venue(payloads)

    harvest = securities.pull(CREDENTIALS)

    assert harvest.cash_movements == ()
    assert len(harvest.trades) == 1
    (passed,) = harvest.passed_over
    assert "bonus" in passed.description and "2000.00 EUR" in passed.description


def test_a_movement_that_takes_another_back_is_passed_over():
    payloads = only(1)
    (moved,) = payloads["operations"][0]["data"][0]["transactions"]
    moved.update(flow="OUTGOING", compensates="7a000000-0000-4000-8000-000000000099")
    _, securities, _ = venue(payloads)

    harvest = securities.pull(CREDENTIALS)

    assert harvest.cash_movements == ()
    (passed,) = harvest.passed_over
    assert "takes back" in passed.description


def test_an_asset_the_venue_no_longer_lists_is_passed_over_not_refused():
    payloads = only(3)
    payloads["assets"] = [row for row in payloads["assets"] if row["id"] != MSFT_ID]
    _, securities, _ = venue(payloads)

    harvest = securities.pull(CREDENTIALS)

    assert harvest.trades == ()
    (passed,) = harvest.passed_over
    assert MSFT_ID in passed.description


# --- Capabilities, paging and failure ---


def test_both_kinds_declare_an_unbounded_lookback_and_the_broker_reports_its_period():
    spot, securities, _ = venue()

    assert spot.lookback_days is None and securities.lookback_days is None
    assert securities.pull(CREDENTIALS).covered == CoveredPeriod(start=None, end=NOW)


def test_every_page_is_followed_by_the_cursor_the_last_answer_stated():
    """And a cursor of whole seconds goes back with milliseconds — the venue
    restarts the listing otherwise."""
    spot, _, requests = venue()

    spot.pull(CREDENTIALS)

    cursors = [
        request.url.params.get("cursor")
        for request in requests
        if request.url.path == "/v1/operations"
    ]
    assert cursors == [None, base64.b64encode(b"2024-04-10T00:00:00.000Z").decode()]


def test_a_cursor_that_does_not_advance_is_refused_rather_than_followed_forever():
    payloads = recorded()
    payloads["operations"] = [payloads["operations"][0]]
    spot, _, _ = venue(payloads)

    with pytest.raises(AdapterError, match="did not advance"):
        spot.pull(CREDENTIALS)


def test_exhausting_the_page_budget_raises_rather_than_truncates(monkeypatch):
    monkeypatch.setattr(bitpanda, "_MAX_PAGES", 1)
    spot, _, _ = venue()

    with pytest.raises(AdapterError, match="truncated"):
        spot.pull(CREDENTIALS)


def test_a_rate_limited_request_waits_and_asks_again():
    answers = iter([429, 200])
    slept: list[float] = []

    def answer(request: httpx.Request) -> httpx.Response:
        status = next(answers) if request.url.path == "/v1/portfolio" else 200
        if status == 429:
            return httpx.Response(429)
        name = {**_ACCOUNT_PATHS, **_PUBLIC_PATHS}[request.url.path]
        payload = RECORDED[name]
        return httpx.Response(200, json={"data": payload} if name == "assets" else payload)

    adapter = BitpandaSecuritiesAdapter(
        client=httpx.Client(transport=httpx.MockTransport(answer)),
        now=lambda: NOW,
        sleep=slept.append,
    )

    assert len(adapter.normalized_positions(CREDENTIALS)) == 7
    assert slept == [1]


def test_a_row_the_adapter_cannot_read_is_an_adapter_error():
    payloads = only(2)
    del payloads["operations"][0]["data"][0]["transactions"][0]["credited_at"]
    spot, securities, _ = venue(payloads)

    for adapter in (spot, securities):
        with pytest.raises(AdapterError, match="could not read"):
            adapter.pull(CREDENTIALS)


def test_an_empty_depot_pulls_clean_empty_harvests():
    spot, securities, _ = venue(only())

    assert spot.pull(CREDENTIALS) == Harvest()
    assert securities.pull(CREDENTIALS) == BrokerHarvest(covered=CoveredPeriod(start=None, end=NOW))


# --- Positions: for Reconciliation alone ---


def test_positions_state_the_whole_depot_a_security_by_isin_the_rest_by_symbol():
    """One kind speaks for the Depot, so a reconciliation against the one
    Account sees everything it holds: securities by ISIN — the venue's two
    listings of one paper alike — coins and cash by symbol."""
    _, securities, _ = venue()

    positions = securities.normalized_positions(CREDENTIALS)

    assert set(positions) == {
        NormalizedPosition(symbol="EUR", quantity=Decimal("1419.10"), as_of=NOW),
        NormalizedPosition(symbol="BTC", quantity=Decimal("0.0029"), as_of=NOW),
        NormalizedPosition(symbol="ETH", quantity=Decimal("0.0503"), as_of=NOW),
        NormalizedPosition(symbol="MSFT", quantity=Decimal("0.5"), as_of=NOW, isin="US5949181045"),
        NormalizedPosition(symbol="MSFT", quantity=Decimal("0.25"), as_of=NOW, isin="US5949181045"),
        NormalizedPosition(symbol="SXR8", quantity=Decimal("0.2"), as_of=NOW, isin="IE00B5BMR087"),
        NormalizedPosition(symbol="XAU", quantity=Decimal("0.5"), as_of=NOW),
    }


def test_the_spot_kind_states_no_positions_so_the_depot_is_reconciled_once():
    spot, securities, _ = venue()

    assert not isinstance(spot, StatesNormalizedPositions)
    assert isinstance(securities, StatesNormalizedPositions)


def test_a_harvest_has_no_place_for_a_position():
    _, securities, _ = venue()

    harvest = securities.pull(CREDENTIALS)

    assert not any(
        isinstance(record, NormalizedPosition)
        for records in vars(harvest).values()
        if isinstance(records, tuple)
        for record in records
    )


# --- The registry ---


def test_bitpanda_ships_as_a_kind_of_each_port_plus_a_registry_entry():
    """The broker port took its second venue unchanged; the coins a Depot
    holds beside its securities arrive through the exchange port."""
    entry = VENUES["bitpanda"]

    assert [(type(adapter), adapter.kind) for adapter in entry.adapters] == [
        (BitpandaSpotAdapter, "spot"),
        (BitpandaSecuritiesAdapter, "securities"),
    ]
    assert (entry.requires_secret, entry.requires_passphrase) == (False, False)
    for scope in ("Balances", "Transaction", "Trade (Write)", "Earn (Write)"):
        assert scope in entry.required_scope
    assert get_venue_adapters()["bitpanda"] == entry.adapters


def test_the_recorded_payloads_are_json_clean():
    assert json.loads(json.dumps(RECORDED)) == RECORDED

"""The OKX adapters against recorded venue responses (ticket 36): raw
payloads in the venue's documented shapes in, normalized records out. No live
call is ever made — the seam is the port, fed through a mock transport that
answers what the venue answers.

The payloads are the official API documentation's own example responses
(timestamps rebased into the lookback window); where the docs print no
example — a SWAP fill, a funding-fee bill — the row is authored from the
documented field tables and marked as such. The mock venue honours each
endpoint's real pagination contract: fills and bills page backwards by
billId (`after` = strictly earlier), asset transfer history by timestamp
(`after` = strictly earlier ts), fiat order history by inclusive time
filters (`after` = begin, `before` = end).
"""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from open_leprechaun.adapters import get_exchange_adapters
from open_leprechaun.ports import okx
from open_leprechaun.ports.exchange import AdapterError
from open_leprechaun.ports.okx import BASE_URL, OkxFuturesAdapter, OkxSpotAdapter, _sign
from open_leprechaun.services.connections import Credentials

CREDENTIALS = Credentials(key="the-key", secret="the-secret", passphrase="the-passphrase")

NOW_MS = int(datetime.now(UTC).timestamp() * 1000)
DAY_MS = 24 * 3600 * 1000

# The API documentation's own example rows, timestamps rebased into the
# lookback window; monotonic billIds so id-order matches time-order, as the
# venue's cursor pagination presumes.

A_SPOT_FILL = {
    "side": "buy",
    "fillSz": "0.00192834",
    "fillPx": "51858",
    "fee": "-0.00000192834",
    "fillPnl": "0",
    "ordId": "680800019749904384",
    "feeRate": "-0.001",
    "instType": "SPOT",
    "instId": "BTC-USDT",
    "clOrdId": "",
    "posSide": "net",
    "billId": "680800019754098688",
    "subType": "1",
    "tag": "",
    "fillTime": str(NOW_MS - 10 * DAY_MS),
    "execType": "T",
    "tradeId": "744876980",
    "feeCcy": "BTC",
    "ts": str(NOW_MS - 10 * DAY_MS),
    "tradeQuoteCcy": "USDT",
}

A_DEPOSIT = {
    "actualDepBlkConfirm": "2",
    "amt": "1",
    "ccy": "USDT",
    "chain": "USDT-TRC20",
    "depId": "88881233",
    "from": "",
    "fromWdId": "",
    "state": "2",
    "to": "TN4hGjVXMzy9b4N1aGizqs",
    "ts": str(NOW_MS - 9 * DAY_MS),
    "txId": "fee235b3e812857d36bb0426917f0df1802",
}

A_WITHDRAWAL = {
    "note": "",
    "chain": "ETH-Ethereum",
    "fee": "0.007",
    "feeCcy": "ETH",
    "ccy": "ETH",
    "clientId": "",
    "amt": "0.029809",
    "txId": "0x35cb360a174d",
    "from": "156359",
    "to": "0xa30d1fab7CF18C7B6C579",
    "state": "2",
    "ts": str(NOW_MS - 8 * DAY_MS),
    "nonTradableAsset": False,
    "wdId": "15447421",
}

A_FIAT_DEPOSIT = {
    "cTime": str(NOW_MS - 7 * DAY_MS),
    "uTime": str(NOW_MS - 7 * DAY_MS),
    "ordId": "024041201450544699",
    "paymentMethod": "SEPA",
    "paymentAcctId": "20",
    "amt": "10000",
    "fee": "0",
    "ccy": "EUR",
    "state": "completed",
    "clientId": "",
}

A_FIAT_WITHDRAWAL = {
    "cTime": str(NOW_MS - 6 * DAY_MS),
    "uTime": str(NOW_MS - 6 * DAY_MS),
    "ordId": "124041201450544699",
    "paymentMethod": "SEPA",
    "paymentAcctId": "20",
    "amt": "2000",
    "fee": "0",
    "ccy": "EUR",
    "state": "completed",
    "clientId": "194a6975e98246538faeb0fab0d502df",
}


# Instrument descriptions as the live public endpoint answers them (captured
# 2026-08-10), abridged to the fields the adapter reads.
LINEAR_SWAP = {
    "instType": "SWAP",
    "instId": "BTC-USDT-SWAP",
    "ctType": "linear",
    "ctVal": "0.01",
    "ctValCcy": "BTC",
    "ctMult": "1",
    "settleCcy": "USDT",
    "state": "live",
}
INVERSE_SWAP = {
    "instType": "SWAP",
    "instId": "BTC-USD-SWAP",
    "ctType": "inverse",
    "ctVal": "100",
    "ctValCcy": "USD",
    "ctMult": "1",
    "settleCcy": "BTC",
    "state": "live",
}

# The docs print no SWAP example for fills-history — authored from the
# documented field table: fillSz in contracts, posSide stated in hedge mode,
# fillPnl the venue's own realised result on a close, fee in the settlement
# asset, negative when charged.
A_SWAP_FILL = {
    "side": "sell",
    "fillSz": "5",
    "fillPx": "52000",
    "fee": "-1.3",
    "fillPnl": "71",
    "ordId": "680800019749904001",
    "instType": "SWAP",
    "instId": "BTC-USDT-SWAP",
    "clOrdId": "",
    "posSide": "long",
    "billId": "680800019754098001",
    "subType": "5",
    "fillTime": str(NOW_MS - 5 * DAY_MS),
    "execType": "M",
    "tradeId": "744876981",
    "feeCcy": "USDT",
    "ts": str(NOW_MS - 5 * DAY_MS),
}

# Authored likewise from the bills-archive field table: type 8 is a funding
# fee, subType 173 an expense, and the docs say to read the payment from
# `pnl` — signed, negative paid.
A_FUNDING_BILL = {
    "bal": "8694.21",
    "balChg": "-0.0123",
    "billId": "623950854533513001",
    "ccy": "USDT",
    "execType": "",
    "fee": "0",
    "instId": "BTC-USDT-SWAP",
    "instType": "SWAP",
    "mgnMode": "cross",
    "notes": "",
    "ordId": "",
    "pnl": "-0.0123",
    "posBal": "0",
    "posBalChg": "0",
    "px": "52100",
    "subType": "173",
    "sz": "5",
    "ts": str(NOW_MS - 4 * DAY_MS),
    "type": "8",
}


def ok(rows):
    return httpx.Response(200, json={"code": "0", "msg": "", "data": list(rows)})


def _limited(rows, params, instant_of):
    limit = int(params.get("limit", "100"))
    return sorted(rows, key=instant_of, reverse=True)[:limit]


def by_bill_id(rows, params):
    """How fills-history and bills-archive answer: begin/end filter on ts,
    `after` returns records with a strictly smaller billId, newest first."""
    matching = [
        row
        for row in rows
        if ("begin" not in params or int(row["ts"]) >= int(params["begin"]))
        and ("end" not in params or int(row["ts"]) <= int(params["end"]))
        and ("after" not in params or int(row["billId"]) < int(params["after"]))
    ]
    return _limited(matching, params, lambda row: int(row["billId"]))


def by_instant(rows, params):
    """How asset deposit/withdrawal history answers: `after` returns records
    strictly earlier than the ts, `before` strictly newer, newest first."""
    matching = [
        row
        for row in rows
        if ("after" not in params or int(row["ts"]) < int(params["after"]))
        and ("before" not in params or int(row["ts"]) > int(params["before"]))
    ]
    return _limited(matching, params, lambda row: int(row["ts"]))


def by_fiat_window(rows, params):
    """How fiat order history answers: `after` and `before` are an inclusive
    begin/end filter on cTime, newest first."""
    matching = [
        row
        for row in rows
        if ("after" not in params or int(row["cTime"]) >= int(params["after"]))
        and ("before" not in params or int(row["cTime"]) <= int(params["before"]))
    ]
    return _limited(matching, params, lambda row: int(row["cTime"]))


def venue(
    adapter_type=OkxSpotAdapter,
    *,
    spot_fills=(),
    swap_fills=(),
    futures_fills=(),
    bills=(),
    deposits=(),
    withdrawals=(),
    fiat_deposits=(),
    fiat_withdrawals=(),
    instruments=(),
):
    """A recorded OKX behind a mock transport, answering each endpoint the
    way the documented API answers it."""
    requests = []

    def answer(request):
        requests.append(request)
        path = request.url.path
        params = request.url.params
        if path == "/api/v5/account/config":
            return ok([{"uid": "44705892", "acctLv": "2", "perm": "read_only"}])
        if path == "/api/v5/public/instruments":
            return ok([row for row in instruments if row["instType"] == params["instType"]])
        if path == "/api/v5/trade/fills-history":
            pools = {"SPOT": spot_fills, "SWAP": swap_fills, "FUTURES": futures_fills}
            return ok(by_bill_id(pools[params["instType"]], params))
        if path == "/api/v5/account/bills-archive":
            matching = [row for row in bills if row["type"] == params.get("type", row["type"])]
            return ok(by_bill_id(matching, params))
        if path == "/api/v5/asset/deposit-history":
            return ok(by_instant(deposits, params))
        if path == "/api/v5/asset/withdrawal-history":
            return ok(by_instant(withdrawals, params))
        if path == "/api/v5/fiat/deposit-order-history":
            return ok(by_fiat_window(fiat_deposits, params))
        if path == "/api/v5/fiat/withdrawal-order-history":
            return ok(by_fiat_window(fiat_withdrawals, params))
        raise AssertionError(f"Unexpected path {path}")

    adapter = adapter_type(
        client=httpx.Client(transport=httpx.MockTransport(answer)), throttle_seconds=0
    )
    return adapter, requests


# --- Signing: the exact scheme the live API accepts ---


def test_sign_prehashes_timestamp_method_path_and_body():
    signature = _sign(
        "the-secret",
        "2020-12-08T09:08:57.715Z",
        "GET",
        "/api/v5/account/config",
    )

    prehash = "2020-12-08T09:08:57.715ZGET/api/v5/account/config"
    expected = base64.b64encode(
        hmac.new(b"the-secret", prehash.encode(), hashlib.sha256).digest()
    ).decode()
    assert signature == expected


def test_sign_includes_the_query_string_in_the_signed_path():
    signature = _sign(
        "s",
        "2020-12-08T09:08:57.715Z",
        "GET",
        "/api/v5/trade/fills-history?instType=SPOT&limit=100",
    )

    prehash = "2020-12-08T09:08:57.715ZGET/api/v5/trade/fills-history?instType=SPOT&limit=100"
    expected = base64.b64encode(hmac.new(b"s", prehash.encode(), hashlib.sha256).digest()).decode()
    assert signature == expected


def test_every_request_carries_the_four_okx_headers_and_a_valid_signature():
    requests = []

    def answer(request):
        requests.append(request)
        return ok([{"acctLv": "2", "perm": "read_only", "uid": "1"}])

    adapter = OkxSpotAdapter(
        client=httpx.Client(transport=httpx.MockTransport(answer)), throttle_seconds=0
    )

    adapter.test(CREDENTIALS)

    (request,) = requests
    assert request.headers["OK-ACCESS-KEY"] == "the-key"
    assert request.headers["OK-ACCESS-PASSPHRASE"] == "the-passphrase"
    timestamp = request.headers["OK-ACCESS-TIMESTAMP"]
    assert timestamp.endswith("Z") and "T" in timestamp
    path_url = str(request.url).removeprefix(BASE_URL)
    prehash = f"{timestamp}GET{path_url}"
    expected = base64.b64encode(
        hmac.new(b"the-secret", prehash.encode(), hashlib.sha256).digest()
    ).decode()
    assert request.headers["OK-ACCESS-SIGN"] == expected


# --- The spot kind: recorded responses in, ledger-bound records out ---


def test_a_spot_pull_normalizes_the_documented_fill_into_a_trade():
    adapter, _ = venue(spot_fills=[A_SPOT_FILL])

    harvest = adapter.pull(CREDENTIALS)

    (trade,) = harvest.trades
    assert trade.external_id == "680800019754098688"
    assert trade.occurred_at == datetime.fromtimestamp(int(A_SPOT_FILL["ts"]) / 1000, tz=UTC)
    assert trade.occurred_at.tzinfo is UTC
    assert (trade.base_symbol, trade.quote_symbol) == ("BTC", "USDT")
    assert trade.side == "buy"
    assert trade.base_quantity == Decimal("0.00192834")
    # 0.00192834 BTC at 51858 USDT each.
    assert trade.quote_quantity == Decimal("99.99985572")
    # The venue charges the spot fee in the received asset, as a negative
    # amount — stated back as the positive quantity it cost.
    assert (trade.fee_symbol, trade.fee_quantity) == ("BTC", Decimal("0.00000192834"))
    assert harvest.fills == () and harvest.funding == ()


def test_a_spot_rebate_is_refused_rather_than_mislabelled():
    """The venue documents a positive fee as a rebate — income the trade
    shape cannot state as a fee, refused loudly instead of booked wrong."""
    rebate = {**A_SPOT_FILL, "fee": "0.00000192834"}
    adapter, _ = venue(spot_fills=[rebate])

    with pytest.raises(AdapterError, match="rebate"):
        adapter.pull(CREDENTIALS)


def test_a_zero_fee_spot_fill_carries_no_fee():
    free = {**A_SPOT_FILL, "fee": "0", "feeCcy": ""}
    adapter, _ = venue(spot_fills=[free])

    (trade,) = adapter.pull(CREDENTIALS).trades

    assert (trade.fee_symbol, trade.fee_quantity) == (None, None)


def test_a_spot_pull_normalizes_deposits_and_withdrawals_into_transfers():
    adapter, _ = venue(deposits=[A_DEPOSIT], withdrawals=[A_WITHDRAWAL])

    harvest = adapter.pull(CREDENTIALS)

    incoming, outgoing = sorted(harvest.transfers, key=lambda transfer: transfer.direction)
    assert incoming.external_id == "dep-88881233"
    assert incoming.direction == "in"
    assert (incoming.symbol, incoming.quantity) == ("USDT", Decimal("1"))
    assert incoming.fee_quantity is None
    assert outgoing.external_id == "wd-15447421"
    assert outgoing.direction == "out"
    assert (outgoing.symbol, outgoing.quantity) == ("ETH", Decimal("0.029809"))
    assert outgoing.fee_quantity == Decimal("0.007")


def test_a_transfer_still_in_flight_stays_out_until_it_settles():
    """Anything but the venue's success state is not yet a movement — it
    arrives on a later sync once the venue calls it settled."""
    pending = {**A_DEPOSIT, "depId": "99", "state": "0"}
    failed = {**A_WITHDRAWAL, "wdId": "98", "state": "-1"}
    adapter, _ = venue(deposits=[pending], withdrawals=[failed])

    assert adapter.pull(CREDENTIALS).transfers == ()


def test_a_withdrawal_fee_outside_its_own_asset_is_refused():
    foreign = {**A_WITHDRAWAL, "feeCcy": "OKB"}
    adapter, _ = venue(withdrawals=[foreign])

    with pytest.raises(AdapterError, match="OKB"):
        adapter.pull(CREDENTIALS)


def test_a_spot_pull_normalizes_fiat_orders_into_cash_movements():
    adapter, _ = venue(fiat_deposits=[A_FIAT_DEPOSIT], fiat_withdrawals=[A_FIAT_WITHDRAWAL])

    harvest = adapter.pull(CREDENTIALS)

    incoming, outgoing = sorted(harvest.cash_movements, key=lambda movement: movement.direction)
    assert incoming.external_id == "fiat-dep-024041201450544699"
    assert (incoming.direction, incoming.currency, incoming.amount) == (
        "in",
        "EUR",
        Decimal("10000"),
    )
    assert outgoing.external_id == "fiat-wd-124041201450544699"
    assert (outgoing.direction, outgoing.currency, outgoing.amount) == (
        "out",
        "EUR",
        Decimal("2000"),
    )


def test_a_fiat_order_not_yet_completed_stays_out():
    pending = {**A_FIAT_DEPOSIT, "ordId": "1", "state": "processing"}
    adapter, _ = venue(fiat_deposits=[pending])

    assert adapter.pull(CREDENTIALS).cash_movements == ()


def test_a_fiat_fee_is_refused_rather_than_guessed_into_the_amount():
    """The port's cash movement carries one amount; whether the venue's
    order fee sits inside or beside it is undocumented, so a fee-bearing
    order refuses instead of guessing."""
    charged = {**A_FIAT_WITHDRAWAL, "fee": "1"}
    adapter, _ = venue(fiat_withdrawals=[charged])

    with pytest.raises(AdapterError, match="fee"):
        adapter.pull(CREDENTIALS)


# --- The futures kind: contracts sized by the venue's own descriptions ---


def futures_venue(**kwargs):
    kwargs.setdefault("instruments", [LINEAR_SWAP, INVERSE_SWAP])
    return venue(OkxFuturesAdapter, **kwargs)


def test_a_futures_pull_normalizes_the_authored_swap_fill():
    adapter, _ = futures_venue(swap_fills=[A_SWAP_FILL])

    harvest = adapter.pull(CREDENTIALS)

    (fill,) = harvest.fills
    assert fill.external_id == "680800019754098001"
    assert fill.symbol == "BTC-USDT-SWAP"
    assert fill.side == "sell"
    assert fill.price == Decimal("52000")
    # 5 contracts of 0.01 BTC face value each.
    assert fill.size == Decimal("0.05")
    # The venue charges fees as negative amounts; the port states the cost.
    assert fill.fee == Decimal("1.3")
    assert fill.settlement_symbol == "USDT"
    assert fill.position_side == "long"
    assert fill.realized == Decimal("71")
    assert fill.inverse is False
    assert fill.occurred_at == datetime.fromtimestamp(int(A_SWAP_FILL["ts"]) / 1000, tz=UTC)
    assert harvest.trades == () and harvest.transfers == () and harvest.cash_movements == ()


def test_net_mode_leaves_the_position_side_unstated():
    net = {**A_SWAP_FILL, "posSide": "net"}
    adapter, _ = futures_venue(swap_fills=[net])

    (fill,) = adapter.pull(CREDENTIALS).fills

    assert fill.position_side is None


def test_an_inverse_contract_is_stated_as_inverse_with_its_usd_size():
    """A coin-margined contract settles in the coin; its size is the USD
    notional the venue denominates it in, and `inverse` is stated truthfully
    so derivation leans on the venue's own realised results (ticket 28)."""
    inverse = {
        **A_SWAP_FILL,
        "instId": "BTC-USD-SWAP",
        "feeCcy": "BTC",
        "fee": "-0.00002",
        "fillPnl": "0.0014",
        "billId": "680800019754098002",
    }
    adapter, _ = futures_venue(swap_fills=[inverse])

    (fill,) = adapter.pull(CREDENTIALS).fills

    assert fill.inverse is True
    # 5 contracts of 100 USD face value each.
    assert fill.size == Decimal("500")
    assert fill.settlement_symbol == "BTC"
    assert fill.fee == Decimal("0.00002")
    assert fill.realized == Decimal("0.0014")


def test_a_fill_on_a_contract_the_venue_no_longer_describes_is_refused():
    """No instrument description, no contract value — sizing the fill would
    be a guess, so the kind refuses and names the contract."""
    delisted = {**A_SWAP_FILL, "instId": "LUNA-USDT-SWAP"}
    adapter, _ = futures_venue(swap_fills=[delisted])

    with pytest.raises(AdapterError, match="LUNA-USDT-SWAP"):
        adapter.pull(CREDENTIALS)


def test_a_fill_fee_outside_the_settlement_asset_is_refused():
    foreign = {**A_SWAP_FILL, "feeCcy": "OKB"}
    adapter, _ = futures_venue(swap_fills=[foreign])

    with pytest.raises(AdapterError, match="OKB"):
        adapter.pull(CREDENTIALS)


def test_a_maker_rebate_arrives_as_a_negative_cost():
    """The venue documents a positive fee as a rebate; the port states costs
    positive, so a rebate is deliberately a negative fee — income the net
    accounting sums into the position (ticket 28), unlike the ledger's fee
    leg, which has no shape for it."""
    rebate = {**A_SWAP_FILL, "fee": "0.65"}
    adapter, _ = futures_venue(swap_fills=[rebate])

    (fill,) = adapter.pull(CREDENTIALS).fills

    assert fill.fee == Decimal("-0.65")


def test_a_description_stating_neither_variant_leaves_inverse_unstated():
    """A contract description without its linear/inverse statement must not
    default to linear — `inverse` stays None and derivation refuses the
    stream rather than book a coin-settled result in the wrong unit."""
    unstated = {key: value for key, value in LINEAR_SWAP.items() if key != "ctType"}
    adapter, _ = futures_venue(swap_fills=[A_SWAP_FILL], instruments=[unstated])

    (fill,) = adapter.pull(CREDENTIALS).fills

    assert fill.inverse is None


def test_a_futures_pull_normalizes_the_authored_funding_bill():
    adapter, _ = futures_venue(bills=[A_FUNDING_BILL])

    harvest = adapter.pull(CREDENTIALS)

    (payment,) = harvest.funding
    assert payment.external_id == "623950854533513001"
    assert payment.symbol == "BTC-USDT-SWAP"
    # The docs say to read the payment from `pnl` — signed, negative paid.
    assert payment.amount == Decimal("-0.0123")
    assert payment.settlement_symbol == "USDT"
    assert payment.occurred_at == datetime.fromtimestamp(int(A_FUNDING_BILL["ts"]) / 1000, tz=UTC)
    assert payment.position_side is None


def test_only_funding_bills_are_asked_for():
    """The bills archive holds every bill type; the walk asks the venue for
    funding fees alone rather than filtering the account's whole history."""
    adapter, requests = futures_venue(bills=[A_FUNDING_BILL])

    adapter.pull(CREDENTIALS)

    bills_requests = [r for r in requests if r.url.path == "/api/v5/account/bills-archive"]
    assert bills_requests and all(r.url.params["type"] == "8" for r in bills_requests)


# --- Pagination: the venue's own cursors, walked to the end ---


def test_a_full_page_continues_from_its_oldest_bill_id(monkeypatch):
    """Fills page backwards by bill id: `after` answers strictly earlier
    bills, so a full page's oldest id is the next request's cursor and no
    row is lost or repeated."""
    monkeypatch.setattr(okx, "_PAGE_LIMIT", 2)
    fills = [
        {**A_SPOT_FILL, "billId": str(680800019754098688 - n), "tradeId": str(744876980 + n)}
        for n in range(3)
    ]
    adapter, requests = venue(spot_fills=fills)

    harvest = adapter.pull(CREDENTIALS)

    assert sorted(trade.external_id for trade in harvest.trades) == sorted(
        fill["billId"] for fill in fills
    )
    spot_requests = [r for r in requests if r.url.path == "/api/v5/trade/fills-history"]
    assert spot_requests[1].url.params["after"] == str(680800019754098688 - 1)


def test_exhausting_the_page_budget_raises_rather_than_truncates(monkeypatch):
    monkeypatch.setattr(okx, "_PAGE_LIMIT", 2)
    monkeypatch.setattr(okx, "_MAX_PAGES", 2)
    fills = [
        {**A_SPOT_FILL, "billId": str(680800019754098688 - n), "tradeId": str(744876980 + n)}
        for n in range(6)
    ]
    adapter, _ = venue(spot_fills=fills)

    with pytest.raises(AdapterError, match="truncated"):
        adapter.pull(CREDENTIALS)


def test_transfers_sharing_the_page_boundary_instant_are_not_lost(monkeypatch):
    """The asset history pages by timestamp, and a full page can cut through
    one millisecond — the deposit beyond the cut, sharing its instant with
    the last one answered, must still arrive rather than be skipped past."""
    monkeypatch.setattr(okx, "_PAGE_LIMIT", 2)
    shared_instant = int(A_DEPOSIT["ts"]) - DAY_MS
    deposits = [
        A_DEPOSIT,
        {**A_DEPOSIT, "depId": "2", "ts": str(shared_instant)},
        {**A_DEPOSIT, "depId": "3", "ts": str(shared_instant)},
    ]
    adapter, _ = venue(deposits=deposits)

    harvest = adapter.pull(CREDENTIALS)

    assert sorted(transfer.external_id for transfer in harvest.transfers) == [
        "dep-2",
        "dep-3",
        "dep-88881233",
    ]


def test_the_pull_asks_for_the_declared_lookback_and_nothing_more():
    adapter, requests = venue(spot_fills=[A_SPOT_FILL])

    adapter.pull(CREDENTIALS)

    (spot_request, *_) = [r for r in requests if r.url.path == "/api/v5/trade/fills-history"]
    begin = int(spot_request.url.params["begin"])
    assert NOW_MS - 91 * DAY_MS <= begin <= NOW_MS - 89 * DAY_MS
    assert int(spot_request.url.params["end"]) >= NOW_MS - DAY_MS


def test_an_account_with_no_history_pulls_a_clean_empty_harvest():
    """Ticket 36: a venue account that has never traded answers empty pages
    everywhere — the pull completes with an empty harvest, never an error."""
    spot, _ = venue()
    futures, _ = futures_venue()

    for harvest in (spot.pull(CREDENTIALS), futures.pull(CREDENTIALS)):
        assert harvest.trades == ()
        assert harvest.transfers == ()
        assert harvest.cash_movements == ()
        assert harvest.fills == ()
        assert harvest.funding == ()


# --- The registry entry ---


def test_okx_ships_as_two_adapters_plus_a_registry_entry():
    """Adding the venue changed no service, router or screen: the registry
    answers its credential shape — secret and passphrase both — and its two
    kinds."""
    adapters = get_exchange_adapters()["okx"]

    assert [adapter.kind for adapter in adapters] == ["spot", "futures"]
    assert isinstance(adapters[0], OkxSpotAdapter)
    assert isinstance(adapters[1], OkxFuturesAdapter)
    assert all(adapter.lookback_days == 90 for adapter in adapters)


def test_the_recorded_payloads_are_json_clean():
    """The fixtures stand in for wire payloads — they must survive a JSON
    round trip unchanged, as real recordings would."""
    for payload in (
        A_SPOT_FILL,
        A_SWAP_FILL,
        A_FUNDING_BILL,
        A_DEPOSIT,
        A_WITHDRAWAL,
        A_FIAT_DEPOSIT,
        A_FIAT_WITHDRAWAL,
        LINEAR_SWAP,
        INVERSE_SWAP,
    ):
        assert json.loads(json.dumps(payload)) == payload


# --- Testing the credential ---


def config_venue(perm="read_only", status=200, payload=None):
    def answer(request):
        assert request.url.path == "/api/v5/account/config"
        if payload is not None:
            return httpx.Response(status, json=payload)
        return ok([{"uid": "44705892", "acctLv": "2", "posMode": "net_mode", "perm": perm}])

    return OkxSpotAdapter(
        client=httpx.Client(transport=httpx.MockTransport(answer)), throttle_seconds=0
    )


def test_a_successful_test_confirms_the_key_is_read_only():
    adapter = config_venue(perm="read_only")

    assert adapter.test(CREDENTIALS) == "Authenticated — the key is read-only."


def test_a_key_that_can_trade_or_withdraw_is_refused():
    """Read-only credentials only (ADR-0003): the venue states the key's own
    permissions, and a key that can do more than read fails its test with the
    scope to grant instead."""
    adapter = config_venue(perm="read_only,trade")

    with pytest.raises(AdapterError, match=r"Read permission"):
        adapter.test(CREDENTIALS)


def test_a_logical_error_becomes_an_adapter_error():
    """OKX signals failures as {"code" != "0", "msg"} — with HTTP 200 for
    most, an auth status for a refused credential — translated, never
    swallowed."""
    refused = {"code": "50111", "msg": "Invalid OK-ACCESS-KEY", "data": []}
    adapter = config_venue(status=401, payload=refused)

    with pytest.raises(AdapterError, match=r"50111.*Invalid OK-ACCESS-KEY"):
        adapter.test(CREDENTIALS)


def test_a_non_json_answer_becomes_an_adapter_error():
    adapter = OkxSpotAdapter(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(502, text="Bad Gateway"))
        ),
        throttle_seconds=0,
    )

    with pytest.raises(AdapterError, match="not JSON"):
        adapter.test(CREDENTIALS)


def test_no_secret_material_ever_reaches_an_error_sentence():
    """Whatever fails, the sentence recorded per kind must be safe to store
    and show — the key, secret and passphrase never appear in it."""
    refused = {"code": "50113", "msg": "Invalid Sign", "data": []}
    adapter = config_venue(status=401, payload=refused)

    with pytest.raises(AdapterError) as failed:
        adapter.test(CREDENTIALS)
    for secret_material in ("the-key", "the-secret", "the-passphrase"):
        assert secret_material not in str(failed.value)


def test_a_missing_secret_or_passphrase_is_refused_before_any_request():
    requests = []
    adapter = OkxSpotAdapter(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: requests.append(r) or ok([]))),
        throttle_seconds=0,
    )

    with pytest.raises(AdapterError, match="secret"):
        adapter.test(Credentials(key="k", secret=None, passphrase="p"))
    with pytest.raises(AdapterError, match="passphrase"):
        adapter.test(Credentials(key="k", secret="s", passphrase=None))
    assert requests == []

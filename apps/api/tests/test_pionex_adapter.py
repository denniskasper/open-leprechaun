"""The Pionex futures adapter against recorded venue responses (ticket 35):
raw payloads captured from the live API in, normalized fills and funding out.
No live call is ever made — the seam is the port, fed through a mock
transport that answers what the venue answered.
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from open_leprechaun.adapters import get_exchange_adapters
from open_leprechaun.ports import pionex
from open_leprechaun.ports.exchange import AdapterError
from open_leprechaun.ports.pionex import BASE_URL, PionexFuturesAdapter, _sign
from open_leprechaun.services.connections import Credentials

CREDENTIALS = Credentials(key="the-key", secret="the-secret", passphrase=None)

NOW_MS = int(datetime.now(UTC).timestamp() * 1000)
DAY_MS = 24 * 3600 * 1000

# Captured verbatim from the live API (previous implementation's recording).
A_FILL = {
    "id": 110000000006,
    "orderId": 11039096978211008,
    "symbol": "TAO_USDT_PERP",
    "side": "SELL",
    "role": "MAKER",
    "price": "249.35",
    "size": "1.816",
    "fee": "9.056392",
    "feeCoin": "USDT",
    "feeType": "LIQUIDATION",
    "timestamp": NOW_MS - 10 * DAY_MS,
}

A_FUNDING = {
    "symbol": "TAO_USDT_PERP",
    "fundingFee": "-0.5",
    "fundingCoin": "USDT",
    "fundingRate": "0.0001",
    "timestamp": NOW_MS - 9 * DAY_MS,
}

AN_ORDER = {"orderId": 1, "symbol": "TAO_USDT_PERP", "updateTime": NOW_MS - 11 * DAY_MS}
A_SPOT_ORDER = {"orderId": 2, "symbol": "BTC_USDT", "updateTime": NOW_MS - 11 * DAY_MS}


def ok(payload):
    return httpx.Response(200, json={"result": True, **payload})


def in_window(rows, request):
    """What the venue would answer: the newest rows inside the requested
    span, at most `limit` of them."""
    start = int(request.url.params["startTime"])
    end = int(request.url.params["endTime"])
    limit = int(request.url.params["limit"])
    matching = [row for row in rows if start <= int(row["timestamp"]) <= end]
    return sorted(matching, key=lambda row: int(row["timestamp"]), reverse=True)[:limit]


def venue(fills=(), fundings=(), orders=(), open_orders=(), balances=()):
    """A recorded Pionex behind a mock transport, answering each endpoint
    the way the live API answers it."""
    requests = []

    def answer(request):
        requests.append(request)
        path = request.url.path
        if path == "/api/v1/account/balances":
            return ok({"data": {"balances": list(balances)}})
        if path == "/uapi/v1/trade/openOrders":
            return ok({"data": {"orders": list(open_orders)}})
        if path == "/uapi/v1/trade/historyOrders":
            return ok({"data": {"orders": list(orders)}})
        if path == "/uapi/v1/trade/fills":
            return ok({"data": {"fills": in_window(fills, request)}})
        if path == "/uapi/v1/trade/fundingFee":
            return ok({"data": {"fundings": in_window(fundings, request)}})
        raise AssertionError(f"Unexpected path {path}")

    adapter = PionexFuturesAdapter(
        client=httpx.Client(transport=httpx.MockTransport(answer)), throttle_seconds=0
    )
    return adapter, requests


# --- Signing: the exact scheme the live API accepts ---


def test_sign_sorts_params_and_keeps_the_timestamp_only_in_the_query():
    path_url, signature = _sign(
        "testsecret",
        "GET",
        "/uapi/v1/trade/fills",
        {"symbol": "BTC_USDT_PERP", "limit": "100"},
        timestamp="1700000000000",
    )

    # Params (timestamp included) sorted alphabetically: limit < symbol < timestamp.
    assert path_url == (
        "/uapi/v1/trade/fills?limit=100&symbol=BTC_USDT_PERP&timestamp=1700000000000"
    )
    # Signed string = METHOD + PATH_URL; the timestamp lives only in the
    # query, never appended a second time.
    expected = hmac.new(b"testsecret", ("GET" + path_url).encode(), hashlib.sha256).hexdigest()
    assert signature == expected


def test_sign_appends_the_body_for_a_post():
    path_url, signature = _sign("s", "POST", "/x", {}, body='{"a":1}', timestamp="1")

    expected = hmac.new(b"s", ("POST" + path_url + '{"a":1}').encode(), hashlib.sha256).hexdigest()
    assert signature == expected


def test_every_request_carries_the_key_and_a_valid_signature():
    adapter, requests = venue(balances=[{"coin": "USDT"}, {"coin": "BTC"}])

    adapter.test(CREDENTIALS)

    (request,) = requests
    assert request.headers["PIONEX-KEY"] == "the-key"
    path_url = str(request.url).removeprefix(BASE_URL)
    expected = hmac.new(b"the-secret", ("GET" + path_url).encode(), hashlib.sha256).hexdigest()
    assert request.headers["PIONEX-SIGNATURE"] == expected


# --- Testing the credential ---


def test_a_successful_test_answers_what_the_venue_showed():
    adapter, _ = venue(balances=[{"coin": "USDT"}, {"coin": "BTC"}])

    assert adapter.test(CREDENTIALS) == "Authenticated — 2 account balances visible."


def test_a_logical_error_becomes_an_adapter_error():
    """Pionex signals failures with HTTP 200 + {result: false, code,
    message} — translated, never swallowed."""

    def refused(request):
        return httpx.Response(
            200, json={"result": False, "code": "APIKEY_LOST", "message": "apikey not found"}
        )

    adapter = PionexFuturesAdapter(
        client=httpx.Client(transport=httpx.MockTransport(refused)), throttle_seconds=0
    )

    with pytest.raises(AdapterError, match=r"APIKEY_LOST.*apikey not found"):
        adapter.test(CREDENTIALS)


def test_a_non_json_answer_becomes_an_adapter_error():
    adapter = PionexFuturesAdapter(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(502, text="Bad Gateway"))
        ),
        throttle_seconds=0,
    )

    with pytest.raises(AdapterError, match="not JSON"):
        adapter.test(CREDENTIALS)


def test_a_missing_secret_is_refused_before_any_request():
    adapter, requests = venue()

    with pytest.raises(AdapterError, match="secret"):
        adapter.test(Credentials(key="k", secret=None, passphrase=None))
    assert requests == []


# --- Pulling: recorded responses in, normalized records out ---


def test_pull_normalizes_the_recorded_fill_and_funding():
    adapter, _ = venue(fills=[A_FILL], fundings=[A_FUNDING], orders=[AN_ORDER])

    harvest = adapter.pull(CREDENTIALS)

    (fill,) = harvest.fills
    assert fill.external_id == "110000000006"
    assert fill.symbol == "TAO_USDT_PERP"
    assert fill.side == "sell"
    assert fill.price == Decimal("249.35")
    assert fill.size == Decimal("1.816")
    assert fill.fee == Decimal("9.056392")
    assert fill.settlement_symbol == "USDT"
    assert fill.occurred_at == datetime.fromtimestamp(A_FILL["timestamp"] / 1000, tz=UTC)
    assert fill.occurred_at.tzinfo is UTC
    # Pionex states none of the enrichment trio; a USDT-quoted perp is its
    # linear contract.
    assert (fill.position_side, fill.reduce_only, fill.realized) == (None, None, None)
    assert fill.inverse is False

    (funding,) = harvest.funding
    assert funding.external_id == f"TAO_USDT_PERP|{A_FUNDING['timestamp']}"
    assert funding.amount == Decimal("-0.5")
    assert funding.settlement_symbol == "USDT"
    assert funding.symbol == "TAO_USDT_PERP"
    assert harvest.trades == () and harvest.transfers == () and harvest.cash_movements == ()


def test_discovery_keeps_perp_symbols_from_open_and_closed_orders():
    """The spot order is not a perp and stays out; open and closed orders
    both contribute."""
    open_order = {"orderId": 3, "symbol": "BTC_USDT_PERP"}
    adapter, requests = venue(orders=[AN_ORDER, A_SPOT_ORDER], open_orders=[open_order])

    adapter.pull(CREDENTIALS)

    fills_requests = [r for r in requests if r.url.path == "/uapi/v1/trade/fills"]
    assert sorted({r.url.params["symbol"] for r in fills_requests}) == [
        "BTC_USDT_PERP",
        "TAO_USDT_PERP",
    ]


def test_the_lookback_is_walked_in_windows_the_api_accepts():
    """90 days of lookback arrive as spans of at most 60 days each — the
    venue caps the span per request, the adapter absorbs it."""
    adapter, requests = venue(fills=[A_FILL], orders=[AN_ORDER])

    adapter.pull(CREDENTIALS)

    spans = [
        int(r.url.params["endTime"]) - int(r.url.params["startTime"])
        for r in requests
        if r.url.path == "/uapi/v1/trade/fills"
    ]
    assert len(spans) == 2
    assert all(span <= 60 * DAY_MS for span in spans)
    covered = [
        (int(r.url.params["startTime"]), int(r.url.params["endTime"]))
        for r in requests
        if r.url.path == "/uapi/v1/trade/fills"
    ]
    assert min(start for start, _ in covered) >= NOW_MS - 91 * DAY_MS


def test_a_full_page_moves_the_cursor_onto_the_oldest_instant(monkeypatch):
    """A page at the limit means more rows remain — the next request ends
    *on* the oldest instant answered, never past it, until a short page
    closes the window. The boundary row comes back and is deduplicated."""
    monkeypatch.setattr(pionex, "_PAGE_LIMIT", 2)
    older = {**A_FILL, "id": 110000000001, "timestamp": A_FILL["timestamp"] - DAY_MS}
    oldest = {**A_FILL, "id": 110000000000, "timestamp": A_FILL["timestamp"] - 2 * DAY_MS}
    adapter, requests = venue(fills=[A_FILL, older, oldest], orders=[AN_ORDER])

    harvest = adapter.pull(CREDENTIALS)

    assert [fill.external_id for fill in harvest.fills] == [
        "110000000006",
        "110000000001",
        "110000000000",
    ]
    fills_requests = [r for r in requests if r.url.path == "/uapi/v1/trade/fills"]
    second = fills_requests[1]
    assert int(second.url.params["endTime"]) == older["timestamp"]


def test_rows_sharing_the_page_boundary_instant_are_not_lost(monkeypatch):
    """A full page can cut through the middle of one millisecond — the fill
    beyond the cut, sharing its instant with the last one answered, must
    still arrive rather than be silently skipped past."""
    monkeypatch.setattr(pionex, "_PAGE_LIMIT", 2)
    shared_instant = A_FILL["timestamp"] - DAY_MS
    at_boundary = {**A_FILL, "id": 110000000001, "timestamp": shared_instant}
    beyond_the_cut = {**A_FILL, "id": 110000000000, "timestamp": shared_instant}
    adapter, _ = venue(fills=[A_FILL, at_boundary, beyond_the_cut], orders=[AN_ORDER])

    harvest = adapter.pull(CREDENTIALS)

    assert sorted(fill.external_id for fill in harvest.fills) == [
        "110000000000",
        "110000000001",
        "110000000006",
    ]


def test_an_instant_the_api_cannot_page_past_terminates_the_walk(monkeypatch):
    """More rows at one instant than the API will ever answer for it: what
    the venue shows is delivered, the cursor steps past the drained instant,
    and the walk terminates instead of looping on the same page forever."""
    monkeypatch.setattr(pionex, "_PAGE_LIMIT", 2)
    instant = A_FILL["timestamp"]
    crowd = [{**A_FILL, "id": 110000000000 + n, "timestamp": instant} for n in range(4)]
    adapter, _ = venue(fills=crowd, orders=[AN_ORDER])

    harvest = adapter.pull(CREDENTIALS)

    assert len(harvest.fills) == 2


def test_exhausting_the_discovery_budget_raises_rather_than_truncates(monkeypatch):
    monkeypatch.setattr(pionex, "_MAX_HISTORY_PAGES", 3)
    monkeypatch.setattr(pionex, "_ORDER_PAGE_LIMIT", 1)
    pages = iter(range(1000))

    def endless(request):
        if request.url.path == "/uapi/v1/trade/historyOrders":
            n = next(pages)
            return ok(
                {"data": {"orders": [{"symbol": f"S{n}_USDT_PERP", "updateTime": NOW_MS - n}]}}
            )
        return ok({"data": {"orders": []}})

    adapter = PionexFuturesAdapter(
        client=httpx.Client(transport=httpx.MockTransport(endless)), throttle_seconds=0
    )

    with pytest.raises(AdapterError, match="truncated"):
        adapter.pull(CREDENTIALS)


def test_a_fee_outside_the_settlement_asset_is_refused():
    """The port states fees in the settlement asset; a fill charging its fee
    elsewhere refuses loudly instead of mislabelling the amount."""
    foreign_fee = {**A_FILL, "feeCoin": "BNB"}
    adapter, _ = venue(fills=[foreign_fee], orders=[AN_ORDER])

    with pytest.raises(AdapterError, match="BNB"):
        adapter.pull(CREDENTIALS)


def test_a_non_usdt_quote_leaves_inverse_unstated():
    """A perp quoted in anything but USDT is not a contract this API
    documents as linear — `inverse` stays None and derivation will refuse
    the stream rather than guess (ticket 28)."""
    coin_quoted = {**A_FILL, "symbol": "USDT_BTC_PERP", "feeCoin": "BTC"}
    order = {"orderId": 9, "symbol": "USDT_BTC_PERP", "updateTime": NOW_MS - 11 * DAY_MS}
    adapter, _ = venue(fills=[coin_quoted], orders=[order])

    (fill,) = adapter.pull(CREDENTIALS).fills

    assert fill.inverse is None
    assert fill.settlement_symbol == "BTC"


def test_no_secret_material_ever_reaches_an_error_sentence():
    """Whatever fails, the sentence recorded per kind must be safe to store
    and show — the key and secret never appear in it."""

    def refused(request):
        return httpx.Response(200, json={"result": False, "code": "X", "message": "denied"})

    adapter = PionexFuturesAdapter(
        client=httpx.Client(transport=httpx.MockTransport(refused)), throttle_seconds=0
    )

    with pytest.raises(AdapterError) as failed:
        adapter.test(CREDENTIALS)
    assert "the-key" not in str(failed.value)
    assert "the-secret" not in str(failed.value)


# --- The registry entry ---


def test_pionex_ships_as_one_adapter_plus_a_registry_entry():
    """Adding the venue changed no service, router or screen: the registry
    answers its credential shape and its one futures adapter."""
    adapters = get_exchange_adapters()["pionex"]

    assert [adapter.kind for adapter in adapters] == ["futures"]
    assert isinstance(adapters[0], PionexFuturesAdapter)


def test_the_recorded_payloads_are_json_clean():
    """The fixtures stand in for wire payloads — they must survive a JSON
    round trip unchanged, as real recordings would."""
    for payload in (A_FILL, A_FUNDING, AN_ORDER):
        assert json.loads(json.dumps(payload)) == payload

"""The Coinbase adapter against recorded venue responses (ticket 37): raw
payloads in the venue's documented shapes in, normalized records out. No live
call is ever made — the seam is the port, fed through a mock transport that
answers what the venue answers.

The payloads are the official API documentation's own example responses
wherever it prints one — the fill, the key permissions, the account, the
on-chain send. Where the docs print no example — a receive, a fiat deposit or
withdrawal — the row is authored from the documented transaction field table
and marked as such. The mock venue honours each API's real pagination
contract: fills by the opaque `cursor` the last answer stated, accounts and
transactions by the `next_uri` their pagination object names.
"""

import base64
import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from open_leprechaun.adapters import get_venue_adapters
from open_leprechaun.ports import coinbase
from open_leprechaun.ports.coinbase import CoinbaseSpotAdapter
from open_leprechaun.ports.exchange import (
    AdapterError,
    Harvest,
    NormalizedCashMovement,
    NormalizedTrade,
)
from open_leprechaun.services.connections import Credentials

KEY_NAME = "organizations/the-org/apiKeys/the-key-id"

# A throwaway signing key minted for this test run — the shape the venue
# issues (an ECDSA P-256 key as "EC PRIVATE KEY" PEM), never a real one.
SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())
PEM = SIGNING_KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption(),
).decode()

CREDENTIALS = Credentials(key=KEY_NAME, secret=PEM, passphrase=None)

# The documentation's example answer for a key's permissions, narrowed to the
# view-only key the application asks for.
VIEW_ONLY = {
    "can_view": True,
    "can_trade": False,
    "can_transfer": False,
    "portfolio_uuid": "12345678-1234-1234-1234-123456789012",
    "portfolio_type": "DEFAULT",
}

# The documentation's own example fill, verbatim.
A_FILL = {
    "entry_id": "22222-2222222-22222222",
    "trade_id": "1111-11111-111111",
    "order_id": "0000-000000-000000",
    "trade_time": "2021-05-31T09:59:59Z",
    "trade_type": "FILL",
    "price": "10000.00",
    "size": "0.001",
    "commission": "1.25",
    "product_id": "BTC-USD",
    "sequence_timestamp": "2021-05-31T09:58:59Z",
    "liquidity_indicator": "MAKER",
    "size_in_quote": False,
    "user_id": "3333-333333-3333333",
    "side": "BUY",
    "retail_portfolio_id": "4444-444444-4444444",
}

# The documentation's example account, abridged to the fields that matter,
# and a fiat one authored beside it from the account field table.
BTC_ACCOUNT = {
    "id": "2bbf394c-193b-5b2a-9155-3b4732659ede",
    "name": "My Wallet",
    "primary": True,
    "type": "wallet",
    "currency": {"code": "BTC", "name": "Bitcoin", "exponent": 8, "type": "crypto"},
    "balance": {"amount": "39.59000000", "currency": "BTC"},
    "created_at": "2024-01-31T20:49:02Z",
    "updated_at": "2024-01-31T20:49:02Z",
    "resource": "account",
    "resource_path": "/v2/accounts/2bbf394c-193b-5b2a-9155-3b4732659ede",
}
EUR_ACCOUNT = {
    "id": "58542935-67b5-56e1-a3f9-42686e07fa40",
    "name": "EUR Wallet",
    "primary": False,
    "type": "fiat",
    "currency": {"code": "EUR", "name": "Euro", "exponent": 2, "type": "fiat"},
    "balance": {"amount": "250.50", "currency": "EUR"},
    "created_at": "2024-01-31T20:49:02Z",
    "updated_at": "2024-01-31T20:49:02Z",
    "resource": "account",
    "resource_path": "/v2/accounts/58542935-67b5-56e1-a3f9-42686e07fa40",
}

# The documentation's transaction-resource example of an on-chain send, with
# two repairs the test states openly: the status is `completed` (the example
# is caught mid-flight), and `transaction_amount` is in BTC (the example
# prints "ETH" beside BTC amounts — a typo). The arithmetic is the docs' own:
# the account was debited 0.00133, of which 0.001 reached the recipient and
# 0.00033 paid the network.
AN_ONCHAIN_SEND = {
    "id": "57ffb4ae-0c59-5430-bcd3-3f98f797a66c",
    "type": "send",
    "status": "completed",
    "amount": {"amount": "-0.00133", "currency": "BTC"},
    "native_amount": {"amount": "-0.01", "currency": "USD"},
    "description": None,
    "created_at": "2015-03-11T13:13:35-07:00",
    "resource": "transaction",
    "resource_path": (
        "/v2/accounts/2bbf394c-193b-5b2a-9155-3b4732659ede"
        "/transactions/57ffb4ae-0c59-5430-bcd3-3f98f797a66c"
    ),
    "idem": "df087dce-92a8-45cf-b112-60aad22c0976",
    "network": {
        "status": "confirmed",
        "transaction_fee": {"amount": "0.00033", "currency": "BTC"},
        "transaction_amount": {"amount": "0.001", "currency": "BTC"},
    },
    "to": {"resource": "bitcoin_address", "address": "1AUJ8z5RuHRTqD1eikyfUUetzGmdWLGkpT"},
}

# The documentation's list example of a send that never touched a chain —
# to another Coinbase user — verbatim: no network fee is stated.
AN_OFFCHAIN_SEND = {
    "id": "3c04e35e-8e5a-5ff1-9155-00675db4ac02",
    "type": "send",
    "status": "completed",
    "amount": {"amount": "-0.00100000", "currency": "BTC"},
    "native_amount": {"amount": "-0.01", "currency": "USD"},
    "description": None,
    "created_at": "2015-03-11T13:13:35-07:00",
    "updated_at": "2015-03-26T15:55:43-07:00",
    "resource": "transaction",
    "resource_path": (
        "/v2/accounts/2bbf394c-193b-5b2a-9155-3b4732659ede"
        "/transactions/3c04e35e-8e5a-5ff1-9155-00675db4ac02"
    ),
    "network": {"status": "off_blockchain", "name": "bitcoin"},
    "to": {
        "id": "a6b4c2df-a62c-5d68-822a-dd4e2102e703",
        "resource": "user",
        "resource_path": "/v2/users/a6b4c2df-a62c-5d68-822a-dd4e2102e703",
    },
    "details": {"title": "Send bitcoin", "subtitle": "to User 2"},
}

# The docs print no receive and no fiat movement — authored from the
# documented transaction field table: `amount` is the account's own credit
# (positive) or debit (negative) in the account's currency.
A_RECEIVE = {
    "id": "9d6a7d1c-58d5-5a3b-b6a1-0d3b2c1f4e5a",
    "type": "receive",
    "status": "completed",
    "amount": {"amount": "0.25000000", "currency": "BTC"},
    "native_amount": {"amount": "2500.00", "currency": "EUR"},
    "description": None,
    "created_at": "2024-02-03T10:15:00Z",
    "resource": "transaction",
    "resource_path": (
        "/v2/accounts/2bbf394c-193b-5b2a-9155-3b4732659ede"
        "/transactions/9d6a7d1c-58d5-5a3b-b6a1-0d3b2c1f4e5a"
    ),
    "network": {"status": "confirmed", "name": "bitcoin"},
    "from": {"resource": "bitcoin_network"},
}
A_FIAT_DEPOSIT = {
    "id": "1f2e3d4c-5b6a-5978-8a9b-0c1d2e3f4a5b",
    "type": "fiat_deposit",
    "status": "completed",
    "amount": {"amount": "1000.00", "currency": "EUR"},
    "native_amount": {"amount": "1000.00", "currency": "EUR"},
    "description": None,
    "created_at": "2024-02-01T08:00:00Z",
    "resource": "transaction",
    "resource_path": (
        "/v2/accounts/58542935-67b5-56e1-a3f9-42686e07fa40"
        "/transactions/1f2e3d4c-5b6a-5978-8a9b-0c1d2e3f4a5b"
    ),
}
A_FIAT_WITHDRAWAL = {
    "id": "6a5b4c3d-2e1f-5a0b-9c8d-7e6f5a4b3c2d",
    "type": "fiat_withdrawal",
    "status": "completed",
    "amount": {"amount": "-400.00", "currency": "EUR"},
    "native_amount": {"amount": "-400.00", "currency": "EUR"},
    "description": None,
    "created_at": "2024-02-05T16:30:00Z",
    "resource": "transaction",
    "resource_path": (
        "/v2/accounts/58542935-67b5-56e1-a3f9-42686e07fa40"
        "/transactions/6a5b4c3d-2e1f-5a0b-9c8d-7e6f5a4b3c2d"
    ),
}


# The docs print no simple buy or sell — authored from rows the live API
# answers, every amount and id invented. An order states itself once per
# wallet it touched, each row naming the order under `buy` or `sell`: the
# coin's credit or debit, and — when the euros moved through the EUR wallet —
# that wallet's debit or credit of the order's total. A buy's total is its
# subtotal plus the fee, a sell's its subtotal less the fee.
_ORDER_PATH = "/v2/accounts/{}/transactions/{}"


def order_row(kind, order, *, row_id, account, amount, currency, total, subtotal, fee, paid_by):
    return {
        "id": row_id,
        "type": kind,
        "status": "completed",
        "amount": {"amount": amount, "currency": currency},
        "native_amount": {
            "amount": total if not amount.startswith("-") else f"-{total}",
            "currency": "EUR",
        },
        "created_at": "2024-03-04T09:30:00Z",
        "resource": "transaction",
        "resource_path": _ORDER_PATH.format(account["id"], row_id),
        kind: {
            "id": order,
            "fee": {"amount": fee, "currency": "EUR"},
            "subtotal": {"amount": subtotal, "currency": "EUR"},
            "total": {"amount": total, "currency": "EUR"},
            "payment_method_name": paid_by,
        },
    }


_WALLET_BUY = dict(total="250.00", subtotal="246.27", fee="3.73", paid_by="EUR Wallet")
A_WALLET_BUY = [
    order_row(
        "buy",
        "order-wallet-buy",
        row_id="row-wb-btc",
        account=BTC_ACCOUNT,
        amount="0.00500000",
        currency="BTC",
        **_WALLET_BUY,
    ),
    order_row(
        "buy",
        "order-wallet-buy",
        row_id="row-wb-eur",
        account=EUR_ACCOUNT,
        amount="-250.00",
        currency="EUR",
        **_WALLET_BUY,
    ),
]
# Paid by card: the euros never touch the venue account, so only the coin's
# wallet states the order.
A_CARD_BUY = order_row(
    "buy",
    "order-card-buy",
    row_id="row-cb-btc",
    account=BTC_ACCOUNT,
    amount="0.00200000",
    currency="BTC",
    total="120.00",
    subtotal="118.21",
    fee="1.79",
    paid_by="4111********1111",
)
_WALLET_SELL = dict(total="389.51", subtotal="395.42", fee="5.91", paid_by="EUR Wallet")
A_WALLET_SELL = [
    order_row(
        "sell",
        "order-wallet-sell",
        row_id="row-ws-btc",
        account=BTC_ACCOUNT,
        amount="-0.00800000",
        currency="BTC",
        **_WALLET_SELL,
    ),
    order_row(
        "sell",
        "order-wallet-sell",
        row_id="row-ws-eur",
        account=EUR_ACCOUNT,
        amount="389.51",
        currency="EUR",
        **_WALLET_SELL,
    ),
]


def _b64url_decode(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def paged(rows, request, path):
    """How the v2 API answers a list: at most `limit` rows after the
    `starting_after` id, and a `next_uri` naming the following page — null
    once the list is exhausted."""
    limit = int(request.url.params.get("limit", "25"))
    after = request.url.params.get("starting_after")
    start = 0
    if after is not None:
        start = next(index for index, row in enumerate(rows) if row["id"] == after) + 1
    page = rows[start : start + limit]
    more = start + limit < len(rows)
    return httpx.Response(
        200,
        json={
            "pagination": {
                "ending_before": None,
                "starting_after": after,
                "limit": limit,
                "order": "desc",
                "previous_uri": None,
                "next_uri": (
                    f"{path}?limit={limit}&starting_after={page[-1]['id']}" if more else None
                ),
            },
            "data": page,
        },
    )


def venue(*, fills=(), accounts=(), transactions=None, permissions=VIEW_ONLY):
    """A recorded Coinbase behind a mock transport, answering each endpoint
    the way the documented API answers it. `transactions` maps an account id
    to that account's rows."""
    requests = []
    transactions = transactions or {}
    fills = list(fills)

    def answer(request):
        requests.append(request)
        path = request.url.path
        params = request.url.params
        if path == "/api/v3/brokerage/key_permissions":
            return httpx.Response(200, json=permissions)
        if path == "/api/v3/brokerage/orders/historical/fills":
            # The cursor is opaque to the client; here it is simply the
            # offset of the next row, empty once nothing follows.
            start = int(params.get("cursor") or 0)
            limit = int(params.get("limit", "100"))
            following = start + limit
            return httpx.Response(
                200,
                json={
                    "fills": fills[start:following],
                    "cursor": str(following) if following < len(fills) else "",
                },
            )
        if path == "/v2/accounts":
            return paged(list(accounts), request, path)
        if path.startswith("/v2/accounts/") and path.endswith("/transactions"):
            account_id = path.split("/")[3]
            return paged(list(transactions.get(account_id, ())), request, path)
        raise AssertionError(f"Unexpected path {path}")

    adapter = CoinbaseSpotAdapter(
        client=httpx.Client(transport=httpx.MockTransport(answer)), throttle_seconds=0
    )
    return adapter, requests


# --- Signing: the JWT the live API accepts ---


def test_every_request_carries_a_bearer_jwt_signed_by_the_key():
    """The venue's documented token: ES256, the key name as `kid` and `sub`,
    issuer "cdp", two minutes of life, and a `uri` claim binding it to this
    one request — method, host and path, the query string left out."""
    adapter, requests = venue(fills=[A_FILL])

    adapter.pull(CREDENTIALS)

    fills_request = next(r for r in requests if r.url.path.endswith("/fills"))
    scheme, token = fills_request.headers["Authorization"].split(" ")
    assert scheme == "Bearer"
    header, payload, signature = token.split(".")
    stated_header = json.loads(_b64url_decode(header))
    claims = json.loads(_b64url_decode(payload))
    assert stated_header["alg"] == "ES256"
    assert stated_header["typ"] == "JWT"
    assert stated_header["kid"] == KEY_NAME
    assert stated_header["nonce"]
    assert claims["sub"] == KEY_NAME
    assert claims["iss"] == "cdp"
    assert claims["exp"] - claims["nbf"] == 120
    assert claims["uri"] == "GET api.coinbase.com/api/v3/brokerage/orders/historical/fills"
    raw = _b64url_decode(signature)
    assert len(raw) == 64
    SIGNING_KEY.public_key().verify(
        encode_dss_signature(int.from_bytes(raw[:32]), int.from_bytes(raw[32:])),
        f"{header}.{payload}".encode(),
        ec.ECDSA(hashes.SHA256()),
    )


def test_each_request_is_signed_afresh():
    """A token is bound to one request and carries a nonce — none is reused."""
    adapter, requests = venue(accounts=[BTC_ACCOUNT, EUR_ACCOUNT])

    adapter.pull(CREDENTIALS)

    tokens = [request.headers["Authorization"] for request in requests]
    assert len(tokens) > 1
    assert len(set(tokens)) == len(tokens)


@pytest.mark.parametrize(
    "pasted",
    [
        # As the venue's key file states it: one JSON string, newlines escaped.
        PEM.replace("\n", "\\n"),
        # As a single-line input leaves it: every line break gone.
        PEM.replace("\n", ""),
        PEM.replace("\n", " "),
        # A PKCS#8 export of the same key.
        SIGNING_KEY.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    ],
)
def test_the_secret_is_read_however_the_pem_was_pasted(pasted):
    adapter, _ = venue()

    detail = adapter.test(Credentials(key=KEY_NAME, secret=pasted, passphrase=None))

    assert detail == "Authenticated — the key is view-only."


def test_a_secret_that_is_no_private_key_is_refused_before_any_request():
    adapter, requests = venue()

    with pytest.raises(AdapterError, match="PEM") as failed:
        adapter.test(Credentials(key=KEY_NAME, secret="not-a-pem-at-all", passphrase=None))

    assert "not-a-pem-at-all" not in str(failed.value)
    assert requests == []


# The shape the venue's key page issues an Ed25519 key in: one base64 string
# of the 32-byte seed followed by the 32-byte public key.
ED25519_KEY = ed25519.Ed25519PrivateKey.generate()
ED25519_SECRET = base64.b64encode(
    ED25519_KEY.private_bytes_raw() + ED25519_KEY.public_key().public_bytes_raw()
).decode()


def test_an_ed25519_key_signs_its_token_eddsa():
    """The venue's default key type: the same token, `alg` EdDSA, the
    signature the key's own 64 bytes."""
    adapter, requests = venue(fills=[A_FILL])

    adapter.pull(Credentials(key=KEY_NAME, secret=ED25519_SECRET, passphrase=None))

    fills_request = next(r for r in requests if r.url.path.endswith("/fills"))
    header, payload, signature = fills_request.headers["Authorization"].split(" ")[1].split(".")
    stated_header = json.loads(_b64url_decode(header))
    claims = json.loads(_b64url_decode(payload))
    assert stated_header["alg"] == "EdDSA"
    assert stated_header["kid"] == claims["sub"] == KEY_NAME
    assert claims["uri"] == "GET api.coinbase.com/api/v3/brokerage/orders/historical/fills"
    ED25519_KEY.public_key().verify(_b64url_decode(signature), f"{header}.{payload}".encode())


@pytest.mark.parametrize(
    "pasted",
    [
        ED25519_SECRET,
        f"  {ED25519_SECRET}\n",
        # A PKCS#8 export of the same key.
        ED25519_KEY.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    ],
    ids=["as-shown", "padded", "pkcs8-pem"],
)
def test_an_ed25519_secret_is_read_however_it_was_pasted(pasted):
    adapter, _ = venue()

    detail = adapter.test(Credentials(key=KEY_NAME, secret=pasted, passphrase=None))

    assert detail == "Authenticated — the key is view-only."


def test_an_ed25519_secret_whose_halves_disagree_is_refused_before_any_request():
    """The second half is the first half's public key; a mismatch is a
    secret damaged in copying, caught before the venue answers a bare 401."""
    other = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    damaged = base64.b64encode(ED25519_KEY.private_bytes_raw() + other).decode()
    adapter, requests = venue()

    with pytest.raises(AdapterError, match="Ed25519") as failed:
        adapter.test(Credentials(key=KEY_NAME, secret=damaged, passphrase=None))

    assert damaged not in str(failed.value)
    assert requests == []


def test_a_key_of_another_algorithm_is_refused_with_the_ones_to_choose():
    """Only ECDSA P-256 and Ed25519 sign these APIs' tokens — any other key
    is refused at the test, naming both."""
    rsa_pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )
    adapter, requests = venue()

    with pytest.raises(AdapterError, match=r"ECDSA.*Ed25519"):
        adapter.test(Credentials(key=KEY_NAME, secret=rsa_pem, passphrase=None))
    assert requests == []


def test_a_missing_secret_is_refused_before_any_request():
    adapter, requests = venue()

    with pytest.raises(AdapterError, match="secret"):
        adapter.test(Credentials(key=KEY_NAME, secret=None, passphrase=None))
    assert requests == []


# --- The credential test: read-only enforced, not just requested ---


def test_a_successful_test_confirms_the_key_is_view_only():
    adapter, _ = venue()

    assert adapter.test(CREDENTIALS) == "Authenticated — the key is view-only."


@pytest.mark.parametrize(
    ("granted", "named"),
    [("can_trade", "Trade"), ("can_transfer", "Transfer")],
)
def test_a_key_that_can_trade_or_transfer_is_refused(granted, named):
    """Read-only credentials only (ADR-0003): the venue states the key's own
    permissions, and a key that can do more than view fails its test with the
    scope to grant instead."""
    adapter, _ = venue(permissions={**VIEW_ONLY, granted: True})

    with pytest.raises(AdapterError, match=rf"{named}.*View permission only"):
        adapter.test(CREDENTIALS)


def test_a_permission_left_unstated_is_not_taken_for_absent():
    """Only an explicit "no" proves a key cannot trade or transfer."""
    adapter, _ = venue(permissions={"can_view": True})

    with pytest.raises(AdapterError, match="Trade and Transfer"):
        adapter.test(CREDENTIALS)


def test_a_key_that_cannot_view_is_refused():
    adapter, _ = venue(permissions={**VIEW_ONLY, "can_view": False})

    with pytest.raises(AdapterError, match="View"):
        adapter.test(CREDENTIALS)


def failing(response):
    return CoinbaseSpotAdapter(
        client=httpx.Client(transport=httpx.MockTransport(lambda request: response)),
        throttle_seconds=0,
    )


def test_a_refused_credential_becomes_an_adapter_error():
    """The brokerage API refuses a bad token with a bare 401 and no JSON —
    translated, never swallowed."""
    adapter = failing(httpx.Response(401, text="Unauthorized\n"))

    with pytest.raises(AdapterError, match=r"401.*Unauthorized"):
        adapter.test(CREDENTIALS)


def test_both_error_dialects_state_the_venues_own_message():
    """The brokerage API answers {"error", "message"}; the account API
    answers {"errors": [{"id", "message"}]}."""
    brokerage = failing(
        httpx.Response(
            403,
            json={
                "error": "PERMISSION_DENIED",
                "error_details": "Missing required scopes",
                "message": "Missing required scopes",
            },
        )
    )
    account_api = failing(
        httpx.Response(404, json={"errors": [{"id": "not_found", "message": "Account not found"}]})
    )

    with pytest.raises(AdapterError, match=r"403.*Missing required scopes"):
        brokerage.test(CREDENTIALS)
    with pytest.raises(AdapterError, match=r"404.*Account not found"):
        account_api.pull(CREDENTIALS)


def test_a_non_json_answer_becomes_an_adapter_error():
    adapter = failing(httpx.Response(200, text="<html>maintenance</html>"))

    with pytest.raises(AdapterError, match="not JSON"):
        adapter.test(CREDENTIALS)


def test_no_secret_material_ever_reaches_an_error_sentence():
    """Whatever fails, the sentence recorded per kind must be safe to store
    and show — neither the key name nor the private key appears in it."""
    adapter = failing(httpx.Response(401, text="Unauthorized\n"))

    with pytest.raises(AdapterError) as failed:
        adapter.test(CREDENTIALS)
    body = "".join(PEM.splitlines()[1:-1])
    for secret_material in (KEY_NAME, body, body[:24]):
        assert secret_material not in str(failed.value)


# --- Trades: the brokerage API's fills ---


def test_a_pull_normalizes_the_documented_fill_into_a_trade():
    adapter, _ = venue(fills=[A_FILL])

    (trade,) = adapter.pull(CREDENTIALS).trades

    assert trade.external_id == "22222-2222222-22222222"
    assert trade.occurred_at == datetime(2021, 5, 31, 9, 59, 59, tzinfo=UTC)
    assert (trade.base_symbol, trade.quote_symbol) == ("BTC", "USD")
    assert trade.side == "buy"
    assert trade.base_quantity == Decimal("0.001")
    # 0.001 BTC at 10,000 — the quote side follows from the stated price.
    assert trade.quote_quantity == Decimal("10")
    # The commission is charged in the quote currency.
    assert (trade.fee_symbol, trade.fee_quantity) == ("USD", Decimal("1.25"))


def test_a_fill_sized_in_quote_states_its_base_from_the_price():
    """An order placed in the quote currency states `size` in it — 50 USD at
    10,000 bought 0.005 BTC."""
    sized_in_quote = {**A_FILL, "size_in_quote": True, "size": "50", "side": "SELL"}
    adapter, _ = venue(fills=[sized_in_quote])

    (trade,) = adapter.pull(CREDENTIALS).trades

    assert trade.side == "sell"
    assert trade.quote_quantity == Decimal("50")
    assert trade.base_quantity == Decimal("0.005")


def test_a_zero_commission_fill_carries_no_fee():
    adapter, _ = venue(fills=[{**A_FILL, "commission": "0"}])

    (trade,) = adapter.pull(CREDENTIALS).trades

    assert trade.fee_symbol is None
    assert trade.fee_quantity is None


def test_a_fill_that_amends_another_is_refused_by_name():
    adapter, _ = venue(fills=[{**A_FILL, "trade_type": "REVERSAL"}])

    with pytest.raises(AdapterError, match=r"22222-2222222-22222222.*REVERSAL"):
        adapter.pull(CREDENTIALS)


def test_only_spot_fills_are_asked_for():
    adapter, requests = venue()

    adapter.pull(CREDENTIALS)

    (fills_request,) = [r for r in requests if r.url.path.endswith("/fills")]
    assert fills_request.url.params["product_types"] == "SPOT"


# --- Transfers and cash movements: the account API's transactions ---


def test_an_onchain_send_is_a_transfer_out_with_its_network_fee_apart():
    """The venue debits a send gross. The docs' own arithmetic: 0.00133 left
    the account, 0.001 reached the recipient, 0.00033 paid the network."""
    adapter, _ = venue(accounts=[BTC_ACCOUNT], transactions={BTC_ACCOUNT["id"]: [AN_ONCHAIN_SEND]})

    (transfer,) = adapter.pull(CREDENTIALS).transfers

    assert transfer.external_id == "tx-57ffb4ae-0c59-5430-bcd3-3f98f797a66c"
    assert transfer.direction == "out"
    assert transfer.symbol == "BTC"
    assert transfer.quantity == Decimal("0.001")
    assert transfer.fee_quantity == Decimal("0.00033")
    # 13:13:35 at UTC-7, stated in UTC.
    assert transfer.occurred_at == datetime(2015, 3, 11, 20, 13, 35, tzinfo=UTC)


def test_a_send_states_its_network_hash_and_recipient():
    """The network Coinbase sent on, the hash and the recipient's address
    are kept as recorded fact (ADR-0032)."""
    send = {
        **AN_ONCHAIN_SEND,
        "network": {
            **AN_ONCHAIN_SEND["network"],
            "network_name": "solana",
            "hash": "5rTxHashOnSolana",
        },
    }
    adapter, _ = venue(accounts=[BTC_ACCOUNT], transactions={BTC_ACCOUNT["id"]: [send]})

    (transfer,) = adapter.pull(CREDENTIALS).transfers

    assert transfer.chain == "solana"
    assert transfer.tx_hash == "5rTxHashOnSolana"
    assert transfer.counterparty_address == "1AUJ8z5RuHRTqD1eikyfUUetzGmdWLGkpT"


def test_a_send_that_touched_no_chain_states_no_network_facts():
    adapter, _ = venue(accounts=[BTC_ACCOUNT], transactions={BTC_ACCOUNT["id"]: [AN_OFFCHAIN_SEND]})

    (transfer,) = adapter.pull(CREDENTIALS).transfers

    assert (transfer.chain, transfer.tx_hash, transfer.counterparty_address) == (None, None, None)


def test_a_receive_states_the_network_it_arrived_on():
    adapter, _ = venue(accounts=[BTC_ACCOUNT], transactions={BTC_ACCOUNT["id"]: [A_RECEIVE]})

    (transfer,) = adapter.pull(CREDENTIALS).transfers

    assert transfer.chain == "bitcoin"
    assert transfer.counterparty_address is None


def test_an_offchain_send_carries_no_fee():
    adapter, _ = venue(accounts=[BTC_ACCOUNT], transactions={BTC_ACCOUNT["id"]: [AN_OFFCHAIN_SEND]})

    (transfer,) = adapter.pull(CREDENTIALS).transfers

    assert transfer.direction == "out"
    assert transfer.quantity == Decimal("0.001")
    assert transfer.fee_quantity is None


def test_a_receive_is_a_transfer_in():
    adapter, _ = venue(accounts=[BTC_ACCOUNT], transactions={BTC_ACCOUNT["id"]: [A_RECEIVE]})

    (transfer,) = adapter.pull(CREDENTIALS).transfers

    assert transfer.external_id == "tx-9d6a7d1c-58d5-5a3b-b6a1-0d3b2c1f4e5a"
    assert transfer.direction == "in"
    assert (transfer.symbol, transfer.quantity) == ("BTC", Decimal("0.25"))
    assert transfer.fee_quantity is None


def test_a_credited_send_is_a_transfer_in():
    """Older history used `send` as a catch-all, so the amount's sign — the
    account's own credit or debit — decides the direction, not the type."""
    credited = {**AN_OFFCHAIN_SEND, "amount": {"amount": "0.5", "currency": "BTC"}}
    adapter, _ = venue(accounts=[BTC_ACCOUNT], transactions={BTC_ACCOUNT["id"]: [credited]})

    (transfer,) = adapter.pull(CREDENTIALS).transfers

    assert transfer.direction == "in"
    assert transfer.quantity == Decimal("0.5")


def test_a_network_fee_outside_the_sent_asset_is_refused():
    foreign_fee = {
        **AN_ONCHAIN_SEND,
        "network": {"transaction_fee": {"amount": "0.0004", "currency": "ETH"}},
    }
    adapter, _ = venue(accounts=[BTC_ACCOUNT], transactions={BTC_ACCOUNT["id"]: [foreign_fee]})

    with pytest.raises(AdapterError, match=r"'ETH'.*'BTC'"):
        adapter.pull(CREDENTIALS)


def test_fiat_movements_are_cash_movements():
    adapter, _ = venue(
        accounts=[BTC_ACCOUNT, EUR_ACCOUNT],
        transactions={EUR_ACCOUNT["id"]: [A_FIAT_WITHDRAWAL, A_FIAT_DEPOSIT]},
    )

    harvest = adapter.pull(CREDENTIALS)

    withdrawal, deposit = harvest.cash_movements
    assert deposit.external_id == "tx-1f2e3d4c-5b6a-5978-8a9b-0c1d2e3f4a5b"
    assert (deposit.direction, deposit.currency, deposit.amount) == (
        "in",
        "EUR",
        Decimal("1000.00"),
    )
    assert deposit.occurred_at == datetime(2024, 2, 1, 8, 0, tzinfo=UTC)
    # A withdrawal is stated as a debit; the port's amount is unsigned.
    assert (withdrawal.direction, withdrawal.currency, withdrawal.amount) == (
        "out",
        "EUR",
        Decimal("400.00"),
    )
    assert harvest.transfers == ()


@pytest.mark.parametrize("status", ["pending", "canceled", "failed", "expired"])
def test_a_movement_not_completed_stays_out(status):
    """A movement in flight arrives on a later sync once the venue calls it
    completed; one that never happened never arrives."""
    adapter, _ = venue(
        accounts=[BTC_ACCOUNT],
        transactions={BTC_ACCOUNT["id"]: [{**A_RECEIVE, "status": status}]},
    )

    assert adapter.pull(CREDENTIALS).transfers == ()


def test_fills_and_own_account_transfers_are_not_stated_twice():
    """The account API repeats each brokerage fill as one row per account and
    shows moves between the venue account's own wallets — neither is a record
    the ledger lacks."""
    repeated_fill = {**A_RECEIVE, "id": "fill-row", "type": "advanced_trade_fill"}
    own_transfer = {**A_RECEIVE, "id": "own-row", "type": "transfer"}
    adapter, _ = venue(
        fills=[A_FILL],
        accounts=[BTC_ACCOUNT],
        transactions={BTC_ACCOUNT["id"]: [repeated_fill, own_transfer]},
    )

    harvest = adapter.pull(CREDENTIALS)

    assert len(harvest.trades) == 1
    assert harvest.transfers == ()


def test_movements_the_venue_documents_no_shape_for_refuse_the_pull_by_name():
    """A conversion, a reward: the documentation states neither their
    counter-amount nor their fee, and skipping them would land a history with
    holes — so the pull refuses, naming every such type once."""
    a_conversion = {**A_RECEIVE, "id": "a-conversion", "type": "trade"}
    another_conversion = {**A_RECEIVE, "id": "another-conversion", "type": "trade"}
    a_reward = {**A_RECEIVE, "id": "a-reward", "type": "earn_payout"}
    adapter, _ = venue(
        accounts=[BTC_ACCOUNT],
        transactions={BTC_ACCOUNT["id"]: [a_conversion, another_conversion, a_reward, A_RECEIVE]},
    )

    with pytest.raises(AdapterError, match=r"'earn_payout', 'trade' transactions"):
        adapter.pull(CREDENTIALS)


# --- Simple buys and sells: one order, stated once per wallet it touched ---


def test_a_buy_paid_from_the_eur_wallet_is_one_trade():
    """Both rows name one order: the coin credited, the EUR wallet debited
    the total — the subtotal exchanged and the fee charged beside it."""
    adapter, _ = venue(
        accounts=[BTC_ACCOUNT, EUR_ACCOUNT],
        transactions={BTC_ACCOUNT["id"]: A_WALLET_BUY[:1], EUR_ACCOUNT["id"]: A_WALLET_BUY[1:]},
    )

    harvest = adapter.pull(CREDENTIALS)

    assert harvest.trades == (
        NormalizedTrade(
            external_id="buy-order-wallet-buy",
            occurred_at=datetime(2024, 3, 4, 9, 30, tzinfo=UTC),
            base_symbol="BTC",
            quote_symbol="EUR",
            side="buy",
            base_quantity=Decimal("0.00500000"),
            quote_quantity=Decimal("246.27"),
            fee_symbol="EUR",
            fee_quantity=Decimal("3.73"),
        ),
    )
    assert harvest.cash_movements == ()
    assert harvest.transfers == ()


def test_a_buy_paid_by_card_brings_its_euros_in_first():
    """The euros came from outside the venue account and were spent at once:
    a deposit of the total beside the trade, so the account's EUR balance
    stays what the venue states and the payment counts as money put in."""
    adapter, _ = venue(accounts=[BTC_ACCOUNT], transactions={BTC_ACCOUNT["id"]: [A_CARD_BUY]})

    harvest = adapter.pull(CREDENTIALS)

    (trade,) = harvest.trades
    assert (trade.external_id, trade.side, trade.base_quantity, trade.quote_quantity) == (
        "buy-order-card-buy",
        "buy",
        Decimal("0.00200000"),
        Decimal("118.21"),
    )
    assert (trade.fee_symbol, trade.fee_quantity) == ("EUR", Decimal("1.79"))
    assert harvest.cash_movements == (
        NormalizedCashMovement(
            external_id="buy-order-card-buy-paid",
            occurred_at=datetime(2024, 3, 4, 9, 30, tzinfo=UTC),
            direction="in",
            currency="EUR",
            amount=Decimal("120.00"),
        ),
    )


def test_a_sell_into_the_eur_wallet_is_one_trade():
    adapter, _ = venue(
        accounts=[BTC_ACCOUNT, EUR_ACCOUNT],
        transactions={
            BTC_ACCOUNT["id"]: A_WALLET_SELL[:1],
            EUR_ACCOUNT["id"]: A_WALLET_SELL[1:],
        },
    )

    harvest = adapter.pull(CREDENTIALS)

    (trade,) = harvest.trades
    assert (trade.external_id, trade.side, trade.base_symbol, trade.quote_symbol) == (
        "sell-order-wallet-sell",
        "sell",
        "BTC",
        "EUR",
    )
    assert (trade.base_quantity, trade.quote_quantity) == (
        Decimal("0.00800000"),
        Decimal("395.42"),
    )
    assert (trade.fee_symbol, trade.fee_quantity) == ("EUR", Decimal("5.91"))
    assert harvest.cash_movements == ()


def test_a_sell_paid_out_elsewhere_takes_its_euros_out_after():
    """The mirror of a card buy: the coin's wallet alone states the order, so
    its proceeds left the venue account — a withdrawal of the total."""
    adapter, _ = venue(accounts=[BTC_ACCOUNT], transactions={BTC_ACCOUNT["id"]: A_WALLET_SELL[:1]})

    harvest = adapter.pull(CREDENTIALS)

    assert [trade.external_id for trade in harvest.trades] == ["sell-order-wallet-sell"]
    assert harvest.cash_movements == (
        NormalizedCashMovement(
            external_id="sell-order-wallet-sell-paid",
            occurred_at=datetime(2024, 3, 4, 9, 30, tzinfo=UTC),
            direction="out",
            currency="EUR",
            amount=Decimal("389.51"),
        ),
    )


@pytest.mark.parametrize(
    ("amend", "named"),
    [
        ({"total": {"amount": "260.00", "currency": "EUR"}}, "do not add up"),
        ({"fee": {"amount": "3.73", "currency": "USD"}}, "more than one currency"),
    ],
    ids=["arithmetic", "currencies"],
)
def test_an_order_whose_amounts_cannot_be_read_as_one_trade_is_refused(amend, named):
    """Rather than book a trade the order does not prove: its total must be
    its subtotal and fee, all in the one currency it was paid in."""
    coin_row = {**A_CARD_BUY, "buy": {**A_CARD_BUY["buy"], **amend}}
    adapter, _ = venue(accounts=[BTC_ACCOUNT], transactions={BTC_ACCOUNT["id"]: [coin_row]})

    with pytest.raises(AdapterError, match=named):
        adapter.pull(CREDENTIALS)


def test_an_order_whose_coin_moved_against_its_side_is_refused():
    backwards = {**A_CARD_BUY, "amount": {"amount": "-0.00200000", "currency": "BTC"}}
    adapter, _ = venue(accounts=[BTC_ACCOUNT], transactions={BTC_ACCOUNT["id"]: [backwards]})

    with pytest.raises(AdapterError, match="wrong way round"):
        adapter.pull(CREDENTIALS)


def test_an_order_stated_by_its_euro_row_alone_is_refused():
    """Which coin was bought is stated only by the coin's own row."""
    adapter, _ = venue(accounts=[EUR_ACCOUNT], transactions={EUR_ACCOUNT["id"]: A_WALLET_BUY[1:]})

    with pytest.raises(AdapterError, match="order-wallet-buy"):
        adapter.pull(CREDENTIALS)


def test_an_undocumented_movement_still_in_flight_does_not_refuse():
    pending_buy = {**A_RECEIVE, "id": "a-buy", "type": "buy", "status": "pending"}
    adapter, _ = venue(accounts=[BTC_ACCOUNT], transactions={BTC_ACCOUNT["id"]: [pending_buy]})

    assert adapter.pull(CREDENTIALS) == Harvest()


# --- Pagination: the venue's own cursors, walked to the end ---


def numbered(row, count, key="id"):
    return [{**row, key: f"{row[key]}-{n}"} for n in range(count)]


def test_fills_continue_from_the_cursor_the_last_answer_stated(monkeypatch):
    monkeypatch.setattr(coinbase, "_PAGE_LIMIT", 2)
    fills = numbered(A_FILL, 5, key="entry_id")
    adapter, requests = venue(fills=fills)

    harvest = adapter.pull(CREDENTIALS)

    assert [trade.external_id for trade in harvest.trades] == [fill["entry_id"] for fill in fills]
    fills_requests = [r for r in requests if r.url.path.endswith("/fills")]
    assert [r.url.params.get("cursor") for r in fills_requests] == [None, "2", "4"]


def test_every_account_and_every_page_of_its_transactions_is_walked(monkeypatch):
    """Transactions are listed per account, so the walk is accounts first —
    themselves paged — then each account's own pages by `next_uri`."""
    monkeypatch.setattr(coinbase, "_PAGE_LIMIT", 2)
    accounts = numbered(BTC_ACCOUNT, 3)
    receives = numbered(A_RECEIVE, 5)
    adapter, requests = venue(
        accounts=accounts,
        transactions={accounts[0]["id"]: receives, accounts[2]["id"]: [A_FIAT_DEPOSIT]},
    )

    harvest = adapter.pull(CREDENTIALS)

    assert [transfer.external_id for transfer in harvest.transfers] == [
        f"tx-{receive['id']}" for receive in receives
    ]
    assert len(harvest.cash_movements) == 1
    account_pages = [r for r in requests if r.url.path == "/v2/accounts"]
    assert [r.url.params.get("starting_after") for r in account_pages] == [
        None,
        accounts[1]["id"],
    ]


def test_a_followed_page_is_signed_for_its_path_without_the_query(monkeypatch):
    monkeypatch.setattr(coinbase, "_PAGE_LIMIT", 2)
    adapter, requests = venue(accounts=numbered(BTC_ACCOUNT, 3))

    adapter.pull(CREDENTIALS)

    followed = next(r for r in requests if "starting_after" in r.url.params)
    claims = json.loads(_b64url_decode(followed.headers["Authorization"].split(".")[1]))
    assert claims["uri"] == "GET api.coinbase.com/v2/accounts"


def test_a_next_page_outside_the_account_api_is_never_followed():
    """The token opens the venue account — it goes to the venue's own host
    and nowhere a response might point it."""
    requests = []

    def answer(request):
        requests.append(request)
        if request.url.path.endswith("/fills"):
            return httpx.Response(200, json={"fills": [], "cursor": ""})
        return httpx.Response(
            200,
            json={"pagination": {"next_uri": "https://elsewhere.example/v2/accounts"}, "data": []},
        )

    adapter = CoinbaseSpotAdapter(
        client=httpx.Client(transport=httpx.MockTransport(answer)), throttle_seconds=0
    )

    with pytest.raises(AdapterError, match="outside the account API"):
        adapter.pull(CREDENTIALS)
    assert all(request.url.host == "api.coinbase.com" for request in requests)


def test_exhausting_the_page_budget_raises_rather_than_truncates(monkeypatch):
    monkeypatch.setattr(coinbase, "_PAGE_LIMIT", 2)
    monkeypatch.setattr(coinbase, "_MAX_PAGES", 2)
    fills_heavy, _ = venue(fills=numbered(A_FILL, 6, key="entry_id"))
    transactions_heavy, _ = venue(
        accounts=[BTC_ACCOUNT], transactions={BTC_ACCOUNT["id"]: numbered(A_RECEIVE, 6)}
    )

    for adapter in (fills_heavy, transactions_heavy):
        with pytest.raises(AdapterError, match="truncated"):
            adapter.pull(CREDENTIALS)


def test_a_history_that_exactly_fills_the_budget_is_not_called_truncated(monkeypatch):
    monkeypatch.setattr(coinbase, "_PAGE_LIMIT", 2)
    monkeypatch.setattr(coinbase, "_MAX_PAGES", 2)
    adapter, _ = venue(
        fills=numbered(A_FILL, 4, key="entry_id"),
        accounts=[BTC_ACCOUNT],
        transactions={BTC_ACCOUNT["id"]: numbered(A_RECEIVE, 4)},
    )

    harvest = adapter.pull(CREDENTIALS)

    assert len(harvest.trades) == 4
    assert len(harvest.transfers) == 4


def test_an_account_with_no_history_pulls_a_clean_empty_harvest():
    adapter, _ = venue(accounts=[BTC_ACCOUNT, EUR_ACCOUNT])

    harvest = adapter.pull(CREDENTIALS)

    assert harvest.trades == ()
    assert harvest.transfers == ()
    assert harvest.cash_movements == ()
    assert harvest.fills == ()
    assert harvest.funding == ()


# --- The registry entry ---


def test_coinbase_ships_as_one_adapter_plus_a_registry_entry():
    """Adding the venue changed no service, router or screen: the registry
    answers its one kind, which declares that the venue's history has no
    lookback cap."""
    (adapter,) = get_venue_adapters()["coinbase"]

    assert isinstance(adapter, CoinbaseSpotAdapter)
    assert adapter.kind == "spot"
    assert adapter.lookback_days is None


def test_the_recorded_payloads_are_json_clean():
    """The fixtures stand in for wire payloads — they must survive a JSON
    round trip unchanged, as real recordings would."""
    for payload in (
        VIEW_ONLY,
        A_FILL,
        BTC_ACCOUNT,
        EUR_ACCOUNT,
        AN_ONCHAIN_SEND,
        AN_OFFCHAIN_SEND,
        A_RECEIVE,
        A_FIAT_DEPOSIT,
        A_FIAT_WITHDRAWAL,
    ):
        assert json.loads(json.dumps(payload)) == payload


# --- Rows the documentation does not promise ---


def test_a_fiat_movement_stated_the_other_way_round_is_refused():
    """A deposit that debits is a reversal — not the movement its type
    names, and never booked as one."""
    reversed_deposit = {**A_FIAT_DEPOSIT, "amount": {"amount": "-1000.00", "currency": "EUR"}}
    adapter, _ = venue(accounts=[EUR_ACCOUNT], transactions={EUR_ACCOUNT["id"]: [reversed_deposit]})

    with pytest.raises(AdapterError, match=r"1f2e3d4c.*'fiat_deposit'.*reversal"):
        adapter.pull(CREDENTIALS)


def test_a_row_that_moved_nothing_states_nothing():
    nothing_sent = {**AN_OFFCHAIN_SEND, "amount": {"amount": "0.00000000", "currency": "BTC"}}
    adapter, _ = venue(accounts=[BTC_ACCOUNT], transactions={BTC_ACCOUNT["id"]: [nothing_sent]})

    assert adapter.pull(CREDENTIALS) == Harvest()


@pytest.mark.parametrize(
    "malformed",
    [
        {**A_FILL, "product_id": "BTCUSD"},
        {**A_FILL, "size_in_quote": True, "price": "0"},
        {key: value for key, value in A_FILL.items() if key != "size"},
    ],
)
def test_a_row_the_adapter_cannot_read_is_an_adapter_error(malformed):
    """The port promises AdapterError and nothing else — a malformed row
    never escapes as a bare KeyError or arithmetic fault."""
    adapter, _ = venue(fills=[malformed])

    with pytest.raises(AdapterError, match="could not read"):
        adapter.pull(CREDENTIALS)


def test_a_timestamp_without_an_offset_is_read_as_utc():
    unzoned = {**A_RECEIVE, "created_at": "2024-02-03T10:15:00"}
    adapter, _ = venue(accounts=[BTC_ACCOUNT], transactions={BTC_ACCOUNT["id"]: [unzoned]})

    (transfer,) = adapter.pull(CREDENTIALS).transfers

    assert transfer.occurred_at == datetime(2024, 2, 3, 10, 15, tzinfo=UTC)

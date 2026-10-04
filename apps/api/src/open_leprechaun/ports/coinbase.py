"""The Coinbase adapter (ticket 37): the venue's two REST APIs translated
into the port's normalized records — spot trades from the brokerage API's
fills, crypto transfers and fiat cash movements from the account API's
per-account transactions.

Auth, as the venue documents it: a JWT per request, signed ES256 with the
key's own EC private key — the key name as `kid` and `sub`, issuer "cdp", two
minutes of life, a random `nonce`, and a `uri` claim of
"METHOD host/path" (the query string left out) binding the token to the one
request it opens. Sent as `Authorization: Bearer`. The credential's key is
the key name ("organizations/…/apiKeys/…") and its secret the PEM private
key; the venue's Ed25519 keys are not accepted by these APIs.

Quirks absorbed here: two error dialects (the brokerage API answers
{"error", "message"} or a bare 401, the account API {"errors": [...]});
two pagination dialects (an opaque `cursor`, and a `next_uri` to follow);
transactions listed per wallet rather than for the venue account as a whole; a send's
`amount` stated gross of its network fee; and a history with no lookback cap.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import httpx
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.serialization import load_der_private_key

from open_leprechaun.ports.exchange import (
    AdapterError,
    Credentials,
    Harvest,
    NormalizedCashMovement,
    NormalizedTrade,
    NormalizedTransfer,
)

_HOST = "api.coinbase.com"
BASE_URL = f"https://{_HOST}"

_PERMISSIONS_PATH = "/api/v3/brokerage/key_permissions"
_FILLS_PATH = "/api/v3/brokerage/orders/historical/fills"
_ACCOUNTS_PATH = "/v2/accounts"

# The venue serves an account's whole history — there is no cap to declare
# (ADR-0008: None is "unbounded", and the UI says so).
LOOKBACK_DAYS = None
_PAGE_LIMIT = 100
# Page budget per walk; exhausting it means truncation, which is an error to
# raise, never a silent shortfall. Generous, because every sync walks the
# whole unbounded history: a hundred thousand rows per walk.
_MAX_PAGES = 1000
_TOKEN_SECONDS = 120

_COMPLETED = "completed"
# Transaction types that state nothing the ledger lacks: a fill arrives whole
# from the brokerage API (here it is one row per account, each half a trade);
# a transfer between the venue account's own wallets nets to nothing within
# the one Account they all land in; a request moved no funds.
_NOTHING_TO_LAND = frozenset({"advanced_trade_fill", "transfer", "request"})
_TRANSFER_TYPES = frozenset({"send", "receive"})
_CASH_DIRECTIONS: dict[str, Literal["in", "out"]] = {
    "fiat_deposit": "in",
    "fiat_withdrawal": "out",
}

_PEM = re.compile(r"-----BEGIN ([A-Z ]*PRIVATE KEY)-----(.+?)-----END \1-----", re.DOTALL)


def _signing_key(secret: str) -> ec.EllipticCurvePrivateKey:
    """The credential's private key, read however its PEM was pasted — with
    real line breaks, with the key file's escaped ones, or with none at all
    after a single-line input swallowed them. No sentence raised here ever
    carries a byte of the secret."""
    armoured = _PEM.search(secret.replace("\\n", "\n"))
    try:
        if armoured is None:
            raise ValueError("no PEM armour")
        der = base64.b64decode("".join(armoured.group(2).split()), validate=True)
        key = load_der_private_key(der, password=None)
    except ValueError, TypeError, binascii.Error, UnsupportedAlgorithm:
        # Deliberately no `from`: the cause may quote what it failed to parse.
        raise AdapterError(
            "The secret is not a private key in PEM form — paste the whole"
            " privateKey value from the key file Coinbase issued."
        ) from None
    if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != "secp256r1":
        raise AdapterError(
            "Coinbase accepts ECDSA keys only on these APIs — create the key"
            " with the ECDSA signature algorithm, and store that instead."
        )
    return key


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _token(key_name: str, key: ec.EllipticCurvePrivateKey, method: str, path: str) -> str:
    """The venue's documented JWT for one request: ES256 over
    header.payload, the signature as the raw r‖s pair JWS prescribes."""
    now = int(time.time())
    header = {"alg": "ES256", "kid": key_name, "nonce": secrets.token_hex(), "typ": "JWT"}
    claims = {
        "sub": key_name,
        "iss": "cdp",
        "nbf": now,
        "exp": now + _TOKEN_SECONDS,
        "uri": f"{method.upper()} {_HOST}{path}",
    }
    signing_input = ".".join(
        _b64url(json.dumps(part, separators=(",", ":")).encode()) for part in (header, claims)
    )
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    return f"{signing_input}.{_b64url(r.to_bytes(32) + s.to_bytes(32))}"


def _at(stated: str) -> datetime:
    at = datetime.fromisoformat(stated)
    # The venue states an offset; were one ever missing, UTC is what it means
    # — never the server's own timezone.
    return at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)


def _truncated(path: str) -> AdapterError:
    return AdapterError(
        f"The walk over {path} may be truncated — the {_MAX_PAGES}-page"
        " budget ran out before the history did."
    )


def _error_message(response: httpx.Response) -> str:
    """The venue's own sentence in either dialect, or the bare body where it
    answered no JSON at all (a refused token is a plain-text 401)."""
    try:
        data = response.json()
    except ValueError:
        return response.text.strip()[:200]
    if isinstance(data, dict):
        errors = data.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            return str(errors[0].get("message") or errors[0].get("id") or "")
        return str(data.get("message") or data.get("error") or "")
    return ""


class CoinbaseSpotAdapter:
    """The spot kind of a Coinbase Connection: spot trades, crypto transfers
    and fiat cash movements out — everything ledger-bound the venue account
    shows in a documented shape. What the venue states without one (a simple
    buy or sell, a conversion, a reward) refuses the pull by name rather than
    land a history with holes in it."""

    kind = "spot"
    lookback_days = LOOKBACK_DAYS

    def __init__(self, client: httpx.Client | None = None, throttle_seconds: float = 0.15) -> None:
        self._client = client or httpx.Client(timeout=15.0)
        # A small pause between paged requests respects the venue's rate
        # limits; tests pass zero.
        self._throttle_seconds = throttle_seconds

    def test(self, credentials: Credentials) -> str:
        granted = self._signed_get(credentials, _PERMISSIONS_PATH)
        # The venue states the key's own permission set. Read-only
        # credentials only (ADR-0003): a key that can do more than view fails
        # its test — and so does one whose answer leaves a permission
        # unstated, because only an explicit "no" proves it.
        beyond = [
            name
            for flag, name in (("can_trade", "Trade"), ("can_transfer", "Transfer"))
            if granted.get(flag) is not False
        ]
        if beyond:
            raise AdapterError(
                f"The key is not shown to be without {' and '.join(beyond)} — create one with the"
                " View permission only, and store that instead."
            )
        if not granted.get("can_view"):
            raise AdapterError(
                "The key does not grant View — create one with the View permission only."
            )
        return "Authenticated — the key is view-only."

    def pull(self, credentials: Credentials) -> Harvest:
        try:
            return self._harvest(credentials)
        except (KeyError, ValueError, TypeError, ArithmeticError) as failed:
            raise AdapterError(
                "Coinbase answered a row the adapter could not read — a field"
                f" it documents was missing or malformed ({type(failed).__name__})."
            ) from failed

    def _harvest(self, credentials: Credentials) -> Harvest:
        trades = tuple(self._trade(raw) for raw in self._fills(credentials))
        transfers: list[NormalizedTransfer] = []
        cash_movements: list[NormalizedCashMovement] = []
        unshaped: set[str] = set()
        for wallet in tuple(self._paged_by_uri(credentials, _ACCOUNTS_PATH)):
            for raw in self._paged_by_uri(
                credentials, f"{_ACCOUNTS_PATH}/{wallet['id']}/transactions"
            ):
                # Anything not completed is a movement still in flight or one
                # that never happened, arriving on a later sync once settled;
                # a row that moved nothing states nothing.
                if raw.get("status") != _COMPLETED or not Decimal(str(raw["amount"]["amount"])):
                    continue
                stated_type = str(raw.get("type"))
                if stated_type in _TRANSFER_TYPES:
                    transfers.append(self._transfer(raw))
                elif stated_type in _CASH_DIRECTIONS:
                    cash_movements.append(self._cash_movement(raw, _CASH_DIRECTIONS[stated_type]))
                elif stated_type not in _NOTHING_TO_LAND:
                    unshaped.add(stated_type)
        if unshaped:
            named = ", ".join(repr(stated_type) for stated_type in sorted(unshaped))
            raise AdapterError(
                f"The account holds {named} transactions, which the venue"
                " documents no shape for — the kind refuses rather than import"
                " a history with those movements missing. Import them from the"
                " venue's own export instead."
            )
        return Harvest(
            trades=trades, transfers=tuple(transfers), cash_movements=tuple(cash_movements)
        )

    def _signed_get(
        self, credentials: Credentials, path_url: str, params: dict[str, str] | None = None
    ) -> dict:
        if not credentials.secret:
            raise AdapterError("Coinbase signs with a secret, and this credential has none.")
        key = _signing_key(credentials.secret)
        # The token binds the path alone — the query string stays out of it.
        token = _token(credentials.key, key, "GET", path_url.partition("?")[0])
        try:
            response = self._client.get(
                f"{BASE_URL}{path_url}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as failed:
            raise AdapterError(f"The Coinbase request failed: {failed}") from failed
        if response.status_code != 200:
            raise AdapterError(
                f"Coinbase API error [HTTP {response.status_code}]: {_error_message(response)}"
            )
        try:
            data = response.json()
        except ValueError as failed:
            raise AdapterError(
                f"Coinbase answered something that is not JSON (HTTP {response.status_code})."
            ) from failed
        if not isinstance(data, dict):
            raise AdapterError("Coinbase answered JSON that is not an object.")
        return data

    def _fills(self, credentials: Credentials) -> Iterator[dict]:
        """Walk the brokerage API's fills by its opaque cursor: each answer
        names where the next one starts, and an empty cursor ends the walk."""
        cursor: str | None = None
        for _ in range(_MAX_PAGES):
            # Spot only: the venue's futures fills are another kind's records.
            params = {"product_types": "SPOT", "limit": str(_PAGE_LIMIT)}
            if cursor:
                params["cursor"] = cursor
            page = self._signed_get(credentials, _FILLS_PATH, params)
            fills = page.get("fills") or []
            yield from fills
            cursor = page.get("cursor")
            if not cursor or not fills:
                return
            self._pause()
        raise _truncated(_FILLS_PATH)

    def _paged_by_uri(self, credentials: Credentials, path: str) -> Iterator[dict]:
        """Walk one account-API list by following the `next_uri` its
        pagination object names, until it names none."""
        page = self._signed_get(credentials, path, {"limit": str(_PAGE_LIMIT)})
        for pages_read in range(1, _MAX_PAGES + 1):
            yield from page.get("data") or []
            next_uri = (page.get("pagination") or {}).get("next_uri")
            if not next_uri:
                return
            if pages_read == _MAX_PAGES:
                break
            # The venue states a path; anything else is never followed, so a
            # token is only ever sent to the venue's own host.
            if not str(next_uri).startswith("/v2/"):
                raise AdapterError(
                    f"The walk over {path} was pointed outside the account API — refused."
                )
            self._pause()
            page = self._signed_get(credentials, str(next_uri))
        raise _truncated(path)

    def _pause(self) -> None:
        if self._throttle_seconds:
            time.sleep(self._throttle_seconds)

    def _trade(self, raw: dict) -> NormalizedTrade:
        # Only a plain fill is a trade as stated; a reversal or correction
        # amends another row, and guessing how would book a trade twice.
        if raw.get("trade_type") != "FILL":
            raise AdapterError(
                f"Fill {raw['entry_id']} is a {raw.get('trade_type')!r}, not a"
                " plain fill — the kind refuses rather than guess what it amends."
            )
        base, quote = str(raw["product_id"]).split("-")[:2]
        price = Decimal(str(raw["price"]))
        size = Decimal(str(raw["size"]))
        # `size` is in the currency the order was placed in: the base, or —
        # for an order sized in quote — the quote, the base following from
        # the price.
        if raw.get("size_in_quote"):
            base_quantity, quote_quantity = size / price, size
        else:
            base_quantity, quote_quantity = size, size * price
        commission = Decimal(str(raw.get("commission") or "0"))
        return NormalizedTrade(
            external_id=str(raw["entry_id"]),
            occurred_at=_at(str(raw["trade_time"])),
            base_symbol=base,
            quote_symbol=quote,
            side="buy" if str(raw["side"]).upper() == "BUY" else "sell",
            base_quantity=base_quantity,
            quote_quantity=quote_quantity,
            # The venue charges its commission in the quote currency.
            fee_symbol=quote if commission else None,
            fee_quantity=commission or None,
        )

    def _transfer(self, raw: dict) -> NormalizedTransfer:
        symbol = str(raw["amount"]["currency"])
        amount = Decimal(str(raw["amount"]["amount"]))
        # The amount is the account's own credit or debit, so its sign — not
        # the type, which older history used as a catch-all — says which way
        # the asset moved.
        if amount > 0:
            return NormalizedTransfer(
                external_id=f"tx-{raw['id']}",
                occurred_at=_at(str(raw["created_at"])),
                direction="in",
                symbol=symbol,
                quantity=amount,
            )
        fee = self._network_fee(raw, symbol)
        # A send is debited gross: what reached the recipient plus what the
        # network took. The port states the two apart.
        quantity = -amount - fee
        if quantity <= 0:
            raise AdapterError(
                f"Transaction {raw['id']} states a network fee no smaller than"
                " the amount it moved — refused rather than booked as a"
                " transfer of nothing."
            )
        return NormalizedTransfer(
            external_id=f"tx-{raw['id']}",
            occurred_at=_at(str(raw["created_at"])),
            direction="out",
            symbol=symbol,
            quantity=quantity,
            fee_quantity=fee or None,
        )

    @staticmethod
    def _network_fee(raw: dict, symbol: str) -> Decimal:
        stated = (raw.get("network") or {}).get("transaction_fee")
        if not stated:
            return Decimal(0)
        fee = Decimal(str(stated["amount"]))
        if fee and stated["currency"] != symbol:
            raise AdapterError(
                f"Transaction {raw['id']}'s network fee arrived in"
                f" {stated['currency']!r} rather than the sent asset {symbol!r}"
                " — the port states a transfer's fee in its own asset only."
            )
        return fee

    @staticmethod
    def _cash_movement(raw: dict, direction: Literal["in", "out"]) -> NormalizedCashMovement:
        amount = Decimal(str(raw["amount"]["amount"]))
        # A deposit credits and a withdrawal debits; one stated the other way
        # round is a reversal, which is not the movement its type names.
        if (amount > 0) != (direction == "in"):
            raise AdapterError(
                f"Transaction {raw['id']} is a {raw['type']!r} moving the other"
                " way — a reversal the kind refuses rather than book as the"
                " movement it undoes."
            )
        return NormalizedCashMovement(
            external_id=f"tx-{raw['id']}",
            occurred_at=_at(str(raw["created_at"])),
            direction=direction,
            currency=str(raw["amount"]["currency"]),
            # Stated as the fiat account's credit or debit — what the balance
            # actually moved by, a withdrawal's sign dropped for the port.
            amount=abs(amount),
        )

"""OKX adapters (ticket 36): the venue's v5 REST API translated into the
port's normalized records — the spot kind emits trades, transfers and cash
movements; the futures kind emits fills and funding.

Auth, as the venue documents it: Base64 of an HMAC-SHA256 over
timestamp + METHOD + request path (query string included) + body, where the
timestamp is ISO-8601 UTC with milliseconds ("2020-12-08T09:08:57.715Z").
Sent via the OK-ACCESS-KEY, OK-ACCESS-SIGN, OK-ACCESS-TIMESTAMP and
OK-ACCESS-PASSPHRASE headers — OKX is the first venue here whose key carries
a passphrase.

Quirks absorbed here: logical errors arrive as {"code": != "0", "msg"} with
HTTP 200 or an auth status alike; history endpoints page backwards by an
opaque id cursor via the `after` parameter.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import httpx

from open_leprechaun.ports.exchange import (
    AdapterError,
    Credentials,
    Harvest,
    NormalizedCashMovement,
    NormalizedFill,
    NormalizedFunding,
    NormalizedTrade,
    NormalizedTransfer,
)

BASE_URL = "https://www.okx.com"

_CONFIG_PATH = "/api/v5/account/config"
_FILLS_PATH = "/api/v5/trade/fills-history"
_BILLS_PATH = "/api/v5/account/bills-archive"
_DEPOSITS_PATH = "/api/v5/asset/deposit-history"
_WITHDRAWALS_PATH = "/api/v5/asset/withdrawal-history"
_FIAT_DEPOSITS_PATH = "/api/v5/fiat/deposit-order-history"
_FIAT_WITHDRAWALS_PATH = "/api/v5/fiat/withdrawal-order-history"
_INSTRUMENTS_PATH = "/api/v5/public/instruments"

# The venue serves three months of trade and bill history; the adapter asks
# for exactly that and nothing pretends to reach further (ticket 40 will say
# so in the UI).
LOOKBACK_DAYS = 90
_DAY_MS = 24 * 3600 * 1000
_PAGE_LIMIT = 100
# Page budget per walk; exhausting it means truncation, which is an error to
# raise, never a silent shortfall.
_MAX_PAGES = 200
# The bill type naming a funding-fee payment; subtypes 173 (expense) and 174
# (income) both arrive under it, their sign carried by `pnl`.
_FUNDING_BILL_TYPE = "8"
# The contract universe the futures kind serves: perpetual swaps and dated
# futures — options are no Termingeschäft this ledger models yet.
_DERIVATIVE_TYPES = ("SWAP", "FUTURES")
# The success states — anything else is a movement still in flight or one
# that never happened, arriving on a later sync once settled.
_TRANSFER_SETTLED = "2"
_FIAT_COMPLETED = "completed"


def _sign(secret: str, timestamp: str, method: str, path_url: str, body: str = "") -> str:
    """The Base64 HMAC-SHA256 signature over the venue's documented prehash:
    timestamp + METHOD + path (query included) + body."""
    message = f"{timestamp}{method.upper()}{path_url}{body}"
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _at(milliseconds: int) -> datetime:
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


def _with_query(path: str, params: dict[str, str] | None) -> str:
    query = "&".join(f"{key}={value}" for key, value in (params or {}).items())
    return f"{path}?{query}" if query else path


def _truncated(path: str) -> AdapterError:
    return AdapterError(
        f"The walk over {path} may be truncated — the {_MAX_PAGES}-page"
        " budget ran out before the history did."
    )


class _OkxAdapter:
    """What both OKX kinds share: signing, transport, error translation and
    the credential test — one venue account behind one credential set."""

    lookback_days = LOOKBACK_DAYS

    def __init__(self, client: httpx.Client | None = None, throttle_seconds: float = 0.15) -> None:
        self._client = client or httpx.Client(timeout=15.0)
        # A small pause between paged requests respects the venue's rate
        # limits; tests pass zero.
        self._throttle_seconds = throttle_seconds

    def test(self, credentials: Credentials) -> str:
        rows = self._signed_get(credentials, _CONFIG_PATH)
        config = rows[0] if rows else {}
        # The venue states the key's own permission set — "read_only",
        # "trade", "withdraw", comma-joined. Read-only credentials only
        # (ADR-0003): a key that can do more than read fails its test.
        granted = set(str(config.get("perm") or "").split(","))
        beyond = sorted(granted - {"read_only", ""})
        if beyond:
            raise AdapterError(
                f"The key also grants {', '.join(beyond)} — mint one with the Read"
                " permission only, and store that instead."
            )
        return "Authenticated — the key is read-only."

    def _signed_get(
        self, credentials: Credentials, path: str, params: dict[str, str] | None = None
    ) -> list[dict]:
        if not credentials.secret:
            raise AdapterError("OKX signs with a secret, and this credential has none.")
        if not credentials.passphrase:
            raise AdapterError(
                "OKX sends the key's passphrase with every request, and this credential has none."
            )
        path_url = _with_query(path, params)
        timestamp = _now_iso()
        headers = {
            "OK-ACCESS-KEY": credentials.key,
            "OK-ACCESS-SIGN": _sign(credentials.secret, timestamp, "GET", path_url),
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": credentials.passphrase,
        }
        return self._get(path_url, headers)

    def _public_get(self, path: str, params: dict[str, str] | None = None) -> list[dict]:
        return self._get(_with_query(path, params), headers={})

    def _get(self, path_url: str, headers: dict[str, str]) -> list[dict]:
        try:
            response = self._client.get(f"{BASE_URL}{path_url}", headers=headers)
        except httpx.HTTPError as failed:
            raise AdapterError(f"The OKX request failed: {failed}") from failed
        try:
            data = response.json()
        except ValueError as failed:
            raise AdapterError(
                f"OKX answered something that is not JSON (HTTP {response.status_code})."
            ) from failed
        # OKX signals logical errors as {"code": != "0", "msg"} — with HTTP
        # 200 for most, and an auth status like 401 for a refused credential.
        code = data.get("code")
        if response.status_code != 200 or code != "0":
            message = data.get("msg") or response.text[:200]
            raise AdapterError(f"OKX API error [{code or response.status_code}]: {message}")
        return data.get("data") or []

    def _paged_by_id(
        self, credentials: Credentials, path: str, params: dict[str, str]
    ) -> Iterator[dict]:
        """Walk one endpoint backwards by the venue's own bill-id cursor:
        `after` answers strictly earlier bills, so each page continues from
        the oldest id of the last — no instant is ever stepped past, because
        the cursor is unique per row."""
        after: str | None = None
        for _ in range(_MAX_PAGES):
            page = {**params, "limit": str(_PAGE_LIMIT)}
            if after is not None:
                page["after"] = after
            rows = self._signed_get(credentials, path, page)
            yield from rows
            if len(rows) < _PAGE_LIMIT:
                return
            after = str(rows[-1]["billId"])
            self._pause()
        raise _truncated(path)

    def _paged_by_instant(
        self,
        credentials: Credentials,
        path: str,
        params: dict[str, str],
        *,
        cursor_param: str,
        inclusive: bool,
        instant_of: Callable[[dict], int],
        key: Callable[[dict], object],
    ) -> Iterator[dict]:
        """Walk one endpoint backwards by a timestamp cursor. A full page can
        cut through the middle of one millisecond, so the cursor lands *on*
        the oldest instant answered — directly where the venue's cursor is
        inclusive, one past it where it excludes the instant itself — and
        `key` deduplicates the boundary rows that come back; only once a full
        page holds nothing new does the cursor step beyond the instant."""
        seen: set[object] = set()
        cursor: int | None = None
        for _ in range(_MAX_PAGES):
            page = {**params, "limit": str(_PAGE_LIMIT)}
            if cursor is not None:
                page[cursor_param] = str(cursor)
            rows = self._signed_get(credentials, path, page)
            fresh = [row for row in rows if key(row) not in seen]
            for row in fresh:
                seen.add(key(row))
                yield row
            if len(rows) < _PAGE_LIMIT:
                return
            oldest = min(instant_of(row) for row in rows)
            land_on = oldest if inclusive else oldest + 1
            step_past = oldest - 1 if inclusive else oldest
            cursor = land_on if fresh else step_past
            self._pause()
        raise _truncated(path)

    def _pause(self) -> None:
        if self._throttle_seconds:
            time.sleep(self._throttle_seconds)


class OkxSpotAdapter(_OkxAdapter):
    """The spot kind of an OKX Connection: spot trades, crypto transfers and
    fiat cash movements out — everything ledger-bound the venue account
    shows. Margin trading is out of scope: only SPOT fills are pulled."""

    kind = "spot"

    def pull(self, credentials: Credentials) -> Harvest:
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - LOOKBACK_DAYS * _DAY_MS
        trades = tuple(
            self._trade(raw)
            for raw in self._paged_by_id(
                credentials,
                _FILLS_PATH,
                {"instType": "SPOT", "begin": str(start_ms), "end": str(end_ms)},
            )
        )
        transfers = tuple(self._transfers(credentials, start_ms))
        cash_movements = tuple(self._cash_movements(credentials, start_ms))
        return Harvest(trades=trades, transfers=transfers, cash_movements=cash_movements)

    def _transfers(self, credentials: Credentials, start_ms: int) -> Iterator[NormalizedTransfer]:
        for path, normalize in (
            (_DEPOSITS_PATH, self._deposit),
            (_WITHDRAWALS_PATH, self._withdrawal),
        ):
            for raw in self._paged_by_instant(
                credentials,
                path,
                # `before` bounds the range at the lookback start (it answers
                # strictly newer records); `after` is the walking cursor.
                {"before": str(start_ms - 1)},
                cursor_param="after",
                inclusive=False,
                instant_of=lambda row: int(row["ts"]),
                key=lambda row: row.get("depId") or row.get("wdId"),
            ):
                if raw.get("state") == _TRANSFER_SETTLED:
                    yield normalize(raw)

    def _cash_movements(
        self, credentials: Credentials, start_ms: int
    ) -> Iterator[NormalizedCashMovement]:
        endpoints: tuple[tuple[str, Literal["in", "out"], str], ...] = (
            (_FIAT_DEPOSITS_PATH, "in", "fiat-dep"),
            (_FIAT_WITHDRAWALS_PATH, "out", "fiat-wd"),
        )
        for path, direction, prefix in endpoints:
            for raw in self._paged_by_instant(
                credentials,
                path,
                # `after` is this endpoint's inclusive begin filter; `before`,
                # its inclusive end, is the walking cursor.
                {"after": str(start_ms)},
                cursor_param="before",
                inclusive=True,
                instant_of=lambda row: int(row["cTime"]),
                key=lambda row: row["ordId"],
            ):
                if raw.get("state") == _FIAT_COMPLETED:
                    yield self._cash_movement(raw, direction, prefix)

    def _trade(self, raw: dict) -> NormalizedTrade:
        base, quote = str(raw["instId"]).split("-")[:2]
        fee = Decimal(str(raw.get("fee") or "0"))
        # The venue documents a positive fee as a rebate — income the trade
        # shape cannot state as a fee, refused rather than booked wrong.
        if fee > 0:
            raise AdapterError(
                f"Fill {raw['billId']} carries a rebate rather than a fee —"
                " the ledger has no shape for it, so the kind refuses instead"
                " of mislabelling income."
            )
        size = Decimal(str(raw["fillSz"]))
        return NormalizedTrade(
            external_id=str(raw["billId"]),
            occurred_at=_at(int(raw["ts"])),
            base_symbol=base,
            quote_symbol=quote,
            side="buy" if str(raw["side"]).lower() == "buy" else "sell",
            base_quantity=size,
            quote_quantity=size * Decimal(str(raw["fillPx"])),
            fee_symbol=str(raw["feeCcy"]) if fee else None,
            fee_quantity=-fee if fee else None,
        )

    def _deposit(self, raw: dict) -> NormalizedTransfer:
        return NormalizedTransfer(
            external_id=f"dep-{raw['depId']}",
            occurred_at=_at(int(raw["ts"])),
            direction="in",
            symbol=str(raw["ccy"]),
            quantity=Decimal(str(raw["amt"])),
        )

    def _withdrawal(self, raw: dict) -> NormalizedTransfer:
        fee = Decimal(str(raw.get("fee") or "0"))
        fee_ccy = raw.get("feeCcy")
        if fee and fee_ccy and fee_ccy != raw["ccy"]:
            raise AdapterError(
                f"Withdrawal {raw['wdId']}'s fee arrived in {fee_ccy!r} rather"
                f" than the withdrawn asset {raw['ccy']!r} — the port states a"
                " transfer's fee in its own asset only."
            )
        return NormalizedTransfer(
            external_id=f"wd-{raw['wdId']}",
            occurred_at=_at(int(raw["ts"])),
            direction="out",
            symbol=str(raw["ccy"]),
            quantity=Decimal(str(raw["amt"])),
            fee_quantity=fee or None,
        )

    def _cash_movement(
        self, raw: dict, direction: Literal["in", "out"], prefix: str
    ) -> NormalizedCashMovement:
        if Decimal(str(raw.get("fee") or "0")):
            raise AdapterError(
                f"Fiat order {raw['ordId']} carries a fee — whether the venue"
                " states the amount beside or net of it is undocumented, so"
                " the kind refuses instead of guessing."
            )
        return NormalizedCashMovement(
            external_id=f"{prefix}-{raw['ordId']}",
            occurred_at=_at(int(raw["cTime"])),
            direction=direction,
            currency=str(raw["ccy"]),
            amount=Decimal(str(raw["amt"])),
        )


class OkxFuturesAdapter(_OkxAdapter):
    """The futures kind of an OKX Connection: perpetual and dated contract
    fills and their funding payments out. The venue states fills in
    contracts, so each is sized by the public instrument description — face
    value in the base currency for a linear contract, in USD for an inverse
    one, whose flag is stated truthfully either way; OKX names each fill's
    own realised result, which is what lets an inverse stream derive at all
    (ticket 28)."""

    kind = "futures"

    def pull(self, credentials: Credentials) -> Harvest:
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - LOOKBACK_DAYS * _DAY_MS
        specs = self._instrument_descriptions()
        fills = tuple(
            self._fill(raw, specs)
            for inst_type in _DERIVATIVE_TYPES
            for raw in self._paged_by_id(
                credentials,
                _FILLS_PATH,
                {"instType": inst_type, "begin": str(start_ms), "end": str(end_ms)},
            )
        )
        funding = tuple(
            self._funding(raw)
            for raw in self._paged_by_id(
                credentials,
                _BILLS_PATH,
                {"type": _FUNDING_BILL_TYPE, "begin": str(start_ms), "end": str(end_ms)},
            )
        )
        return Harvest(fills=fills, funding=funding)

    def _instrument_descriptions(self) -> dict[str, dict]:
        """Every live contract's description from the public endpoint —
        unauthenticated, so no credential is spent on public facts."""
        descriptions: dict[str, dict] = {}
        for inst_type in _DERIVATIVE_TYPES:
            for row in self._public_get(_INSTRUMENTS_PATH, {"instType": inst_type}):
                descriptions[str(row["instId"])] = row
            self._pause()
        return descriptions

    def _fill(self, raw: dict, descriptions: dict[str, dict]) -> NormalizedFill:
        symbol = str(raw["instId"])
        description = descriptions.get(symbol)
        if description is None:
            raise AdapterError(
                f"The venue no longer describes {symbol!r}, so its contract"
                " value is unknown and the fill cannot be sized."
            )
        settlement = str(description["settleCcy"])
        fee_ccy = raw.get("feeCcy")
        if fee_ccy and fee_ccy != settlement:
            raise AdapterError(
                f"A {symbol} fill's fee arrived in {fee_ccy!r} rather than the"
                f" settlement asset {settlement!r} — the port states fees in"
                " the settlement asset only."
            )
        contracts = Decimal(str(raw["fillSz"]))
        face = Decimal(str(description["ctVal"])) * Decimal(str(description.get("ctMult") or "1"))
        position_side = str(raw.get("posSide") or "")
        return NormalizedFill(
            external_id=str(raw["billId"]),
            occurred_at=_at(int(raw["ts"])),
            symbol=symbol,
            side="buy" if str(raw["side"]).lower() == "buy" else "sell",
            price=Decimal(str(raw["fillPx"])),
            # Linear face value is in the base currency, inverse in USD — the
            # size is stated in that unit either way.
            size=contracts * face,
            # The venue states a charge as a negative amount and a maker
            # rebate as positive; negating keeps the port's positive-is-a-cost
            # convention, and a rebate arrives as a negative cost the net
            # accounting sums correctly into the position (ticket 28).
            fee=-Decimal(str(raw.get("fee") or "0")),
            settlement_symbol=settlement,
            position_side=position_side if position_side in ("long", "short") else None,
            # The venue's own realised result: meaningful on a close, zero on
            # an open — where derivation never reads it (ticket 28).
            realized=Decimal(str(raw.get("fillPnl") or "0")),
            # A description stating neither variant leaves `inverse` unstated
            # — derivation refuses the stream rather than assume linear.
            inverse={"linear": False, "inverse": True}.get(str(description.get("ctType"))),
        )

    def _funding(self, raw: dict) -> NormalizedFunding:
        return NormalizedFunding(
            external_id=str(raw["billId"]),
            occurred_at=_at(int(raw["ts"])),
            symbol=str(raw["instId"]),
            # The documentation's own pointer for a funding bill: the payment
            # is `pnl`, signed — positive received, negative paid.
            amount=Decimal(str(raw["pnl"])),
            settlement_symbol=str(raw["ccy"]),
        )

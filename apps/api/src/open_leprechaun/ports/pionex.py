"""Pionex futures adapter (ticket 35): the venue's REST API translated into
the port's normalized fills and funding.

Pionex exposes only bare perp fills — no position side, no reduce-only flag,
no per-fill realised result — and roughly 90 days of history, so the
enrichment trio stays None and derivation falls back to the documented net
accounting (ticket 28). Its perp API serves USDT-margined linear contracts;
coin-margined exposure exists only inside grid bots, whose per-bot totals the
fills API never shows — a symbol quoted in anything but USDT therefore leaves
`inverse` unstated, and derivation refuses the stream rather than guess.

Auth, verified against the live API in the previous implementation:
HMAC-SHA256 (hex) over METHOD + PATH_URL [+ body], where PATH_URL is the
request path plus the alphabetically sorted query string, which includes
timestamp=<ms>. The timestamp is NOT appended a second time. Sent via the
PIONEX-KEY and PIONEX-SIGNATURE headers.

Quirks absorbed here: fills and funding page backwards by timestamp cursor
inside 60-day request windows (the API caps the span per request); traded
symbols are discovered from open orders plus the paged closed-order history,
which reaches further back than the fills endpoint and captures bot activity
too; Pionex signals logical errors with HTTP 200 plus {result: false}.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from open_leprechaun.ports.exchange import (
    AdapterError,
    Credentials,
    Harvest,
    NormalizedFill,
    NormalizedFunding,
)

BASE_URL = "https://api.pionex.com"

_BALANCES_PATH = "/api/v1/account/balances"
_FILLS_PATH = "/uapi/v1/trade/fills"
_FUNDING_PATH = "/uapi/v1/trade/fundingFee"
_HISTORY_ORDERS_PATH = "/uapi/v1/trade/historyOrders"
_OPEN_ORDERS_PATH = "/uapi/v1/trade/openOrders"

# The venue serves ~90 days of perp history; the adapter asks for exactly
# that and nothing pretends to reach further (ticket 40 will say so in the UI).
LOOKBACK_DAYS = 90
# Requests span at most 60 days — under the API's span cap — paged backwards
# by timestamp cursor within each window.
_WINDOW_MS = 60 * 24 * 3600 * 1000
_PAGE_LIMIT = 200
_ORDER_PAGE_LIMIT = 100
# Page budget for symbol discovery; exhausting it means truncation, which is
# an error to raise, never a silent shortfall.
_MAX_HISTORY_PAGES = 50


def _sign(
    secret: str,
    method: str,
    path: str,
    params: dict[str, str],
    body: str = "",
    timestamp: str | None = None,
) -> tuple[str, str]:
    """(path_url, signature) for a private request. `timestamp` is
    injectable only to make the signing testable; live calls leave it None
    for the current time in milliseconds."""
    stamped = {**params, "timestamp": timestamp or str(int(time.time() * 1000))}
    query = "&".join(f"{key}={stamped[key]}" for key in sorted(stamped))
    path_url = f"{path}?{query}"
    message = f"{method.upper()}{path_url}{body}"
    return path_url, hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def _quote(symbol: str) -> str:
    """ "BTC_USDT_PERP" -> "USDT"."""
    parts = symbol.split("_")
    return parts[1] if len(parts) > 1 else "USDT"


def _at(milliseconds: int) -> datetime:
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


class PionexFuturesAdapter:
    """The futures kind of a Pionex Connection: fills and funding out,
    nothing else — Pionex's spot API is a later adapter's concern."""

    kind = "futures"
    lookback_days = LOOKBACK_DAYS

    def __init__(self, client: httpx.Client | None = None, throttle_seconds: float = 0.15) -> None:
        self._client = client or httpx.Client(timeout=15.0)
        # A small pause between paged requests respects the venue's rate
        # limits; tests pass zero.
        self._throttle_seconds = throttle_seconds

    def test(self, credentials: Credentials) -> str:
        data = self._signed_get(credentials, _BALANCES_PATH)
        balances = (data.get("data") or {}).get("balances") or []
        return f"Authenticated — {len(balances)} account balances visible."

    def pull(self, credentials: Credentials) -> Harvest:
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - LOOKBACK_DAYS * 24 * 3600 * 1000
        fills: list[NormalizedFill] = []
        funding: list[NormalizedFunding] = []
        for symbol in self._traded_symbols(credentials):
            quote = _quote(symbol)
            for raw in self._paged(
                credentials,
                _FILLS_PATH,
                "fills",
                symbol,
                start_ms,
                end_ms,
                key=lambda row: row["id"],
            ):
                fills.append(self._normalized_fill(raw, symbol, quote))
            for raw in self._paged(
                credentials,
                _FUNDING_PATH,
                "fundings",
                symbol,
                start_ms,
                end_ms,
                # The venue assigns funding no id; within one symbol the
                # payment instant is its identity — the same fact the dedup
                # external id is built from.
                key=lambda row: row["timestamp"],
            ):
                funding.append(self._normalized_funding(raw, symbol, quote))
        return Harvest(fills=tuple(fills), funding=tuple(funding))

    def _signed_get(
        self, credentials: Credentials, path: str, params: dict[str, str] | None = None
    ) -> dict:
        if not credentials.secret:
            raise AdapterError("Pionex signs with a secret, and this credential has none.")
        path_url, signature = _sign(credentials.secret, "GET", path, params or {})
        headers = {"PIONEX-KEY": credentials.key, "PIONEX-SIGNATURE": signature}
        try:
            response = self._client.get(f"{BASE_URL}{path_url}", headers=headers)
        except httpx.HTTPError as failed:
            raise AdapterError(f"The Pionex request failed: {failed}") from failed
        try:
            data = response.json()
        except ValueError as failed:
            raise AdapterError(
                f"Pionex answered something that is not JSON (HTTP {response.status_code})."
            ) from failed
        # Pionex signals logical errors with HTTP 200 + {result: false,
        # code, message}, and some auth failures with a non-200 status.
        if response.status_code != 200 or not data.get("result", False):
            code = data.get("code") or response.status_code
            message = data.get("message") or response.text[:200]
            raise AdapterError(f"Pionex API error [{code}]: {message}")
        return data

    def _traded_symbols(self, credentials: Credentials) -> list[str]:
        """Perp symbols the account has traded — open orders plus the paged
        closed-order history, which reaches further back than the fills
        endpoint and captures manual and bot activity alike."""
        symbols: set[str] = set()
        try:
            data = self._signed_get(credentials, _OPEN_ORDERS_PATH)
            orders = (data.get("data") or {}).get("orders") or []
            symbols.update(order["symbol"] for order in orders if order.get("symbol"))
        except AdapterError:
            # Open orders are a bonus; the closed-order history is the
            # primary source.
            pass

        cursor = int(time.time() * 1000)
        for _ in range(_MAX_HISTORY_PAGES):
            data = self._signed_get(
                credentials,
                _HISTORY_ORDERS_PATH,
                {"endTime": str(cursor), "limit": str(_ORDER_PAGE_LIMIT)},
            )
            orders = (data.get("data") or {}).get("orders") or []
            if not orders:
                break
            symbols.update(order["symbol"] for order in orders if order.get("symbol"))
            if len(orders) < _ORDER_PAGE_LIMIT:
                break
            instants = (
                int(order.get("updateTime") or order.get("createTime") or 0) for order in orders
            )
            cursor = min(instants) - 1
            self._pause()
        else:
            raise AdapterError(
                "Symbol discovery may be truncated — the"
                f" {_MAX_HISTORY_PAGES}-page order-history budget ran out before"
                " the history did."
            )
        return sorted(symbol for symbol in symbols if symbol.endswith("_PERP"))

    def _paged(
        self,
        credentials: Credentials,
        path: str,
        field: str,
        symbol: str,
        start_ms: int,
        end_ms: int,
        key: Callable[[dict], object],
    ) -> Iterator[dict]:
        """Walk one endpoint backwards over the lookback: 60-day windows,
        each paged by moving its end cursor onto the oldest instant answered.

        The cursor lands *on* that instant, not past it — a full page can cut
        through the middle of one millisecond, and stepping straight past
        would silently drop whatever shared it. The boundary rows come back
        on the next page and `key` deduplicates them; only once a full page
        holds nothing new — everything the API will ever show at that instant
        already answered — does the cursor step beyond it."""
        seen: set[object] = set()
        window_end = end_ms
        while window_end >= start_ms:
            window_start = max(start_ms, window_end - _WINDOW_MS)
            cursor = window_end
            while cursor >= window_start:
                data = self._signed_get(
                    credentials,
                    path,
                    {
                        "symbol": symbol,
                        "startTime": str(window_start),
                        "endTime": str(cursor),
                        "limit": str(_PAGE_LIMIT),
                    },
                )
                rows = (data.get("data") or {}).get(field) or []
                fresh = [row for row in rows if key(row) not in seen]
                for row in fresh:
                    seen.add(key(row))
                    yield row
                if len(rows) < _PAGE_LIMIT:
                    break
                oldest = min(int(row["timestamp"]) for row in rows)
                # A full page of only-seen rows: the boundary instant is
                # drained as deep as the API answers, so step past it —
                # otherwise land on it and drain it first.
                cursor = oldest - 1 if not fresh else min(cursor, oldest)
                self._pause()
            window_end = window_start - 1

    def _normalized_fill(self, raw: dict, symbol: str, quote: str) -> NormalizedFill:
        fee_coin = raw.get("feeCoin")
        if fee_coin and fee_coin != quote:
            raise AdapterError(
                f"A {symbol} fill's fee arrived in {fee_coin!r} rather than the"
                f" settlement asset {quote!r} — the port states fees in the"
                " settlement asset only."
            )
        return NormalizedFill(
            external_id=str(raw["id"]),
            occurred_at=_at(int(raw["timestamp"])),
            symbol=symbol,
            side=str(raw["side"]).lower(),
            price=Decimal(str(raw["price"])),
            size=Decimal(str(raw["size"])),
            fee=Decimal(str(raw.get("fee") or "0")),
            settlement_symbol=quote,
            # USDT-quoted perps are Pionex's linear contracts; anything else
            # is unstated, and derivation refuses the stream rather than
            # book a coin-settled result in the wrong unit.
            inverse=False if quote == "USDT" else None,
        )

    def _normalized_funding(self, raw: dict, symbol: str, quote: str) -> NormalizedFunding:
        # The venue assigns funding no id of its own; symbol plus payment
        # instant is the identity the dedup key needs.
        instant = int(raw["timestamp"])
        return NormalizedFunding(
            external_id=f"{symbol}|{instant}",
            occurred_at=_at(instant),
            symbol=symbol,
            amount=Decimal(str(raw.get("fundingFee") or "0")),
            settlement_symbol=str(raw.get("fundingCoin") or quote),
        )

    def _pause(self) -> None:
        if self._throttle_seconds:
            time.sleep(self._throttle_seconds)

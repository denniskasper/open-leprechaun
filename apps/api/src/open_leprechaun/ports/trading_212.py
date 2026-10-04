"""The Trading 212 adapter (ticket 48): the venue's Public API translated
into the broker port's normalized records — security trades from the order
history's fills, dividends from the dividend history, cash movements, account
fees and interest from the transaction history, and the open positions and
cash for Reconciliation alone.

Auth, as the venue documents it: HTTP Basic on every request, the API key as
the username and the API secret as the password. A key carries scopes chosen
when it is generated; an endpoint a key lacks the scope for answers 403.

Quirks absorbed here: a sale's quantity stated negative; charges stated as
`taxes` inside a fill's wallet impact, negative or not; a fill's `netValue`
being the wallet's whole movement, fees included; `fxRate` documented as a
number with no direction; London prices stated in pence ("GBX"); history
served newest first, paged by a `nextPagePath` to follow, with no lookback
cap; a rate limit per endpoint and per account, announced in `x-ratelimit-*`
headers; and JSON numbers, read here as decimals without ever passing through
a float.

The API serves Invest and Stocks ISA accounts in their primary currency only
— a multi-currency Depot's other balances are not stated by it.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import httpx

from open_leprechaun.ports.broker import (
    AdapterError,
    BrokerHarvest,
    CoveredPeriod,
    Credentials,
    NormalizedAccountFee,
    NormalizedCashMovement,
    NormalizedDividend,
    NormalizedFee,
    NormalizedOriginalAmount,
    NormalizedPosition,
    NormalizedSecurity,
    NormalizedSecurityTrade,
    PassedOver,
)

BASE_URL = "https://live.trading212.com"

_SUMMARY_PATH = "/api/v0/equity/account/summary"
_POSITIONS_PATH = "/api/v0/equity/positions"
_HISTORY_PREFIX = "/api/v0/equity/history/"
_ORDERS_PATH = f"{_HISTORY_PREFIX}orders"
_DIVIDENDS_PATH = f"{_HISTORY_PREFIX}dividends"
_TRANSACTIONS_PATH = f"{_HISTORY_PREFIX}transactions"

# The scope each endpoint answers 403 without, as the venue names them.
_SCOPES = {
    _SUMMARY_PATH: "account",
    _POSITIONS_PATH: "portfolio",
    _ORDERS_PATH: "history:orders",
    _DIVIDENDS_PATH: "history:dividends",
    _TRANSACTIONS_PATH: "history:transactions",
}

# The venue pages a Depot's whole history — there is no cap to declare
# (ADR-0008: None is "unbounded", and the UI says so).
LOOKBACK_DAYS = None
_PAGE_LIMIT = 50
# Page budget per walk; exhausting it means truncation, which is an error to
# raise, never a silent shortfall. Generous, because every sync walks the
# whole unbounded history: fifty thousand rows per walk.
_MAX_PAGES = 1000
# The longest a rate-limited request waits for the venue's stated reset
# before asking once more.
_MAX_WAIT_SECONDS = 65

_SIDES: dict[str, Literal["buy", "sell"]] = {"BUY": "buy", "SELL": "sell"}
# Sub-units the venue prices in, as (the whole currency, sub-units per unit).
_MINOR_UNITS = {"GBX": ("GBP", 100)}
_CONVERSION_FEE = "CURRENCY_CONVERSION_FEE"
# How far the stated rate may sit from the one the fill's own amounts imply:
# wide enough for the venue's rounding and for a fee folded into the rate,
# far too narrow to mistake a rate for its inverse.
_RATE_TOLERANCE = Decimal("0.02")

# Dividend-history types that are no income from capital: a return of capital
# reduces a cost basis, a demerger or a liquidation payment is fact-specific
# — each a Corporate Action the Admin records, never a dividend.
_NOT_INCOME = ("RETURN_OF_CAPITAL", "DEMERGER", "INTERIM_LIQUIDATION")
_INTEREST_TRANSACTIONS = frozenset({"INTEREST_ON_FREE_CASH", "LENDING_INTEREST"})


def _decimal(stated: object) -> Decimal:
    if isinstance(stated, bool) or not isinstance(stated, (int, Decimal, str)):
        raise TypeError("not a number")
    return Decimal(stated)


def _at(stated: str) -> datetime:
    at = datetime.fromisoformat(stated)
    # The venue states an offset; were one ever missing, UTC is what it means
    # — never the server's own timezone.
    return at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)


def _whole_units(amount: Decimal, currency: str) -> tuple[Decimal, str]:
    """An amount in the currency's whole units (ADR-0008): the venue prices
    London-listed paper in pence under its own code."""
    if currency in _MINOR_UNITS:
        whole, per_unit = _MINOR_UNITS[currency]
        return amount / per_unit, whole
    return amount, currency


def _security(raw: dict) -> NormalizedSecurity:
    ticker = str(raw["ticker"])
    return NormalizedSecurity(
        isin=str(raw["isin"]),
        # The venue's ticker is its own key ("AAPL_US_EQ"); its head is the
        # label a human knows the paper by.
        symbol=ticker.split("_")[0],
        name=str(raw.get("name") or ticker),
    )


class Trading212Adapter:
    """The securities kind of a Trading 212 Connection: everything the Depot
    did that the venue's API states in a documented shape. What reaches the
    history without being a transaction — a split, a spin-off, a return of
    capital — is passed over by name for the Admin to record; a cash
    transaction of a type the venue does not document refuses the pull."""

    kind = "securities"
    lookback_days = LOOKBACK_DAYS

    def __init__(
        self,
        client: httpx.Client | None = None,
        # The history endpoints allow twenty requests a minute per account.
        throttle_seconds: float = 3.1,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client or httpx.Client(timeout=30.0)
        self._throttle_seconds = throttle_seconds
        self._now = now
        self._sleep = sleep

    def test(self, credentials: Credentials) -> str:
        summary = self._get(credentials, _SUMMARY_PATH)
        # Open every other endpoint a sync or a reconciliation reads, so a
        # scope left unticked is named now rather than on the first sync.
        missing = []
        for path in (_POSITIONS_PATH, _ORDERS_PATH, _DIVIDENDS_PATH, _TRANSACTIONS_PATH):
            try:
                self._get(credentials, path if path == _POSITIONS_PATH else f"{path}?limit=1")
            except _ScopeMissingError:
                missing.append(_SCOPES[path])
        if missing:
            raise AdapterError(
                f"The key lacks {' and '.join(missing)} — generate one with every read"
                " scope the setup screen names, and store that instead."
            )
        currency = summary.get("currency") if isinstance(summary, dict) else None
        if not currency:
            raise AdapterError("Trading 212 answered an account summary that names no currency.")
        return (
            f"Authenticated — the Depot settles in {currency}. Trading 212 cannot state"
            " a key's own scopes, so that it grants no trading scope is yours to check."
        )

    def pull(self, credentials: Credentials) -> BrokerHarvest:
        try:
            return self._harvest(credentials)
        except (KeyError, ValueError, TypeError, ArithmeticError, AttributeError) as failed:
            raise AdapterError(
                "Trading 212 answered a row the adapter could not read — a field"
                f" it documents was missing or malformed ({type(failed).__name__})."
            ) from failed

    def normalized_positions(self, credentials: Credentials) -> tuple[NormalizedPosition, ...]:
        try:
            as_of = self._now()
            summary = self._get(credentials, _SUMMARY_PATH)
            held = self._get(credentials, _POSITIONS_PATH)
            positions = [
                NormalizedPosition(
                    symbol=(security := _security(raw["instrument"])).symbol,
                    quantity=_decimal(raw["quantity"]),
                    as_of=as_of,
                    isin=security.isin,
                )
                for raw in held
            ]
            cash = summary["cash"]
            # Free, reserved for pending orders and uninvested inside pies:
            # all of it is cash the Depot holds.
            balance = sum(
                (
                    _decimal(cash.get(part) or 0)
                    for part in ("availableToTrade", "reservedForOrders", "inPies")
                ),
                Decimal(0),
            )
            positions.append(
                NormalizedPosition(symbol=str(summary["currency"]), quantity=balance, as_of=as_of)
            )
            return tuple(positions)
        except (KeyError, ValueError, TypeError, ArithmeticError, AttributeError) as failed:
            raise AdapterError(
                "Trading 212 answered a position the adapter could not read — a field"
                f" it documents was missing or malformed ({type(failed).__name__})."
            ) from failed

    def _harvest(self, credentials: Credentials) -> BrokerHarvest:
        covered_until = self._now()
        trades: list[NormalizedSecurityTrade] = []
        dividends: list[NormalizedDividend] = []
        cash_movements: list[NormalizedCashMovement] = []
        account_fees: list[NormalizedAccountFee] = []
        passed_over: list[PassedOver] = []

        for raw in self._paged(credentials, _ORDERS_PATH):
            fill = raw.get("fill")
            # An order that was cancelled, rejected or is still working
            # filled nothing, and states nothing.
            if not fill or not _decimal(fill["quantity"]):
                continue
            if fill.get("type") == "TRADE":
                trades.append(self._trade(raw["order"], fill))
            else:
                security = _security(raw["order"]["instrument"])
                passed_over.append(
                    PassedOver(
                        external_id=f"fill-{fill['id']}",
                        occurred_at=_at(str(fill["filledAt"])),
                        description=(
                            f"{fill.get('type')} of {_decimal(fill['quantity'])}"
                            f" {security.name} ({security.isin}) — no trade; record it"
                            " as the Corporate Action it is."
                        ),
                    )
                )

        for raw in self._paged(credentials, _DIVIDENDS_PATH):
            stated_type = str(raw.get("type"))
            if stated_type.startswith(_NOT_INCOME):
                security = _security(raw["instrument"])
                passed_over.append(
                    PassedOver(
                        external_id=f"dividend-{raw['reference']}",
                        occurred_at=_at(str(raw["paidOn"])),
                        description=(
                            f"{stated_type} of {abs(_decimal(raw['amount']))} {raw['currency']}"
                            f" from {security.name} ({security.isin}) — no income from"
                            " capital; record it by hand."
                        ),
                    )
                )
                continue
            if _decimal(raw["amount"]) <= 0:
                # A correction takes a payment back; booked as income it
                # would be taxed, so it is named for the Admin instead.
                passed_over.append(
                    PassedOver(
                        external_id=f"dividend-{raw['reference']}",
                        occurred_at=_at(str(raw["paidOn"])),
                        description=(
                            f"{stated_type} of {_decimal(raw['amount'])} {raw['currency']}"
                            f" ({raw['instrument']['isin']}) — a payment taken back, not"
                            " income; correct the dividend it reverses by hand."
                        ),
                    )
                )
                continue
            dividends.append(self._dividend(raw, stated_type))

        unshaped: set[str] = set()
        for raw in self._paged(credentials, _TRANSACTIONS_PATH):
            amount = _decimal(raw["amount"])
            if not amount:
                continue
            stated_type = str(raw.get("type"))
            external_id = f"transaction-{raw['reference']}"
            occurred_at = _at(str(raw["dateTime"]))
            currency = str(raw["currency"])
            direction: Literal["in", "out"] | None = {
                # The venue documents no sign for these, so the type alone
                # says which way the cash went.
                "DEPOSIT": "in",
                "WITHDRAW": "out",
                # Between the Admin's own accounts at the venue: only the
                # amount's sign says which way.
                "TRANSFER": "in" if amount > 0 else "out",
            }.get(stated_type)
            if direction is not None:
                cash_movements.append(
                    NormalizedCashMovement(
                        external_id=external_id,
                        occurred_at=occurred_at,
                        direction=direction,
                        currency=currency,
                        amount=abs(amount),
                    )
                )
            elif stated_type == "FEE":
                account_fees.append(
                    NormalizedAccountFee(
                        external_id=external_id,
                        occurred_at=occurred_at,
                        amount=abs(amount),
                        currency=currency,
                    )
                )
            elif stated_type in _INTEREST_TRANSACTIONS and amount < 0:
                passed_over.append(
                    PassedOver(
                        external_id=external_id,
                        occurred_at=occurred_at,
                        description=(
                            f"{stated_type} of {amount} {currency} — interest taken back,"
                            " not income; correct the payment it reverses by hand."
                        ),
                    )
                )
            elif stated_type in _INTEREST_TRANSACTIONS:
                dividends.append(
                    NormalizedDividend(
                        external_id=external_id,
                        occurred_at=occurred_at,
                        kind="interest",
                        amount=amount,
                        currency=currency,
                    )
                )
            else:
                unshaped.add(stated_type)
        if unshaped:
            named = ", ".join(repr(stated_type) for stated_type in sorted(unshaped))
            raise AdapterError(
                f"The Depot holds {named} transactions, which the venue documents"
                " no shape for — the kind refuses rather than import a history with"
                " those movements missing."
            )
        return BrokerHarvest(
            covered=CoveredPeriod(start=None, end=covered_until),
            trades=tuple(trades),
            dividends=tuple(dividends),
            cash_movements=tuple(cash_movements),
            account_fees=tuple(account_fees),
            passed_over=tuple(passed_over),
        )

    def _trade(self, order: dict, fill: dict) -> NormalizedSecurityTrade:
        instrument = order["instrument"]
        wallet = fill["walletImpact"]
        settlement_currency = str(wallet["currency"])
        side = _SIDES.get(str(order["side"]).upper())
        if side is None:
            raise AdapterError(
                f"Fill {fill['id']} states the side {order['side']!r}, neither a buy nor"
                " a sale — refused rather than guessed."
            )
        quantity = abs(_decimal(fill["quantity"]))

        fees = []
        for tax in wallet.get("taxes") or []:
            amount = abs(_decimal(tax["quantity"]))
            if not amount:
                continue
            name = str(tax["name"])
            if tax.get("currency", settlement_currency) != settlement_currency:
                raise AdapterError(
                    f"Fill {fill['id']}'s {name} was charged in {tax['currency']!r}"
                    f" rather than the settlement currency {settlement_currency!r} —"
                    " refused rather than netted across currencies."
                )
            fees.append(
                NormalizedFee(
                    name=name,
                    amount=amount,
                    currency=settlement_currency,
                    # Converting the currency is what that fee paid for; every
                    # other charge is a cost of the trade itself.
                    charged_against="cash" if name == _CONVERSION_FEE else "security",
                )
            )
        charged = sum((fee.amount for fee in fees), Decimal(0))
        # The wallet's movement is net: a purchase debits the security's price
        # plus the fees, a sale credits it less them.
        net = abs(_decimal(wallet["netValue"]))
        settled = net - charged if side == "buy" else net + charged
        if settled <= 0:
            raise AdapterError(
                f"Fill {fill['id']} states fees no smaller than the amount it"
                " moved — refused rather than booked as a trade for nothing."
            )

        original = None
        priced, priced_in = _whole_units(
            quantity * _decimal(fill["price"]), str(instrument["currency"])
        )
        if priced_in != settlement_currency:
            original = NormalizedOriginalAmount(
                amount=priced,
                currency=priced_in,
                fx_rate=self._rate(priced, settled, wallet.get("fxRate")),
            )
        return NormalizedSecurityTrade(
            external_id=f"fill-{fill['id']}",
            occurred_at=_at(str(fill["filledAt"])),
            security=_security(instrument),
            side=side,
            quantity=quantity,
            settled_amount=settled,
            settlement_currency=settlement_currency,
            original=original,
            fees=tuple(fees),
        )

    @staticmethod
    def _rate(original: Decimal, settled: Decimal, stated: object) -> Decimal:
        """The rate in the port's direction — original currency per one unit
        of settlement currency. The venue documents `fxRate` as a number with
        no direction, so the stated rate is kept in whichever direction
        reproduces the fill's own amounts; where it is absent or reproduces
        them in neither, the rate those amounts imply is the one the broker
        applied, and a trade is never refused over it."""
        implied = original / settled
        if stated is not None and (rate := _decimal(stated)):
            for candidate in (rate, 1 / rate):
                if abs(candidate - implied) <= _RATE_TOLERANCE * implied:
                    return candidate
        return implied

    @staticmethod
    def _dividend(raw: dict, stated_type: str) -> NormalizedDividend:
        gross_amount = gross_currency = None
        if raw.get("grossAmountPerShare") is not None and raw.get("tickerCurrency"):
            gross_amount, gross_currency = _whole_units(
                _decimal(raw["grossAmountPerShare"]) * abs(_decimal(raw["quantity"])),
                str(raw["tickerCurrency"]),
            )
        return NormalizedDividend(
            external_id=f"dividend-{raw['reference']}",
            occurred_at=_at(str(raw["paidOn"])),
            kind="interest" if "INTEREST" in stated_type else "dividend",
            amount=_decimal(raw["amount"]),
            currency=str(raw["currency"]),
            security=_security(raw["instrument"]),
            gross_amount=gross_amount,
            gross_currency=gross_currency,
        )

    def _paged(self, credentials: Credentials, path: str) -> Iterator[dict]:
        """Walk one history list by following the `nextPagePath` each answer
        states, until it states none."""
        next_path = f"{path}?limit={_PAGE_LIMIT}"
        for pages_read in range(1, _MAX_PAGES + 1):
            page = self._get(credentials, next_path)
            yield from page.get("items") or []
            stated = page.get("nextPagePath")
            if not stated:
                return
            # The venue states a path; anything else is never followed, so
            # the credentials are only ever sent to the venue's own host.
            if not str(stated).startswith(f"{path}?"):
                raise AdapterError(f"The walk over {path} was pointed elsewhere — refused.")
            if pages_read == _MAX_PAGES:
                break
            if self._throttle_seconds:
                self._sleep(self._throttle_seconds)
            next_path = str(stated)
        raise AdapterError(
            f"The walk over {path} may be truncated — the {_MAX_PAGES}-page"
            " budget ran out before the history did."
        )

    def _get(self, credentials: Credentials, path_url: str) -> dict | list:
        if not credentials.secret:
            raise AdapterError(
                "Trading 212 authenticates with a key and its secret, and this"
                " credential has no secret."
            )
        path = path_url.partition("?")[0]
        response = self._send(credentials, path_url)
        if response.status_code == 429:
            # The venue states when the limit resets; wait it out once.
            self._sleep(self._wait_seconds(response))
            response = self._send(credentials, path_url)
            if response.status_code == 429:
                raise AdapterError(
                    f"Trading 212's rate limit on {path} did not lift — try again in a minute."
                )
        if response.status_code == 403:
            raise _ScopeMissingError(
                f"The key lacks the {_SCOPES.get(path, 'required')} scope —"
                " generate one with every read scope the setup screen names."
            )
        if response.status_code != 200:
            raise AdapterError(f"Trading 212 API error [HTTP {response.status_code}] on {path}.")
        try:
            # Numbers arrive as JSON numbers; reading them straight into
            # decimals keeps every amount exactly as the venue printed it.
            return json.loads(response.text, parse_float=Decimal)
        except ValueError as failed:
            raise AdapterError(
                f"Trading 212 answered something that is not JSON (HTTP {response.status_code})."
            ) from failed

    def _send(self, credentials: Credentials, path_url: str) -> httpx.Response:
        try:
            return self._client.get(
                f"{BASE_URL}{path_url}", auth=(credentials.key, credentials.secret or "")
            )
        except httpx.HTTPError as failed:
            # Only the failure's type: a transport error's message may quote
            # the request it failed to send.
            raise AdapterError(
                f"The Trading 212 request failed ({type(failed).__name__})."
            ) from None

    def _wait_seconds(self, response: httpx.Response) -> float:
        try:
            until = int(response.headers["x-ratelimit-reset"]) - int(self._now().timestamp())
        except KeyError, ValueError:
            return _MAX_WAIT_SECONDS
        return min(max(until, 0) + 1, _MAX_WAIT_SECONDS)


class _ScopeMissingError(AdapterError):
    """The venue's 403: the key lacks the scope this endpoint needs."""

"""The Bitpanda adapters (ticket 49): the venue's Public API translated into
normalized records — and the first venue whose one account holds coins beside
securities, so it ships a kind of each account-authenticating port. The spot
kind states what the Depot did in crypto through the exchange port; the
securities kind states its securities, cash and income through the broker
port, and what is held right now, for Reconciliation alone. Both read the one
timeline the venue serves; which kind a movement belongs to follows from the
asset it names, never from anything about the account.

Auth, as the venue documents it: the API key alone, in the `x-api-key` header.
A key carries scopes chosen when it is generated and lives a year at most.
The asset and currency lists are public, so the key is never sent to them.

Quirks absorbed here: every asset and currency named by a UUID, resolved
against the venue's own lists — a share may wear the very symbol of a coin; a
paper listed twice under one ISIN; a history served as operations, each a
bundle of transactions, whose types the venue documents no vocabulary for —
so a movement is read from its shape (what arrived, what left, under which
trade) and from the few type names it cannot be read without, and one the
adapter does not know is passed over by name rather than guessed; amounts
whose sign is undocumented, so `flow` alone says which way; a trade fee
inside the cash leg, stated apart by the trade; a cursor that is a timestamp
and must go back with milliseconds; and no lookback cap.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
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
    NormalizedPosition,
    NormalizedSecurity,
    NormalizedSecurityTrade,
    PassedOver,
)
from open_leprechaun.ports.exchange import Harvest, NormalizedTrade, NormalizedTransfer

BASE_URL = "https://api.public.bitpanda.com"

_OPERATIONS_PATH = "/v1/operations"
_PORTFOLIO_PATH = "/v1/portfolio"
_ASSETS_PATH = "/v1/assets"
_CURRENCIES_PATH = "/v1/currencies"

# The scope each of the account's endpoints refuses without, as the venue
# names them.
_SCOPES = {_OPERATIONS_PATH: "Transaction", _PORTFOLIO_PATH: "Balances"}

# The venue pages a Depot's whole history — there is no cap to declare
# (ADR-0008: None is "unbounded", and the UI says so).
LOOKBACK_DAYS = None
_PAGE_SIZE = 25
# Page budget per walk; exhausting it means truncation, which is an error to
# raise, never a silent shortfall. Generous, because every sync walks the
# whole unbounded history: a hundred thousand operations.
_MAX_PAGES = 4000
# The read limit is per second; a limited request waits one out and asks once
# more.
_RATE_LIMIT_WAIT_SECONDS = 1

_CRYPTO_TYPE = "cryptocoin"
# Staking and unstaking, matched whole — a staking *reward* is income.
_INTERNAL = frozenset({"stake", "unstake", "staking", "unstaking"})
_WITHDRAWALS = frozenset({"withdrawal", "withdraw"})
_INCOME = ("dividend", "interest")
_WHOLE_SECOND = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


@dataclass(frozen=True)
class _Thing:
    """What a transaction moved, resolved from the venue's UUID: cash, a
    coin, a security — identified by its ISIN — or something neither port
    can express (a metal, an index)."""

    family: Literal["cash", "crypto", "security", "other"]
    symbol: str
    name: str
    isin: str | None = None

    def security(self) -> NormalizedSecurity:
        return NormalizedSecurity(isin=self.isin or "", symbol=self.symbol, name=self.name)


@dataclass(frozen=True)
class _Leg:
    """One transaction of an operation, its amount unsigned — `incoming`
    says which way."""

    id: str
    at: datetime
    type: str
    incoming: bool
    amount: Decimal
    thing: _Thing
    # A charge stated with the transaction itself, beside what it moved.
    fee: tuple[Decimal, _Thing] | None
    trade_id: str | None
    # The fee a trade states, and the trade's rate before and after it.
    trade_fee: tuple[Decimal, _Thing] | None
    rates: tuple[Decimal, Decimal] | None
    # The security a cash payment names beside its currency.
    payer: _Thing | None
    takes_back: bool

    def stated(self) -> str:
        if self.thing.family == "cash":
            return f"{self.amount:f} {self.thing.symbol}"
        return f"{self.amount:f} {self.thing.symbol} ({self.thing.name})"


@dataclass
class _Reading:
    """One walk over the timeline, sorted into what each port can state."""

    trades: list[NormalizedTrade] = field(default_factory=list)
    transfers: list[NormalizedTransfer] = field(default_factory=list)
    security_trades: list[NormalizedSecurityTrade] = field(default_factory=list)
    dividends: list[NormalizedDividend] = field(default_factory=list)
    cash_movements: list[NormalizedCashMovement] = field(default_factory=list)
    account_fees: list[NormalizedAccountFee] = field(default_factory=list)
    passed_over: list[PassedOver] = field(default_factory=list)

    def pass_over(self, external_id: str, at: datetime, description: str) -> None:
        self.passed_over.append(
            PassedOver(external_id=external_id, occurred_at=at, description=description)
        )


def _decimal(stated: object) -> Decimal:
    if isinstance(stated, bool) or not isinstance(stated, (int, Decimal, str)):
        raise TypeError("not a number")
    return Decimal(stated)


def _at(stated: str) -> datetime:
    at = datetime.fromisoformat(stated)
    # The venue states UTC; were an offset ever missing, UTC is what it means
    # — never the server's own timezone.
    return at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)


def _returnable(cursor: str) -> str:
    """The cursor as the venue takes it back. It is a base64 timestamp, and
    one of whole seconds restarts the listing at its newest page unless it
    returns with milliseconds; any other cursor stays opaque."""
    try:
        stated = base64.b64decode(cursor, validate=True).decode()
    except binascii.Error, UnicodeDecodeError:
        return cursor
    if _WHOLE_SECOND.fullmatch(stated):
        return base64.b64encode(f"{stated[:-1]}.000Z".encode()).decode()
    return cursor


class _Timeline:
    """The venue's API as both kinds read it: the requests, the paging, the
    resolution of UUIDs, and the one sorting of operations into records."""

    def __init__(
        self,
        client: httpx.Client | None,
        now: Callable[[], datetime],
        sleep: Callable[[float], None],
    ) -> None:
        self._client = client or httpx.Client(timeout=30.0)
        self.now = now
        self._sleep = sleep

    def opens(self, credentials: Credentials, path: str) -> bool:
        """Whether the key opens this endpoint — False where the venue
        refuses it, which a wrong key and a missing scope both look like."""
        try:
            self._get(path, {"page_size": 1} if path == _OPERATIONS_PATH else {}, credentials)
        except _RefusedError:
            return False
        return True

    def read(self, credentials: Credentials) -> _Reading:
        operations = list(self._operations(credentials))
        things = self._things(operations)
        reading = _Reading()
        for operation in operations:
            self._read_operation(operation, things, reading)
        return reading

    def positions(self, credentials: Credentials) -> tuple[NormalizedPosition, ...]:
        as_of = self.now()
        held = self._get(_PORTFOLIO_PATH, {}, credentials)["data"]
        things = self._things(held)
        positions = []
        for row in held:
            balance = row["balance"]
            thing = things[
                balance.get("asset_id")
                or balance.get("currency_id")
                or row.get("asset_id")
                or row["currency_id"]
            ]
            positions.append(
                NormalizedPosition(
                    symbol=thing.symbol,
                    quantity=_decimal(balance["value"]),
                    as_of=as_of,
                    isin=thing.isin,
                )
            )
        return tuple(positions)

    # --- Sorting one operation ---

    def _read_operation(self, raw: dict, things: dict[str, _Thing], reading: _Reading) -> None:
        operation_type = str(raw.get("operation_type") or "").lower()
        legs = [
            leg
            for transaction in raw.get("transactions") or []
            if (leg := self._leg(transaction, operation_type, things)).amount
            # Staked coins stay the Admin's and stay at the venue: such a leg
            # moves nothing in or out of the Depot.
            and leg.type not in _INTERNAL
        ]
        if any(leg.takes_back for leg in legs):
            # A correction: booked as what it looks like it would count
            # twice, or as income, so it is named for the Admin instead.
            for leg in legs:
                reading.pass_over(
                    f"transaction-{leg.id}",
                    leg.at,
                    f"{leg.type} of {leg.stated()} takes back an earlier movement —"
                    " correct the transaction it reverses by hand.",
                )
            return

        # Tax taken from the one payment of income an operation states: the
        # payment lands net of it (ADR-0022), its gross kept beside it.
        income = [leg for leg in legs if leg.type in _INCOME and leg.incoming]
        withheld = [
            leg
            for leg in legs
            if leg.type == "tax"
            and not leg.incoming
            and len(income) == 1
            and leg.thing == income[0].thing
        ]
        taken = sum((leg.amount for leg in withheld), Decimal(0))
        if withheld and taken >= income[0].amount:
            withheld, taken = [], Decimal(0)

        exchanges: dict[str, list[_Leg]] = {}
        fees: list[_Leg] = []
        for leg in legs:
            if leg in withheld:
                continue
            if leg.type == "tax":
                # The venue says neither who withheld it nor under which law,
                # and a withholding is declared, never booked as a cost.
                reading.pass_over(
                    f"transaction-{leg.id}",
                    leg.at,
                    f"tax of {leg.stated()} withheld — declare it on the transaction"
                    " it was withheld from.",
                )
            elif leg.type == "fee":
                fees.append(leg)
            elif leg.trade_id is not None:
                exchanges.setdefault(leg.trade_id, []).append(leg)
            else:
                self._single(leg, reading, withheld=taken if leg in income else Decimal(0))

        attached = False
        for trade_id, exchanged in exchanges.items():
            # A fee charged beside the one trade of an operation is a cost of
            # that trade; beside several, nothing says which.
            attached |= self._exchange(
                trade_id, operation_type, exchanged, fees if len(exchanges) == 1 else [], reading
            )
        if attached:
            return
        for fee in fees:
            if fee.thing.family == "cash" and not exchanges and not fee.incoming:
                reading.account_fees.append(
                    NormalizedAccountFee(
                        external_id=f"transaction-{fee.id}",
                        occurred_at=fee.at,
                        amount=fee.amount,
                        currency=fee.thing.symbol,
                    )
                )
            else:
                self._unstatable(fee, reading)

    def _exchange(
        self,
        trade_id: str,
        operation_type: str,
        legs: list[_Leg],
        fees: list[_Leg],
        reading: _Reading,
    ) -> bool:
        """One thing for another under one trade, landed on the port that can
        state it. Answers whether the operation's own fee legs were attached
        to the trade."""
        external_id = f"trade-{trade_id}"
        occurred_at = max(leg.at for leg in legs)
        arrived = [leg for leg in legs if leg.incoming]
        left = [leg for leg in legs if not leg.incoming]
        families = sorted(leg.thing.family for leg in legs)
        if (
            len(arrived) != 1
            or len(left) != 1
            or families
            not in (
                ["cash", "crypto"],
                ["crypto", "crypto"],
                ["cash", "security"],
            )
        ):
            # A metal, an index, one security for another: no record of
            # either port names it.
            reading.pass_over(
                external_id,
                occurred_at,
                f"{operation_type} of {' and '.join(leg.stated() for leg in arrived) or 'nothing'}"
                f" for {' and '.join(leg.stated() for leg in left) or 'nothing'} — no trade"
                " this adapter can state; record it by hand.",
            )
            return False

        (received,), (gave,) = arrived, left
        if families == ["crypto", "crypto"]:
            priced, paid_in, side = received, gave, "buy"
        else:
            paid_in = received if received.thing.family == "cash" else gave
            priced = gave if paid_in is received else received
            side = "buy" if priced.incoming else "sell"

        charged = Decimal(0)
        stated = paid_in.trade_fee or priced.trade_fee or paid_in.fee
        # A fee stated in a currency no leg moved was taken inside the rate —
        # there is no balance it could have left.
        if stated is not None and stated[1] == paid_in.thing and self._fee_inside(paid_in, priced):
            charged = stated[0]
        # What moved is net: a purchase debits the price plus the fee, a sale
        # credits it less the fee.
        settled = paid_in.amount - charged if side == "buy" else paid_in.amount + charged
        if settled <= 0:
            raise AdapterError(
                f"Trade {trade_id} states a fee no smaller than the amount it moved —"
                " refused rather than booked as a trade for nothing."
            )
        beside = [fee for fee in fees if fee.thing == paid_in.thing and not fee.incoming]
        attached = bool(fees) and len(beside) == len(fees)
        apart = sum((fee.amount for fee in beside), Decimal(0)) if attached else Decimal(0)

        if priced.thing.family == "security":
            costs = []
            if charged:
                costs.append(NormalizedFee("TRADE_FEE", charged, paid_in.thing.symbol, "security"))
            if apart:
                costs.append(NormalizedFee("FEE", apart, paid_in.thing.symbol, "security"))
            reading.security_trades.append(
                NormalizedSecurityTrade(
                    external_id=external_id,
                    occurred_at=occurred_at,
                    security=priced.thing.security(),
                    side=side,
                    quantity=priced.amount,
                    settled_amount=settled,
                    settlement_currency=paid_in.thing.symbol,
                    fees=tuple(costs),
                )
            )
        else:
            total = charged + apart
            reading.trades.append(
                NormalizedTrade(
                    external_id=external_id,
                    occurred_at=occurred_at,
                    base_symbol=priced.thing.symbol,
                    quote_symbol=paid_in.thing.symbol,
                    side=side,
                    base_quantity=priced.amount,
                    quote_quantity=settled,
                    fee_symbol=paid_in.thing.symbol if total else None,
                    fee_quantity=total or None,
                )
            )
        return attached

    @staticmethod
    def _fee_inside(paid_in: _Leg, priced: _Leg) -> bool:
        """Whether the fee came out of the leg the trade was paid in. The
        venue states a trade's rate before and after its fee without saying
        which the amounts follow, so the amounts decide: the fee is inside
        unless they reproduce the rate before it."""
        rates = paid_in.rates or priced.rates
        if rates is None or rates[0] == rates[1]:
            return True
        before, after = rates
        implied = paid_in.amount / priced.amount
        return abs(implied - after) <= abs(implied - before)

    def _single(self, leg: _Leg, reading: _Reading, *, withheld: Decimal) -> None:
        """A movement with no trade: cash or a coin entering or leaving the
        Depot, or income from capital — whatever its type name says and its
        direction agrees with. `withheld` is the tax the venue took from an
        income payment before it arrived."""
        external_id = f"transaction-{leg.id}"
        direction: Literal["in", "out"] | None = None
        if leg.type == "deposit" and leg.incoming:
            direction = "in"
        elif leg.type in _WITHDRAWALS and not leg.incoming:
            direction = "out"
        fee = leg.fee[0] if leg.fee is not None and leg.fee[1] == leg.thing else None
        if direction is not None and leg.fee is not None and fee is None:
            raise AdapterError(
                f"Transaction {leg.id} charges its fee in {leg.fee[1].symbol!r} rather than"
                f" in the {leg.thing.symbol!r} it moved — refused rather than netted"
                " across assets."
            )

        if leg.thing.family == "cash" and direction is not None:
            reading.cash_movements.append(
                NormalizedCashMovement(
                    external_id=external_id,
                    occurred_at=leg.at,
                    direction=direction,
                    currency=leg.thing.symbol,
                    amount=leg.amount,
                )
            )
            if fee:
                reading.account_fees.append(
                    NormalizedAccountFee(
                        external_id=f"{external_id}-fee",
                        occurred_at=leg.at,
                        amount=fee,
                        currency=leg.thing.symbol,
                    )
                )
        elif leg.thing.family == "crypto" and direction is not None:
            reading.transfers.append(
                NormalizedTransfer(
                    external_id=external_id,
                    occurred_at=leg.at,
                    direction=direction,
                    symbol=leg.thing.symbol,
                    quantity=leg.amount,
                    fee_quantity=fee,
                )
            )
        elif leg.thing.family == "cash" and leg.incoming and leg.type in _INCOME and not leg.fee:
            payer = leg.payer if leg.payer is not None and leg.payer.isin else None
            reading.dividends.append(
                NormalizedDividend(
                    external_id=external_id,
                    occurred_at=leg.at,
                    kind="dividend" if leg.type == "dividend" else "interest",
                    amount=leg.amount - withheld,
                    currency=leg.thing.symbol,
                    security=None if payer is None or leg.type == "interest" else payer.security(),
                    # The venue says what was taken, not who took it or under
                    # which law — so the gross is stated and the withholding
                    # left for the Admin to declare.
                    gross_amount=leg.amount if withheld else None,
                    gross_currency=leg.thing.symbol if withheld else None,
                )
            )
        else:
            self._unstatable(leg, reading)

    @staticmethod
    def _unstatable(leg: _Leg, reading: _Reading) -> None:
        reading.pass_over(
            f"transaction-{leg.id}",
            leg.at,
            f"{leg.type} of {leg.stated()} {'received' if leg.incoming else 'paid out'}"
            + (f", with a fee of {leg.fee[0]:f} {leg.fee[1].symbol}" if leg.fee else "")
            + " — not a transaction this adapter can state; record it by hand.",
        )

    @staticmethod
    def _leg(raw: dict, operation_type: str, things: dict[str, _Thing]) -> _Leg:
        def amount_of(stated: dict | None) -> tuple[Decimal, _Thing] | None:
            if not stated or not (value := abs(_decimal(stated["value"]))):
                return None
            return value, things[stated.get("asset_id") or stated["currency_id"]]

        moved = raw["asset_amount"]
        thing = things[moved.get("asset_id") or moved["currency_id"]]
        trade = raw.get("trade") or {}
        rates = None
        if trade.get("rate") is not None and trade.get("rate_with_fee") is not None:
            rates = (_decimal(trade["rate"]), _decimal(trade["rate_with_fee"]))
        flow = str(raw["flow"]).upper()
        if flow not in ("INCOMING", "OUTGOING"):
            raise AdapterError(
                f"Transaction {raw['transaction_id']} states the flow {raw['flow']!r}, neither"
                " incoming nor outgoing — refused rather than guessed."
            )
        return _Leg(
            id=str(raw["transaction_id"]),
            at=_at(str(raw["credited_at"])),
            # Only some operations' transactions carry a type of their own;
            # the rest are what their operation is.
            type=str(raw.get("transaction_type") or operation_type).lower(),
            incoming=flow == "INCOMING",
            amount=abs(_decimal(moved["value"])),
            thing=thing,
            fee=amount_of(raw.get("fee_amount")),
            trade_id=str(trade["trade_id"]) if trade.get("trade_id") else None,
            trade_fee=amount_of(trade.get("fee")),
            rates=rates,
            payer=things[raw["asset_id"]]
            if thing.family == "cash" and raw.get("asset_id")
            else None,
            takes_back=bool(raw.get("compensates")),
        )

    # --- Resolving the venue's UUIDs ---

    def _things(self, rows: Iterable[dict]) -> dict[str, _Thing]:
        """Every asset and currency these rows name, by its UUID. An asset
        the venue's own list no longer states is something neither port can
        express, named by the only thing known of it."""
        asset_ids: set[str] = set()

        def collect(node: object) -> None:
            if isinstance(node, dict):
                if node.get("asset_id"):
                    asset_ids.add(str(node["asset_id"]))
                for value in node.values():
                    collect(value)
            elif isinstance(node, list):
                for value in node:
                    collect(value)

        for row in rows:
            collect(row)

        things = {
            str(currency["id"]): _Thing("cash", str(currency["symbol"]), str(currency["name"]))
            for currency in self._get(_CURRENCIES_PATH, {})["data"]
        }
        wanted = sorted(asset_ids)
        for start in range(0, len(wanted), _PAGE_SIZE):
            batch = wanted[start : start + _PAGE_SIZE]
            listed = self._get(_ASSETS_PATH, {"id": ",".join(batch), "page_size": _PAGE_SIZE})
            for asset in listed["data"]:
                isin = str(asset["isin"]) if asset.get("isin") else None
                if asset.get("type") == _CRYPTO_TYPE:
                    family = "crypto"
                elif isin is not None:
                    family = "security"
                else:
                    family = "other"
                things[str(asset["id"])] = _Thing(
                    family, str(asset["symbol"]), str(asset["name"]), isin
                )
        for asset_id in wanted:
            things.setdefault(
                asset_id, _Thing("other", asset_id, "an asset the venue no longer lists")
            )
        return things

    # --- Requests ---

    def _operations(self, credentials: Credentials) -> Iterator[dict]:
        """Walk the timeline by the cursor each answer states, until one
        states there is no further page."""
        cursor: str | None = None
        for _ in range(_MAX_PAGES):
            params: dict[str, str | int] = {"page_size": _PAGE_SIZE}
            if cursor is not None:
                params["cursor"] = cursor
            page = self._get(_OPERATIONS_PATH, params, credentials)
            yield from page.get("data") or []
            if not page.get("has_next_page"):
                return
            stated = page.get("next_cursor")
            following = _returnable(str(stated)) if stated else None
            if following is None or following == cursor:
                raise AdapterError(
                    "The walk over the operations did not advance — the venue stated a"
                    " further page and no new cursor to reach it by."
                )
            cursor = following
        raise AdapterError(
            f"The walk over the operations may be truncated — the {_MAX_PAGES}-page"
            " budget ran out before the history did."
        )

    def _get(
        self, path: str, params: dict[str, str | int], credentials: Credentials | None = None
    ) -> dict:
        """One request. The key travels to the account's endpoints alone —
        the asset and currency lists are public and are asked without it."""
        response = self._send(path, params, credentials)
        if response.status_code == 429:
            self._sleep(_RATE_LIMIT_WAIT_SECONDS)
            response = self._send(path, params, credentials)
            if response.status_code == 429:
                raise AdapterError(
                    f"Bitpanda's rate limit on {path} did not lift — try again in a minute."
                )
        if response.status_code in (401, 403) and credentials is not None:
            raise _RefusedError(
                f"Bitpanda refused the key on {path} — it is wrong, expired (a key lives a"
                f" year at most) or lacks the {_SCOPES.get(path, 'required')} scope."
            )
        if response.status_code != 200:
            raise AdapterError(f"Bitpanda API error [HTTP {response.status_code}] on {path}.")
        try:
            answered = json.loads(response.text, parse_float=Decimal)
        except ValueError as failed:
            raise AdapterError(
                f"Bitpanda answered something that is not JSON (HTTP {response.status_code})."
            ) from failed
        if not isinstance(answered, dict):
            raise AdapterError(f"Bitpanda answered {path} with something that is no object.")
        return answered

    def _send(
        self, path: str, params: dict[str, str | int], credentials: Credentials | None
    ) -> httpx.Response:
        headers = {} if credentials is None else {"x-api-key": credentials.key}
        try:
            return self._client.get(f"{BASE_URL}{path}", params=params, headers=headers)
        except httpx.HTTPError as failed:
            # Only the failure's type: a transport error's message may quote
            # the request it failed to send.
            raise AdapterError(f"The Bitpanda request failed ({type(failed).__name__}).") from None


class _RefusedError(AdapterError):
    """The venue's 401 or 403: the key is wrong, expired or lacks the scope
    this endpoint needs — the venue does not say which."""


_UNPROVABLE = (
    " Bitpanda cannot state a key's own scopes, so that it grants neither Trade (Write)"
    " nor Earn (Write) is yours to check."
)


def _prove_scopes(timeline: _Timeline, credentials: Credentials, paths: tuple[str, ...]) -> None:
    """Open every endpoint a kind reads, so a scope left unticked is named
    now rather than on the first sync."""
    refused = [path for path in paths if not timeline.opens(credentials, path)]
    if not refused:
        return
    scopes = " and ".join(_SCOPES[path] for path in refused)
    if len(refused) == len(paths):
        raise AdapterError(
            f"Bitpanda refused the key — it is wrong, expired (a key lives a year at"
            f" most) or lacks the {scopes} scope{'s' if len(refused) > 1 else ''}."
        )
    raise AdapterError(
        f"The key lacks the {scopes} scope — generate one with every read scope the"
        " setup screen names, and store that instead."
    )


def _unreadable(what: str, failed: Exception) -> AdapterError:
    return AdapterError(
        f"Bitpanda answered {what} the adapter could not read — a field it documents"
        f" was missing or malformed ({type(failed).__name__})."
    )


_MALFORMED = (KeyError, ValueError, TypeError, ArithmeticError, AttributeError)


class BitpandaSpotAdapter:
    """The spot kind of a Bitpanda Connection, on the exchange port: coins
    bought, sold and swapped, and coins entering or leaving the venue. A
    reward, and anything else the port has no record for, is named by the
    securities kind, which speaks for the whole Depot."""

    kind = "spot"
    lookback_days = LOOKBACK_DAYS

    def __init__(
        self,
        client: httpx.Client | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._timeline = _Timeline(client, now, sleep)

    def test(self, credentials: Credentials) -> str:
        _prove_scopes(self._timeline, credentials, (_OPERATIONS_PATH,))
        return "Authenticated — the key reads the history." + _UNPROVABLE

    def pull(self, credentials: Credentials) -> Harvest:
        try:
            reading = self._timeline.read(credentials)
        except _MALFORMED as failed:
            raise _unreadable("a row", failed) from failed
        return Harvest(trades=tuple(reading.trades), transfers=tuple(reading.transfers))


class BitpandaSecuritiesAdapter:
    """The securities kind of a Bitpanda Connection, on the broker port:
    security trades, dividends and interest, cash entering and leaving, and
    standalone fees — plus, by name, everything in the timeline that neither
    port can express. Its positions state the whole Depot, coins included, so
    the one Account is reconciled once and completely."""

    kind = "securities"
    lookback_days = LOOKBACK_DAYS

    def __init__(
        self,
        client: httpx.Client | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._timeline = _Timeline(client, now, sleep)

    def test(self, credentials: Credentials) -> str:
        _prove_scopes(self._timeline, credentials, (_PORTFOLIO_PATH, _OPERATIONS_PATH))
        return "Authenticated — the key reads the history and the balances." + _UNPROVABLE

    def pull(self, credentials: Credentials) -> BrokerHarvest:
        covered_until = self._timeline.now()
        try:
            reading = self._timeline.read(credentials)
        except _MALFORMED as failed:
            raise _unreadable("a row", failed) from failed
        return BrokerHarvest(
            covered=CoveredPeriod(start=None, end=covered_until),
            trades=tuple(reading.security_trades),
            dividends=tuple(reading.dividends),
            cash_movements=tuple(reading.cash_movements),
            account_fees=tuple(reading.account_fees),
            passed_over=tuple(reading.passed_over),
        )

    def normalized_positions(self, credentials: Credentials) -> tuple[NormalizedPosition, ...]:
        try:
            return self._timeline.positions(credentials)
        except _MALFORMED as failed:
            raise _unreadable("a position", failed) from failed

"""The ledger export (ticket 56): the ledger restated in an independent tax
tool's documented import format — CoinTracking's CSV — so a second engine
computes the same year from identical transactions, and a disagreement
between the two is one about rules rather than about data.

Data flows outward only: nothing here, or anywhere, reads that tool back.

The format is CoinTracking's own, as its import pages document it: one row
per movement with a buy side, a sell side and a fee, the place it happened
in `Exchange`, and a `Type` from its fixed list.
"""

import csv
import io
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Engine, Row

from open_leprechaun.repositories import instruments, platforms, stances
from open_leprechaun.services import transactions
from open_leprechaun.services.stances import effective_stance, never_enters_cost_basis
from open_leprechaun.services.transactions import LegOverview, TransactionOverview

FORMAT = "cointracking"
FILENAME = "open-leprechaun-ledger-cointracking.csv"

# The header CoinTracking documents for a hand-made CSV file, followed by the
# four optional columns it allows after the date.
COLUMNS = (
    "Type",
    "Buy Amount",
    "Buy Currency",
    "Sell Amount",
    "Sell Currency",
    "Fee",
    "Fee Currency",
    "Exchange",
    "Trade-Group",
    "Comment",
    "Date",
    "Tx-ID",
    "Buy Value in Account Currency",
    "Sell Value in Account Currency",
    "Liquidity pool",
)


# What each type of the vocabulary becomes in CoinTracking's fixed list of
# types. A trade is its own shape — one row with both sides — and a fee leg
# no row could absorb is an "Other Fee" whatever its Transaction's type.
COINTRACKING_TYPES: Mapping[str, str] = {
    "trade": "Trade",
    "transfer_in": "Deposit",
    "transfer_out": "Withdrawal",
    "spend": "Spend",
    "staking_reward": "Staking",
    "lending_interest": "Lending Income",
    "mining_reward": "Mining",
    "airdrop": "Airdrop",
    # Received for nothing: no income, which is what its untaxed airdrop is.
    "windfall": "Airdrop (non taxable)",
    # Neither a purchase nor income — the position existed. Untaxed income
    # is the one type that mints a holding at a stated value with nothing
    # sold for it; the estimated basis rides in the value column.
    "opening_balance": "Income (non taxable)",
    "dividend": "Dividends Income",
    "distribution": "Dividends Income",
    "interest": "Interest Income",
    "fee": "Other Fee",
}
_OTHER_FEE = "Other Fee"


@dataclass(frozen=True)
class ExportRow:
    """One line of the file: what arrived, what left and what a fee consumed
    at one place, under one of CoinTracking's types."""

    type: str
    buy: Decimal | None
    buy_currency: str | None
    sell: Decimal | None
    sell_currency: str | None
    fee: Decimal | None
    fee_currency: str | None
    # The Account under its Platform — what CoinTracking's `Exchange` column
    # holds, whatever kind of Platform it is.
    account: str
    occurred_at: datetime
    # Stable across exports, so a row can be traced back to its Transaction
    # and a repeated upload is recognised as the same rows.
    tx_id: str
    # What the buy side is worth in the numéraire, stated only where the
    # ledger declares it — an Opening Balance's estimated basis. Everywhere
    # else the tool values the row itself, which is the comparison wanted.
    buy_value: Decimal | None


@dataclass(frozen=True)
class LeftOut:
    """A Transaction the file does not carry, and the sentence saying why —
    so nothing the format cannot express is silently dropped."""

    transaction_id: int
    type: str
    occurred_at: datetime
    reason: str


@dataclass(frozen=True)
class LedgerExport:
    rows: tuple[ExportRow, ...]
    left_out: tuple[LeftOut, ...]


@dataclass
class _Draft:
    """A row while fees are still being placed: CoinTracking's amounts
    include the fee and its fee column states it, where the ledger records
    the fee as a leg of its own."""

    type: str
    buy: LegOverview | None = None
    sell: LegOverview | None = None
    fee: LegOverview | None = None
    # Whether the absorbed fee adds to what was sold rather than coming off
    # what was bought.
    fee_on_sell_side: bool = False
    buy_value: Decimal | None = None

    @property
    def account_id(self) -> int:
        leg = self.buy or self.sell
        assert leg is not None
        return leg.account_id

    def absorb(self, fee: LegOverview) -> bool:
        """Take the fee into this row if it can state it: one fee, charged
        at the same place, in the currency of either side — and never one
        that would consume everything that arrived."""
        if self.fee is not None or fee.account_id != self.account_id:
            return False
        on_sell_side = self.sell is not None and fee.instrument_id == self.sell.instrument_id
        on_buy_side = (
            self.buy is not None
            and fee.instrument_id == self.buy.instrument_id
            and fee.quantity < self.buy.quantity
        )
        if not (on_sell_side or on_buy_side):
            return False
        self.fee = fee
        self.fee_on_sell_side = on_sell_side
        return True


def export(engine: Engine) -> LedgerExport:
    """The whole ledger as CoinTracking rows, oldest first, beside every
    Transaction that could not be stated in them."""
    instrument_of = {row.id: row for row in instruments.list_instruments(engine)}
    platform_names = {row.id: row.name for row in platforms.list_platforms(engine)}
    account_label = {
        row.id: f"{platform_names[row.platform_id]} - {row.name}"
        for row in platforms.list_accounts(engine)
    }
    decisions_of: dict[int, list[Row]] = {}
    for decision in stances.list_stances(engine):
        decisions_of.setdefault(decision.instrument_id, []).append(decision)

    def outside_the_format(leg: LegOverview) -> str | None:
        instrument = instrument_of[leg.instrument_id]
        if instrument.family == "security":
            return (
                f"{instrument.symbol} is a security,"
                " and CoinTracking holds only coins and currencies."
            )
        stance = effective_stance(decisions_of.get(leg.instrument_id, ()), leg.account_id)
        if never_enters_cost_basis(stance):
            return (
                f"{instrument.symbol} stands {stance} at {account_label[leg.account_id]},"
                " outside the cost basis here as well."
            )
        return None

    ledger = sorted(transactions.overview(engine), key=lambda event: (event.occurred_at, event.id))
    stated = {
        event.id: _first(outside_the_format(leg) for leg in event.legs)
        or _drafts(event, account_label)
        for event in ledger
    }

    # CoinTracking tells assets apart by symbol alone, so two Instruments
    # under one symbol would arrive there as one holding. Judged over what is
    # still going out: an ignored namesake takes nothing with it.
    instruments_under: dict[str, set[int]] = {}
    for event in ledger:
        if not isinstance(stated[event.id], str):
            for leg in event.legs:
                symbol = instrument_of[leg.instrument_id].symbol
                instruments_under.setdefault(symbol.upper(), set()).add(leg.instrument_id)

    def shared_symbol(leg: LegOverview) -> str | None:
        symbol = instrument_of[leg.instrument_id].symbol
        if len(instruments_under[symbol.upper()]) > 1:
            return f"The symbol {symbol} names more than one Instrument in this ledger."
        return None

    rows: list[ExportRow] = []
    left_out: list[LeftOut] = []
    for event in ledger:
        drafts = stated[event.id]
        if not isinstance(drafts, str):
            drafts = _first(shared_symbol(leg) for leg in event.legs) or drafts
        if isinstance(drafts, str):
            left_out.append(LeftOut(event.id, event.type, event.occurred_at, drafts))
            continue
        for position, draft in enumerate(drafts, start=1):
            rows.append(
                _row(
                    draft,
                    symbol_of=lambda leg: instrument_of[leg.instrument_id].symbol,
                    account=account_label[draft.account_id],
                    occurred_at=event.occurred_at,
                    tx_id=f"{event.id}-{position}",
                )
            )
    return LedgerExport(rows=tuple(rows), left_out=tuple(left_out))


def _first(reasons: Iterable[str | None]) -> str | None:
    return next((reason for reason in reasons if reason is not None), None)


def _drafts(event: TransactionOverview, account_label: Mapping[int, str]) -> list[_Draft] | str:
    """The rows this Transaction becomes, or the sentence saying why
    CoinTracking's one-row trade cannot state it."""
    arrived = [leg for leg in event.legs if leg.role == "in"]
    left = [leg for leg in event.legs if leg.role == "out"]
    cointracking_type = COINTRACKING_TYPES.get(event.type)
    if cointracking_type is None:
        return f"CoinTracking has no type for a {event.type.replace('_', ' ')}."
    if event.type == "trade":
        shape = "A CoinTracking trade is one asset for one other at one place; this one"
        if len(arrived) != 1 or len(left) != 1:
            return f"{shape} records {len(arrived)} arriving and {len(left)} leaving."
        if arrived[0].account_id != left[0].account_id:
            return (
                f"{shape} spans {account_label[left[0].account_id]}"
                f" and {account_label[arrived[0].account_id]}."
            )
        drafts = [_Draft(cointracking_type, buy=arrived[0], sell=left[0])]
    else:
        drafts = [
            _Draft(cointracking_type, buy=leg, buy_value=event.estimated_basis_eur)
            for leg in arrived
        ] + [_Draft(cointracking_type, sell=leg) for leg in left]
    row_of = {leg.id: draft for draft in drafts for leg in (draft.buy, draft.sell) if leg}
    standalone = []
    for fee in (leg for leg in event.legs if leg.role == "fee"):
        # The row of the leg it was charged against; unattached, the only
        # row there is. A fee no row can state is a row of its own.
        target = (
            row_of.get(fee.charged_against_leg_id)
            if fee.charged_against_leg_id is not None
            else drafts[0]
            if len(drafts) == 1
            else None
        )
        if target is None or not target.absorb(fee):
            standalone.append(_Draft(_OTHER_FEE, sell=fee))
    return drafts + standalone


def _row(
    draft: _Draft,
    *,
    symbol_of: Callable[[LegOverview], str],
    account: str,
    occurred_at: datetime,
    tx_id: str,
) -> ExportRow:
    buy = draft.buy.quantity if draft.buy else None
    sell = draft.sell.quantity if draft.sell else None
    if draft.fee is not None and draft.fee_on_sell_side:
        assert sell is not None
        sell += draft.fee.quantity
    elif draft.fee is not None:
        assert buy is not None
        buy -= draft.fee.quantity
    return ExportRow(
        type=draft.type,
        buy=buy,
        buy_currency=symbol_of(draft.buy) if draft.buy else None,
        sell=sell,
        sell_currency=symbol_of(draft.sell) if draft.sell else None,
        fee=draft.fee.quantity if draft.fee else None,
        fee_currency=symbol_of(draft.fee) if draft.fee else None,
        account=account,
        occurred_at=occurred_at,
        tx_id=tx_id,
        buy_value=draft.buy_value,
    )


def as_csv(export: LedgerExport) -> str:
    """The file itself: every field quoted, as CoinTracking's own header is,
    instants in UTC and amounts as plain decimals — never a float."""
    out = io.StringIO()
    writer = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in export.rows:
        writer.writerow(
            (
                row.type,
                _amount(row.buy),
                row.buy_currency or "",
                _amount(row.sell),
                row.sell_currency or "",
                _amount(row.fee),
                row.fee_currency or "",
                row.account,
                "",
                "",
                row.occurred_at.astimezone(UTC).strftime("%d.%m.%Y %H:%M:%S"),
                row.tx_id,
                _amount(row.buy_value),
                "",
                "",
            )
        )
    return out.getvalue()


def _amount(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")

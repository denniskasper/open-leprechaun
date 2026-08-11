"""The BitBox connector (ticket 32): the transactions CSV the BitBoxApp
exports for one account of a BitBox02 hardware wallet.

What the connector declares about this export, and holds it to:

- The file carries the BitBoxApp's transaction columns; anything else is
  refused rather than mis-parsed.
- Timestamps come in two shapes: RFC 3339 with an offset, converted by that
  offset — and a short local format ("7/26/25 21:51") written from the
  exporting computer's clock with no offset at all. The declared timezone,
  Europe/Berlin, is what a bare timestamp is read in before converting to
  UTC: an export in local time is never tagged UTC, because that shifts
  events across midnight and, at the year's edge, across tax years.
- Amounts and fees are in the coin's smallest unit — satoshi, wei — and the
  Unit column names which. They are divided into whole coins on the way in;
  a unit the connector does not know means an unknown divisor, so that file
  is refused explicitly instead of guessed at.
- One transaction may span several address rows sharing a Transaction ID,
  the fee stated on the first — collapsed into one movement.
- A "sent_to_yourself" transaction moved nothing out of the account, so only
  its network fee is a fact; it is recorded as a standalone fee, and said so.
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from open_leprechaun.ports.csv_connector import (
    FileRejectedError,
    NormalizedRow,
    ParsedFile,
    cell,
)

_REQUIRED_COLUMNS = ("Time", "Type", "Amount", "Unit", "Fee", "Transaction ID")

# The smallest-unit names the BitBoxApp writes, each with the coin it
# subdivides and the power of ten between them.
_UNITS: dict[str, tuple[str, int]] = {
    "satoshi": ("BTC", 8),
    "sat": ("BTC", 8),
    "wei": ("ETH", 18),
    "litoshi": ("LTC", 8),
    "lwei": ("LTC", 8),
}

_TYPES = {"received": "transfer_in", "sent": "transfer_out"}

# The short local formats a real BitBoxApp writes, clock time only.
_SHORT_FORMATS = ("%m/%d/%y %H:%M", "%m/%d/%Y %H:%M", "%m/%d/%y %H:%M:%S", "%m/%d/%Y %H:%M:%S")


@dataclass
class _Movement:
    """One transaction being collapsed across its address rows."""

    occurred_at: datetime
    type: str
    symbol: str
    quantity: Decimal
    fee: Decimal
    note: str | None
    addresses: list[str] = field(default_factory=list)


class BitBoxConnector:
    connector = "bitbox"
    name = "BitBox"
    expects = "The transactions CSV the BitBoxApp exports for one account (⋯ → Export to CSV)."
    timezone = "Europe/Berlin"

    def parse(self, content: str) -> ParsedFile:
        reader = csv.DictReader(io.StringIO(content.removeprefix("﻿")))
        columns = reader.fieldnames or ()
        if any(column not in columns for column in _REQUIRED_COLUMNS):
            raise FileRejectedError(
                "This is not a BitBoxApp export — it does not carry the BitBoxApp's"
                " transaction columns. " + self.expects
            )

        movements: dict[str, _Movement] = {}
        unconfirmed = 0
        for record in reader:
            transaction_id = cell(record, "Transaction ID")
            if not transaction_id:
                continue
            if not cell(record, "Time"):
                # An unconfirmed transaction has no timestamp yet — not a
                # fact until the chain says so.
                unconfirmed += 1
                continue
            symbol, decimals = _unit(cell(record, "Unit"))
            amount = _amount(cell(record, "Amount"), decimals)
            movement = movements.get(transaction_id)
            if movement is not None:
                # A further address row of the same transaction: the amount
                # accumulates, the fee was already stated on the first row.
                if symbol != movement.symbol:
                    raise FileRejectedError(
                        f"Transaction {transaction_id!r} states rows in more than one"
                        " coin — one transaction moves one coin, so this file is"
                        " refused rather than summed across coins."
                    )
                movement.quantity += abs(amount)
                continue
            movements[transaction_id] = _Movement(
                occurred_at=_occurred_at(cell(record, "Time"), self.timezone),
                type=_type(cell(record, "Type")),
                symbol=symbol,
                quantity=abs(amount),
                fee=abs(_fee(record, symbol, decimals)),
                note=cell(record, "Note") or None,
            )

        rows: list[NormalizedRow] = []
        fee_only = 0
        feeless = 0
        for transaction_id, movement in movements.items():
            if movement.type == "sent_to_yourself":
                # The coins never left the account — only the fee is a fact.
                if movement.fee == 0:
                    feeless += 1
                    continue
                fee_only += 1
                rows.append(
                    NormalizedRow(
                        external_id=transaction_id,
                        occurred_at=movement.occurred_at,
                        type="fee",
                        symbol=movement.symbol,
                        quantity=movement.fee,
                        note=movement.note,
                    )
                )
                continue
            rows.append(
                NormalizedRow(
                    external_id=transaction_id,
                    occurred_at=movement.occurred_at,
                    type=movement.type,
                    symbol=movement.symbol,
                    quantity=movement.quantity,
                    fee_quantity=movement.fee or None,
                    note=movement.note,
                )
            )
        return ParsedFile(rows=tuple(rows), warnings=_warnings(unconfirmed, fee_only, feeless))


def _unit(raw: str) -> tuple[str, int]:
    unit = raw.lower()
    if unit not in _UNITS:
        raise FileRejectedError(
            f"This connector cannot support {raw!r} amounts — it knows"
            f" {', '.join(sorted(set(_UNITS)))} — so it refuses this file rather than"
            " guess a conversion."
        )
    return _UNITS[unit]


def _type(raw: str) -> str:
    kind = raw.lower()
    if kind == "sent_to_yourself":
        return kind
    if kind not in _TYPES:
        raise FileRejectedError(
            f"This connector cannot support {raw!r} transactions — it knows received,"
            " sent and sent_to_yourself — so it refuses this file rather than guess."
        )
    return _TYPES[kind]


def _fee(record: dict, symbol: str, decimals: int) -> Decimal:
    """The fee by its own declared unit: the Fee Unit column rules where it
    is stated, the amount's unit stands in where it is empty — and a fee in
    another coin's unit is a variant refused rather than silently divided by
    the wrong power of ten."""
    fee_unit = cell(record, "Fee Unit")
    if fee_unit:
        fee_symbol, fee_decimals = _unit(fee_unit)
        if fee_symbol != symbol:
            raise FileRejectedError(
                f"This file states a fee in {fee_unit!r} beside an amount in another"
                " coin — a variant this connector cannot support, so it refuses the"
                " file rather than guess."
            )
        return _amount(cell(record, "Fee"), fee_decimals)
    return _amount(cell(record, "Fee"), decimals)


def _amount(raw: str, decimals: int) -> Decimal:
    """A smallest-unit count as whole coins — the sub-unit export is never
    taken at face value."""
    if not raw:
        return Decimal(0)
    try:
        return Decimal(raw) / Decimal(10) ** decimals
    except InvalidOperation:
        raise FileRejectedError(
            f"This connector cannot read the amount {raw!r} — not a number it recognises."
        ) from None


def _occurred_at(raw: str, timezone: str) -> datetime:
    """The exported instant as UTC: an offset-carrying timestamp converts by
    its own offset, a bare one is read in the declared timezone first — and a
    shape outside both is refused rather than guessed at."""
    try:
        occurred_at = datetime.fromisoformat(raw)
    except ValueError:
        occurred_at = _short_format(raw)
    if occurred_at is None:
        raise FileRejectedError(
            f"This connector cannot read the timestamp {raw!r} — the BitBoxApp writes"
            " RFC 3339 or M/D/YY H:MM."
        )
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=ZoneInfo(timezone))
    return occurred_at.astimezone(UTC)


def _short_format(raw: str) -> datetime | None:
    for shape in _SHORT_FORMATS:
        try:
            return datetime.strptime(raw, shape)
        except ValueError:
            continue
    return None


def _warnings(unconfirmed: int, fee_only: int, feeless: int) -> tuple[str, ...]:
    warnings: list[str] = []
    if unconfirmed:
        noun = "transaction" if unconfirmed == 1 else "transactions"
        warnings.append(f"{unconfirmed} unconfirmed {noun} left out — not facts yet.")
    if fee_only:
        noun = "transaction" if fee_only == 1 else "transactions"
        warnings.append(
            f"{fee_only} sent-to-yourself {noun} recorded as the network fee only — the"
            " coins never left the account."
        )
    if feeless:
        noun = "transaction" if feeless == 1 else "transactions"
        warnings.append(
            f"{feeless} sent-to-yourself {noun} moved nothing out of the account and paid"
            " no fee — left out."
        )
    return tuple(warnings)

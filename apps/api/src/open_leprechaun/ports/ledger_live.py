"""The Ledger Live connector (ticket 32): the operations CSV a Ledger
hardware wallet's companion app exports.

What the connector declares about this export, and holds it to:

- The file carries the columns of the "operations history" export; anything
  else is refused rather than mis-parsed.
- Timestamps are ISO 8601 in UTC ("2022-12-04T17:49:35.000Z") — the venue
  itself writes UTC, so the declared timezone is UTC and a bare timestamp is
  read as that. A timestamp shape outside ISO 8601 is a variant this
  connector cannot read, and refuses.
- Amounts are whole coin units already, never sub-units.
- Every row names its Ledger account and extended public key. An import
  lands in exactly one Account (ticket 31), so a file spanning several
  Ledger accounts is refused — export one account at a time.
- An OUT row's amount is the whole balance change with the network fee
  already inside it, so no separate fee leg is emitted.

Operation types that move a balance map into the transaction vocabulary; the
rest move nothing the ledger tracks and are left out with a warning naming
them — staking lifecycle operations apart from the others, because a
delegation that parks coins in a pool contract means the holding is no longer
where the ledger says it is, and only the Admin can say where it went.
"""

import csv
import hashlib
import io
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from open_leprechaun.ports.csv_connector import (
    FileRejectedError,
    NormalizedRow,
    ParsedFile,
    cell,
)

_REQUIRED_COLUMNS = (
    "Operation Date",
    "Status",
    "Currency Ticker",
    "Operation Type",
    "Operation Amount",
    "Operation Hash",
    "Account Name",
    "Account xpub",
)

_TYPE_MAP = {
    "IN": "transfer_in",
    "OUT": "transfer_out",
    "REWARD": "staking_reward",
    "REWARD_PAYOUT": "staking_reward",
}

# Staking lifecycle operations: deliberately not mapped, because delegating
# does not change who owns the coins — it is neither a disposal nor an
# acquisition, and must not touch cost basis or the holding period.
_STAKING_OPERATIONS = frozenset(
    {
        "DELEGATE",
        "UNDELEGATE",
        "REDELEGATE",
        "STAKE",
        "UNSTAKE",
        "BOND",
        "UNBOND",
        "WITHDRAW_UNBONDED",
        "FREEZE",
        "UNFREEZE",
        "ACTIVATE",
        "DEACTIVATE",
    }
)


class LedgerLiveConnector:
    connector = "ledger_live"
    name = "Ledger Live"
    expects = (
        "The operations CSV Ledger Live exports for one account"
        " (Accounts → the account → Export operations history)."
    )
    timezone = "UTC"

    def parse(self, content: str) -> ParsedFile:
        reader = csv.DictReader(io.StringIO(content.removeprefix("﻿")))
        columns = reader.fieldnames or ()
        if any(column not in columns for column in _REQUIRED_COLUMNS):
            raise FileRejectedError(
                "This is not a Ledger Live operations export — it does not carry the"
                " operations columns. " + self.expects
            )

        rows: list[NormalizedRow] = []
        accounts: set[str] = set()
        staking: Counter[str] = Counter()
        unmapped: Counter[str] = Counter()
        unconfirmed = 0
        empty = 0
        for record in reader:
            if cell(record, "Status").lower() != "confirmed":
                unconfirmed += 1
                continue
            # The xpub is the Ledger account's own identity; the name beside
            # it is the Admin's editable label. Judged on every confirmed row
            # — a second account represented only by rows the connector would
            # skip must still refuse the file.
            accounts.add(cell(record, "Account xpub") or cell(record, "Account Name"))
            operation = cell(record, "Operation Type").upper()
            ticker = cell(record, "Currency Ticker").upper()
            type = _TYPE_MAP.get(operation)
            if type is None:
                bucket = staking if operation in _STAKING_OPERATIONS else unmapped
                bucket[f"{operation} ({ticker or '?'})"] += 1
                continue
            quantity = _amount(cell(record, "Operation Amount"))
            if not ticker or quantity == 0:
                empty += 1
                continue
            rows.append(
                NormalizedRow(
                    external_id=_external_id(record),
                    occurred_at=_occurred_at(cell(record, "Operation Date")),
                    type=type,
                    symbol=ticker,
                    quantity=abs(quantity),
                    note=cell(record, "Account Name") or None,
                )
            )
        if len(accounts) > 1:
            raise FileRejectedError(
                "This export spans several Ledger accounts, and an import lands in one"
                " Account — export one account at a time."
            )
        return ParsedFile(
            rows=tuple(rows),
            warnings=_warnings(staking, unmapped, unconfirmed, empty),
        )


def _amount(raw: str) -> Decimal:
    try:
        return Decimal(raw) if raw else Decimal(0)
    except InvalidOperation:
        raise FileRejectedError(
            f"This connector cannot read the amount {raw!r} — not a number it recognises."
        ) from None


def _occurred_at(raw: str) -> datetime:
    """The exported instant as UTC. Ledger Live writes ISO 8601 with a Z
    suffix; a bare timestamp is read in the declared timezone (UTC), and any
    other shape is a variant refused rather than guessed at."""
    try:
        occurred_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise FileRejectedError(
            f"This connector cannot read the timestamp {raw!r} — Ledger Live writes ISO 8601 UTC."
        ) from None
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    return occurred_at.astimezone(UTC)


def _external_id(record: dict) -> str:
    """Deterministic across re-exports, distinct across movements: a swap's
    two movements share one chain hash, so the hash alone cannot key them."""
    key = "|".join(
        cell(record, column)
        for column in (
            "Operation Hash",
            "Operation Date",
            "Operation Type",
            "Operation Amount",
            "Currency Ticker",
            "Account xpub",
        )
    )
    return hashlib.sha256(key.encode()).hexdigest()


def _warnings(
    staking: Counter[str], unmapped: Counter[str], unconfirmed: int, empty: int
) -> tuple[str, ...]:
    warnings: list[str] = []
    if staking:
        warnings.append(
            f"Staking operations found and not imported: {_counted(staking)}. Ownership is"
            " unchanged, so cost basis and the holding period are untouched. On chains where"
            " delegation moves coins to a pool contract, record the move between your own"
            " wallets to keep the location accurate."
        )
    if unmapped:
        warnings.append(f"Operations left out (no balance change tracked): {_counted(unmapped)}.")
    if unconfirmed:
        noun = "operation" if unconfirmed == 1 else "operations"
        warnings.append(f"{unconfirmed} unconfirmed {noun} left out — not facts yet.")
    if empty:
        noun = "operation" if empty == 1 else "operations"
        warnings.append(f"{empty} {noun} moved no amount and were left out.")
    return tuple(warnings)


def _counted(operations: Counter[str]) -> str:
    return ", ".join(f"{name} x{count}" for name, count in sorted(operations.items()))

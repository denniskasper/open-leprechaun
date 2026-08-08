"""The Staking Delegation marker (ticket 22): where a holding is presently
committed to a validator, tracked per Account and Instrument — the same coin
may be delegated in one Account and idle in another, so neither alone can
express it.

The marker is informational and carries no tax meaning. Delegating is not a
disposal — ownership never changes — so it creates no private-sale event,
leaves cost basis untouched, and neither restarts the Haltefrist nor extends
it to ten years. Only the resulting rewards are taxable, as Sonstige
Einkünfte at market value on receipt (services/section22). The table is
deliberately not an input class of any materialisation, so marking or
unmarking can never change a lot or a figure; a test holds it to that.

Delegation events an import finds are surfaced as warnings, never imported
as transactions: the transaction vocabulary deliberately has no delegation
type, so a delegation cannot even be recorded as one. Whether coins moved
between the Admin's own Accounts is a fact the Admin states — as a
self-transfer (ticket 16) — never one an import infers from a delegation
event. The import framework (ticket 31) asks `import_warning` for the
sentence it surfaces.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine

from open_leprechaun.repositories import delegations


@dataclass(frozen=True)
class DelegationMarker:
    """One standing marker: this Instrument is presently delegated at this
    Account, with the names the Admin knows the pair by."""

    instrument_id: int
    symbol: str
    instrument_name: str
    account_id: int
    account_name: str
    platform_name: str
    note: str | None
    marked_at: datetime


def mark(engine: Engine, *, instrument_id: int, account_id: int, note: str | None = None) -> bool:
    """Record that this Instrument is delegated at this Account. Marking an
    already-delegated pair refreshes the note — the marker describes the
    present. False when no such Instrument or Account exists."""
    return delegations.mark(engine, instrument_id=instrument_id, account_id=account_id, note=note)


def unmark(engine: Engine, *, instrument_id: int, account_id: int) -> bool:
    """No longer delegated — False when no marker was standing."""
    return delegations.unmark(engine, instrument_id=instrument_id, account_id=account_id)


def overview(engine: Engine) -> list[DelegationMarker]:
    """Every standing marker, grouped the way the Admin reads holdings."""
    return [
        DelegationMarker(
            instrument_id=row.instrument_id,
            symbol=row.symbol,
            instrument_name=row.instrument_name,
            account_id=row.account_id,
            account_name=row.account_name,
            platform_name=row.platform_name,
            note=row.note,
            marked_at=row.marked_at,
        )
        for row in delegations.list_markers(engine)
    ]


def import_warning(*, event: str, symbol: str, account_name: str) -> str:
    """The sentence an import (ticket 31) surfaces for a delegation event it
    found — the event is never imported as a transaction, because whether
    coins moved is the Admin's statement to make, never the import's."""
    return (
        f"The import found a delegation event ({event}) for {symbol} at {account_name}"
        " and did not import it: a delegation is not a transaction. If the coins moved"
        " between your own Accounts, record the movement as a self-transfer; either way"
        " you can set the delegation marker on the holding."
    )

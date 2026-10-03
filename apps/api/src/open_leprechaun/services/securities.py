"""Adding a security by search (ticket 44): the provider's candidates set
against the ledger, so a result that is already an Instrument says so instead
of inviting a duplicate."""

from dataclasses import dataclass
from enum import Enum

from sqlalchemy import Engine

from open_leprechaun.ports.security_search import SecurityCandidate, SecuritySearchProvider
from open_leprechaun.repositories import instruments
from open_leprechaun.repositories.instruments import FUND_TYPES

__all__ = ["FUND_TYPES", "FoundCandidate", "IsinChange", "change_isin", "search"]


@dataclass(frozen=True)
class FoundCandidate:
    """One provider result, and the Instrument it already is — None when the
    ledger does not know it yet."""

    candidate: SecurityCandidate
    instrument_id: int | None


def search(engine: Engine, provider: SecuritySearchProvider, query: str) -> list[FoundCandidate]:
    """The provider's candidates for the query, each marked with the
    Instrument it resolves to — via the identifier history, so a security
    known under a superseded ISIN is still recognised."""
    return [
        FoundCandidate(candidate=candidate, instrument_id=_present(engine, candidate.isin))
        for candidate in provider.search(query)
    ]


def _present(engine: Engine, isin: str) -> int | None:
    matches = [
        row.id for row in instruments.find_by_identifier(engine, isin) if row.family == "security"
    ]
    return matches[0] if matches else None


class IsinChange(Enum):
    """How an identifier change ended."""

    changed = "changed"
    no_such_security = "no_such_security"
    # The ISIN names — or once named — another Instrument.
    taken = "taken"


def change_isin(engine: Engine, instrument_id: int, *, new_isin: str) -> IsinChange:
    """An identifier change (ticket 52): a merger or redomiciliation that
    renames the paper without replacing it. The Instrument stays the row it
    was — every leg and lot recorded under the old ISIN is still its own —
    and its identifier history keeps the superseded ISIN resolving to it.

    An ISIN another Instrument carries, or ever carried, is refused: the
    history resolves an identifier to every Instrument it has named, and two
    answers for one ISIN would let an import land on the wrong one."""
    instrument = instruments.get(engine, instrument_id)
    if instrument is None or instrument.family != "security":
        return IsinChange.no_such_security
    if instrument.isin == new_isin:
        return IsinChange.changed
    if any(row.id != instrument_id for row in instruments.find_by_identifier(engine, new_isin)):
        return IsinChange.taken
    if not instruments.change_isin(engine, instrument_id, new_isin=new_isin):
        return IsinChange.taken
    return IsinChange.changed

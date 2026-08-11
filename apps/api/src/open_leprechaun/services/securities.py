"""Adding a security by search (ticket 44): the provider's candidates set
against the ledger, so a result that is already an Instrument says so instead
of inviting a duplicate."""

from dataclasses import dataclass

from sqlalchemy import Engine

from open_leprechaun.ports.security_search import SecurityCandidate, SecuritySearchProvider
from open_leprechaun.repositories import instruments
from open_leprechaun.repositories.instruments import FUND_TYPES

__all__ = ["FUND_TYPES", "FoundCandidate", "search"]


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

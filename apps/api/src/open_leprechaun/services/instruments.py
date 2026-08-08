"""What the application knows about Instruments beyond storage: the overview
that lets a reader tell two same-symbol rows apart, and the numéraire rule the
tax tickets read — whether moving an Instrument is itself a disposal."""

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import Engine

from open_leprechaun.repositories import instruments


class CarriesNumeraireFlag(Protocol):
    """Anything that says whether it is the numéraire — a repository row or an
    overview alike."""

    @property
    def is_numeraire(self) -> bool: ...


def movement_is_disposal(instrument: CarriesNumeraireFlag) -> bool:
    """Whether moving this Instrument is itself a taxable disposal (ADR-0011).

    The numéraire is the one exception: every taxable figure is expressed in
    it, so its own movement creates no taxable event. The answer comes from
    the designation in the data — never from a symbol comparison — so another
    jurisdiction's numéraire is configuration, not a code change.
    """
    return not instrument.is_numeraire


@dataclass(frozen=True)
class Listing:
    venue: str
    quote_currency: str


@dataclass(frozen=True)
class InstrumentOverview:
    id: int
    family: str
    type: str
    symbol: str
    name: str
    chain: str | None
    contract_address: str | None
    isin: str | None
    is_numeraire: bool
    listings: tuple[Listing, ...]


def overview(engine: Engine) -> list[InstrumentOverview]:
    listings_of: dict[int, list[Listing]] = {}
    for row in instruments.list_listings(engine):
        listings_of.setdefault(row.instrument_id, []).append(
            Listing(venue=row.venue, quote_currency=row.quote_currency)
        )
    return [
        InstrumentOverview(
            id=row.id,
            family=row.family,
            type=row.type,
            symbol=row.symbol,
            name=row.name,
            chain=row.chain,
            contract_address=row.contract_address,
            isin=row.isin,
            is_numeraire=row.is_numeraire,
            listings=tuple(listings_of.get(row.id, [])),
        )
        for row in instruments.list_instruments(engine)
    ]

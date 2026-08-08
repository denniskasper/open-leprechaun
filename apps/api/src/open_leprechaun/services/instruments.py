"""The Instruments overview: every Instrument with its identity attributes
and its Listings, so a reader can tell two same-symbol rows apart."""

from dataclasses import dataclass

from sqlalchemy import Engine

from open_leprechaun.repositories import instruments


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
            listings=tuple(listings_of.get(row.id, [])),
        )
        for row in instruments.list_instruments(engine)
    ]

from fastapi import APIRouter
from pydantic import BaseModel

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.services.instruments import InstrumentOverview, overview

router = APIRouter(tags=["instruments"])


class ListingResponse(BaseModel):
    venue: str
    quote_currency: str


class InstrumentResponse(BaseModel):
    id: int
    family: str
    type: str
    symbol: str
    name: str
    chain: str | None
    contract_address: str | None
    isin: str | None
    is_numeraire: bool
    listings: list[ListingResponse]

    @classmethod
    def of(cls, instrument: InstrumentOverview) -> InstrumentResponse:
        return cls(
            id=instrument.id,
            family=instrument.family,
            type=instrument.type,
            symbol=instrument.symbol,
            name=instrument.name,
            chain=instrument.chain,
            contract_address=instrument.contract_address,
            isin=instrument.isin,
            is_numeraire=instrument.is_numeraire,
            listings=[
                ListingResponse(venue=listing.venue, quote_currency=listing.quote_currency)
                for listing in instrument.listings
            ],
        )


@router.get(
    "/instruments",
    summary="Every Instrument with its identity attributes and Listings",
    response_model=list[InstrumentResponse],
)
def list_instruments(admin: AdminDep, engine: EngineDep) -> list[InstrumentResponse]:
    return [InstrumentResponse.of(instrument) for instrument in overview(engine)]

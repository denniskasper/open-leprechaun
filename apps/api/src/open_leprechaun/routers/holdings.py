from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime, BaseModel, PlainSerializer

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.rates import ReferenceRateSourceDep
from open_leprechaun.services import holdings
from open_leprechaun.services.holdings import Position, RateUnavailableError

router = APIRouter(tags=["holdings"])

# Fixed-point on the way out, as everywhere: a quantity or an EUR figure is
# answered as a decimal string, never a float.
Fixed = Annotated[Decimal, PlainSerializer(lambda value: format(value, "f"), return_type=str)]


class PositionResponse(BaseModel):
    instrument_id: int
    symbol: str
    name: str
    family: str
    type: str
    chain: str | None
    contract_address: str | None
    isin: str | None
    is_numeraire: bool
    account_id: int
    account_name: str
    access_software: str | None
    platform_name: str
    platform_kind: str
    quantity: Fixed
    # Why a position is excluded from totals; None means it counts.
    marker: Literal["dangerous", "ignored", "unacknowledged", "unpriced"] | None
    basis_eur: Fixed | None
    # Why the basis cannot be stated while the position still counts.
    basis_gap: Literal["awaiting_valuation", "unvouched"] | None
    average_cost_eur: Fixed | None
    value_eur: Fixed | None
    unrealised_eur: Fixed | None
    price_source: str | None
    price_as_of: AwareDatetime | None
    rate_date: date | None

    @classmethod
    def of(cls, position: Position) -> PositionResponse:
        return cls(**vars(position))


class HoldingsResponse(BaseModel):
    positions: list[PositionResponse]


class DisplayRateResponse(BaseModel):
    currency: str
    # Units of currency per one euro, as published.
    rate: Fixed
    rate_date: date


@router.get(
    "/holdings",
    summary="Everything held — crypto and cash — with cost basis from the Tax Lots"
    " and values from the store, in EUR",
    response_model=HoldingsResponse,
)
def list_holdings(admin: AdminDep, engine: EngineDep) -> HoldingsResponse:
    return HoldingsResponse(
        positions=[PositionResponse.of(position) for position in holdings.portfolio(engine)]
    )


@router.get(
    "/holdings/display-rate/{currency}",
    summary="The latest reference rate for a DisplayCurrency — presentation only,"
    " never a tax figure",
    response_model=DisplayRateResponse,
)
def get_display_rate(
    currency: str, admin: AdminDep, engine: EngineDep, source: ReferenceRateSourceDep
) -> DisplayRateResponse:
    try:
        rate = holdings.display_rate(engine, source, currency=currency.upper())
    except RateUnavailableError as unavailable:
        raise HTTPException(status_code=404, detail=str(unavailable)) from unavailable
    return DisplayRateResponse(currency=currency.upper(), rate=rate.rate, rate_date=rate.rate_date)

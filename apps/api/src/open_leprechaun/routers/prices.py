from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime, BaseModel, PlainSerializer

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.market_data import SecurityPricesDep
from open_leprechaun.prices import CryptoPriceChainDep
from open_leprechaun.rates import ReferenceRateSourceDep
from open_leprechaun.repositories import crypto_prices as stored_prices
from open_leprechaun.repositories import security_prices as stored_security_prices
from open_leprechaun.services import crypto_prices, security_prices
from open_leprechaun.services.price_reports import (
    BackfillReport,
    PricedInstrument,
    PriceReport,
    ProviderCondition,
)

router = APIRouter(tags=["prices"])

# Fixed-point on the way out, as everywhere: a price is answered as a decimal
# string, never a float.
PriceEur = Annotated[Decimal, PlainSerializer(lambda price: format(price, "f"), return_type=str)]


class PricedInstrumentResponse(BaseModel):
    instrument_id: int
    symbol: str
    name: str
    # `stale` serves the last known price with its age on display; `unpriced`
    # is the honest admission that nothing has ever priced the Instrument —
    # never a zero.
    status: Literal["fresh", "stale", "unpriced"]
    price_eur: PriceEur | None
    source: str | None
    as_of: AwareDatetime | None

    @classmethod
    def of(cls, entry: PricedInstrument) -> PricedInstrumentResponse:
        return cls(
            instrument_id=entry.instrument_id,
            symbol=entry.symbol,
            name=entry.name,
            status=entry.status,
            price_eur=entry.price_eur,
            source=entry.source,
            as_of=entry.as_of,
        )


class ProviderConditionResponse(BaseModel):
    provider: str
    condition: Literal["rate_limited", "outage"]

    @classmethod
    def of(cls, condition: ProviderCondition) -> ProviderConditionResponse:
        return cls(provider=condition.provider, condition=condition.condition)


class PriceReportResponse(BaseModel):
    prices: list[PricedInstrumentResponse]
    conditions: list[ProviderConditionResponse]

    @classmethod
    def of(cls, report: PriceReport) -> PriceReportResponse:
        return cls(
            prices=[PricedInstrumentResponse.of(entry) for entry in report.prices],
            conditions=[ProviderConditionResponse.of(c) for c in report.conditions],
        )


class BackfillRequest(BaseModel):
    start: date
    end: date


class BackfillResponse(BaseModel):
    stored: int
    source: str | None
    conditions: list[ProviderConditionResponse]

    @classmethod
    def of(cls, report: BackfillReport) -> BackfillResponse:
        return cls(
            stored=report.stored,
            source=report.source,
            conditions=[ProviderConditionResponse.of(c) for c in report.conditions],
        )


class DailyCloseResponse(BaseModel):
    close_date: date
    price_eur: PriceEur
    source: str


@router.get(
    "/prices/crypto",
    summary="Price every crypto Instrument through the provider chain,"
    " serving the stored price clearly labelled stale where every provider fails",
    response_model=PriceReportResponse,
)
def crypto_prices_report(
    admin: AdminDep,
    engine: EngineDep,
    chain: CryptoPriceChainDep,
    rate_source: ReferenceRateSourceDep,
) -> PriceReportResponse:
    return PriceReportResponse.of(crypto_prices.refresh_prices(engine, chain, rate_source))


@router.post(
    "/prices/crypto/{instrument_id}/closes/backfill",
    summary="Populate a chosen range of daily closes from the provider chain",
    response_model=BackfillResponse,
)
def backfill_closes(
    instrument_id: int,
    request: BackfillRequest,
    admin: AdminDep,
    engine: EngineDep,
    chain: CryptoPriceChainDep,
    rate_source: ReferenceRateSourceDep,
) -> BackfillResponse:
    if request.start > request.end:
        raise HTTPException(status_code=422, detail="The range ends before it starts.")
    report = crypto_prices.backfill_daily_closes(
        engine,
        chain,
        rate_source,
        instrument_id=instrument_id,
        start=request.start,
        end=request.end,
    )
    if report is None:
        raise HTTPException(
            status_code=404, detail="No such crypto Instrument priceable by the chain."
        )
    return BackfillResponse.of(report)


@router.get(
    "/prices/crypto/{instrument_id}/closes",
    summary="The stored daily closes for one Instrument, with source attribution",
    response_model=list[DailyCloseResponse],
)
def list_closes(
    instrument_id: int,
    start: date,
    end: date,
    admin: AdminDep,
    engine: EngineDep,
) -> list[DailyCloseResponse]:
    return [
        DailyCloseResponse(close_date=row.close_date, price_eur=row.price_eur, source=row.source)
        for row in stored_prices.daily_closes(engine, instrument_id, start=start, end=end)
    ]


@router.get(
    "/prices/securities",
    summary="Price every security through its price-source Listing,"
    " serving the stored price clearly labelled stale where the provider fails",
    response_model=PriceReportResponse,
)
def security_prices_report(
    admin: AdminDep,
    engine: EngineDep,
    provider: SecurityPricesDep,
    rate_source: ReferenceRateSourceDep,
) -> PriceReportResponse:
    return PriceReportResponse.of(security_prices.refresh_prices(engine, provider, rate_source))


@router.post(
    "/prices/securities/{instrument_id}/closes/backfill",
    summary="Populate a chosen range of daily closes through the price-source Listing",
    response_model=BackfillResponse,
)
def backfill_security_closes(
    instrument_id: int,
    request: BackfillRequest,
    admin: AdminDep,
    engine: EngineDep,
    provider: SecurityPricesDep,
    rate_source: ReferenceRateSourceDep,
) -> BackfillResponse:
    if request.start > request.end:
        raise HTTPException(status_code=422, detail="The range ends before it starts.")
    report = security_prices.backfill_daily_closes(
        engine,
        provider,
        rate_source,
        instrument_id=instrument_id,
        start=request.start,
        end=request.end,
    )
    if report is None:
        raise HTTPException(
            status_code=404, detail="No priceable security names this Listing as its price source."
        )
    return BackfillResponse.of(report)


@router.get(
    "/prices/securities/{instrument_id}/closes",
    summary="The stored daily closes for one security, with source attribution",
    response_model=list[DailyCloseResponse],
)
def list_security_closes(
    instrument_id: int,
    start: date,
    end: date,
    admin: AdminDep,
    engine: EngineDep,
) -> list[DailyCloseResponse]:
    return [
        DailyCloseResponse(close_date=row.close_date, price_eur=row.price_eur, source=row.source)
        for row in stored_security_prices.daily_closes(engine, instrument_id, start=start, end=end)
    ]

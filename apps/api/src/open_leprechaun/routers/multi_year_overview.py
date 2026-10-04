from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, PlainSerializer

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.rates import ReferenceRateSourceDep
from open_leprechaun.routers.reports import BlockerResponse
from open_leprechaun.services import fx, multi_year_overview
from open_leprechaun.services.multi_year_overview import (
    CapitalIncomeYear,
    OverviewYear,
    RegimeYear,
)
from open_leprechaun.services.section20 import CarriedCategory, CarryforwardLayer

router = APIRouter(tags=["reports"])

# Fixed-point on the way out, as everywhere: an EUR figure is answered as a
# decimal string, never a float.
Fixed = Annotated[Decimal, PlainSerializer(lambda value: format(value, "f"), return_type=str)]


class RegimeYearResponse(BaseModel):
    """One regime's row for one Tax Year. `tax_eur` is null where the rate
    is the Admin's personal one — the taxable amount is the answer there."""

    gross_eur: Fixed
    offsets_eur: Fixed
    allowance_limit_eur: Fixed
    allowance_eur: Fixed
    taxable_eur: Fixed
    tax_eur: Fixed | None

    @classmethod
    def of(cls, row: RegimeYear | None) -> RegimeYearResponse | None:
        return cls(**vars(row)) if row is not None else None


class CarryforwardLayerResponse(BaseModel):
    """One slice of a loss carryforward: the year that established it, and
    whether it was entered from an assessment predating the ledger rather
    than produced by a year the ledger holds."""

    origin_year: int
    amount_eur: Fixed
    opening: bool

    @classmethod
    def of(cls, layer: CarryforwardLayer) -> CarryforwardLayerResponse:
        return cls(**vars(layer))


class CategoryCarryforwardResponse(BaseModel):
    """One Verlustverrechnungstopf's carryforward through the year: in,
    consumed (each slice naming its origin year), produced, and out — each
    side's layers beside their total."""

    category: str
    carryforward_in_eur: Fixed
    carryforward_in: list[CarryforwardLayerResponse]
    consumed_eur: Fixed
    consumed: list[CarryforwardLayerResponse]
    produced_eur: Fixed
    carryforward_out_eur: Fixed
    carryforward_out: list[CarryforwardLayerResponse]

    @classmethod
    def of(cls, pot: CarriedCategory) -> CategoryCarryforwardResponse:
        return cls(
            category=pot.category,
            carryforward_in_eur=_total(pot.carryforward_in),
            carryforward_in=_layers(pot.carryforward_in),
            consumed_eur=_total(pot.consumed),
            consumed=_layers(pot.consumed),
            produced_eur=pot.produced_eur,
            carryforward_out_eur=_total(pot.carryforward_out),
            carryforward_out=_layers(pot.carryforward_out),
        )


def _layers(layers: tuple[CarryforwardLayer, ...]) -> list[CarryforwardLayerResponse]:
    return [CarryforwardLayerResponse.of(layer) for layer in layers]


def _total(layers: tuple[CarryforwardLayer, ...]) -> Decimal:
    return sum((layer.amount_eur for layer in layers), Decimal(0))


class CapitalIncomeYearResponse(RegimeYearResponse):
    categories: list[CategoryCarryforwardResponse]

    @classmethod
    def of(cls, row: CapitalIncomeYear | None) -> CapitalIncomeYearResponse | None:
        if row is None:
            return None
        figures = {name: value for name, value in vars(row).items() if name != "categories"}
        return cls(
            **figures, categories=[CategoryCarryforwardResponse.of(pot) for pot in row.categories]
        )


class OverviewYearResponse(BaseModel):
    """One Tax Year across the regimes — a regime is null where its engine
    could not state the year, and `blockers` says what stands in the way."""

    year: int
    blockers: list[BlockerResponse]
    private_sales: RegimeYearResponse | None
    other_income: RegimeYearResponse | None
    capital_income: CapitalIncomeYearResponse | None

    @classmethod
    def of(cls, year: OverviewYear) -> OverviewYearResponse:
        return cls(
            year=year.year,
            blockers=[BlockerResponse(**vars(blocker)) for blocker in year.blockers],
            private_sales=RegimeYearResponse.of(year.private_sales),
            other_income=RegimeYearResponse.of(year.other_income),
            capital_income=CapitalIncomeYearResponse.of(year.capital_income),
        )


class MultiYearOverviewResponse(BaseModel):
    years: list[OverviewYearResponse]


@router.get(
    "/multi-year-overview",
    summary="Every Tax Year across the regimes, as the ledger stands now",
    response_model=MultiYearOverviewResponse,
)
def get_multi_year_overview(
    admin: AdminDep, engine: EngineDep, source: ReferenceRateSourceDep
) -> MultiYearOverviewResponse:
    years = multi_year_overview.overview(engine, source, today=fx.event_date(datetime.now(UTC)))
    return MultiYearOverviewResponse(years=[OverviewYearResponse.of(year) for year in years])

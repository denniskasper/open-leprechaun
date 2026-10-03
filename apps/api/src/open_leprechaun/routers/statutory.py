from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, BeforeValidator, Field, PlainSerializer, StringConstraints

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.repositories import capital_income, fund_redemption_values, statutory
from open_leprechaun.routers.fixed_point import decimal_text_only
from open_leprechaun.services.statutory import (
    FIRST_YEAR,
    KEYS,
    LAST_YEAR,
    StatutoryOverview,
    entry_defect,
    overview,
)

router = APIRouter(tags=["statutory"])

# The statutory vocabulary; the service holds each key's unit and whether a
# year requires it, and a test holds the two lists to each other.
StatutoryKey = Literal[
    "private_sale_exemption_limit",
    "other_income_exemption_limit",
    "saver_allowance_single",
    "saver_allowance_joint",
    "flat_rate",
    "solidarity_surcharge_rate",
    "church_tax_rate_bavaria_bw",
    "church_tax_rate_other_laender",
    "advance_lump_sum_base_rate",
    "advance_lump_sum_factor",
    "loss_cap_aktien",
    "loss_cap_sonstige",
    "loss_cap_termingeschaefte",
    "opening_carryforward_aktien",
    "opening_carryforward_sonstige",
    "opening_carryforward_termingeschaefte",
    "partial_exemption_aktienfonds",
    "partial_exemption_mischfonds",
    "partial_exemption_immobilienfonds",
    "partial_exemption_auslands_immobilienfonds",
    "partial_exemption_sonstige",
]

# The elections that select which per-year values apply; the service holds
# the selection, and a test holds the vocabularies to each other.
FilingStatus = Literal["single", "joint"]
ChurchTax = Literal["none", "bavaria_bw", "other_laender"]


# Fixed-point end to end, including in JSON — like every monetary value and
# rate in this API. Non-negative; the unit-aware upper bound for rates is the
# service's judgement.
StatutoryDecimal = Annotated[
    Decimal,
    BeforeValidator(decimal_text_only),
    Field(ge=0, allow_inf_nan=False),
    PlainSerializer(lambda value: format(value, "f"), return_type=str),
]

# A citation is not optional and blank cannot pose as one.
Source = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class KeyResponse(BaseModel):
    key: StatutoryKey
    unit: Literal["eur", "rate"]
    required: bool


class ValueResponse(BaseModel):
    key: StatutoryKey
    value: StatutoryDecimal
    source: str


class YearResponse(BaseModel):
    year: int
    values: list[ValueResponse]
    # The required keys this year still has no value for.
    missing: list[StatutoryKey]


class StatutoryResponse(BaseModel):
    filing_status: FilingStatus
    church_tax: ChurchTax
    keys: list[KeyResponse]
    years: list[YearResponse]

    @classmethod
    def of(cls, store: StatutoryOverview) -> StatutoryResponse:
        return cls(
            filing_status=store.filing_status,
            church_tax=store.church_tax,
            keys=[
                KeyResponse(key=key, unit=definition.unit, required=definition.required)
                for key, definition in KEYS.items()
            ],
            years=[
                YearResponse(
                    year=year.year,
                    values=[
                        ValueResponse(key=value.key, value=value.value, source=value.source)
                        for value in year.values
                    ],
                    missing=list(year.missing),
                )
                for year in store.years
            ],
        )


class EnterValueRequest(BaseModel):
    value: StatutoryDecimal
    source: Source


class ElectionRequest(BaseModel):
    filing_status: FilingStatus
    church_tax: ChurchTax


@router.get(
    "/statutory",
    summary="The statutory configuration: elections, vocabulary, per-year values and gaps",
    response_model=StatutoryResponse,
)
def read_statutory(admin: AdminDep, engine: EngineDep) -> StatutoryResponse:
    return StatutoryResponse.of(overview(engine))


@router.put(
    "/statutory/values/{year}/{key}",
    summary="Enter or correct one per-year statutory value with its source",
    status_code=204,
)
def enter_value(
    year: int, key: StatutoryKey, request: EnterValueRequest, admin: AdminDep, engine: EngineDep
) -> None:
    defect = entry_defect(year=year, key=key, value=request.value)
    if defect is not None:
        raise HTTPException(status_code=422, detail=defect)
    statutory.upsert_value(engine, year=year, key=key, value=request.value, source=request.source)


@router.delete(
    "/statutory/values/{year}/{key}",
    summary="Unset one per-year statutory value",
    status_code=204,
)
def unset_value(year: int, key: StatutoryKey, admin: AdminDep, engine: EngineDep) -> None:
    if not statutory.delete_value(engine, year=year, key=key):
        raise HTTPException(status_code=404, detail="No such value is set.")


@router.put(
    "/statutory/election",
    summary="Choose filing status and church-tax election",
    status_code=204,
)
def choose_election(request: ElectionRequest, admin: AdminDep, engine: EngineDep) -> None:
    statutory.set_election(
        engine, filing_status=request.filing_status, church_tax=request.church_tax
    )


# ISO 3166-1 alpha-2, the shape the schema holds a source country to.
Country = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]

# A treaty limit is a rate: a fraction of one, never a percentage — the upper
# bound is judged in the route, so the Admin reads a sentence, not a schema.
TreatyRate = Annotated[
    Decimal,
    BeforeValidator(decimal_text_only),
    Field(ge=0, allow_inf_nan=False),
    PlainSerializer(lambda value: format(value, "f"), return_type=str),
]


class TreatyLimitRequest(BaseModel):
    rate: TreatyRate
    # The treaty article the rate was taken from — a limit is never entered
    # uncited.
    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class TreatyLimitResponse(BaseModel):
    country: str
    rate: TreatyRate
    source: str


@router.get(
    "/treaty-limits",
    summary="The treaty limit on Quellensteuer per source country",
    response_model=list[TreatyLimitResponse],
)
def list_treaty_limits(admin: AdminDep, engine: EngineDep) -> list[TreatyLimitResponse]:
    """The share of a gross dividend each double-taxation treaty lets the
    source country keep (ticket 47): Quellensteuer is creditable up to it,
    and reported as reclaimable from that country beyond it."""
    return [
        TreatyLimitResponse(country=row.country, rate=row.rate, source=row.source)
        for row in capital_income.list_treaty_limits(engine)
    ]


@router.put(
    "/treaty-limits/{country}",
    summary="Enter or correct one source country's treaty limit",
    status_code=204,
)
def put_treaty_limit(
    country: Country, request: TreatyLimitRequest, admin: AdminDep, engine: EngineDep
) -> None:
    if request.rate > 1:
        raise HTTPException(
            status_code=422, detail="A rate is a fraction of one — 15 % is entered as 0.15."
        )
    capital_income.upsert_treaty_limit(
        engine, country=country, rate=request.rate, source=request.source
    )


@router.delete(
    "/treaty-limits/{country}",
    summary="Remove one source country's treaty limit",
    status_code=204,
)
def delete_treaty_limit(country: Country, admin: AdminDep, engine: EngineDep) -> None:
    if not capital_income.delete_treaty_limit(engine, country):
        raise HTTPException(status_code=404, detail="No treaty limit is entered for that country.")


# A redemption price or a distribution per unit, in EUR — fixed-point end to
# end like every amount in this API, and never negative.
UnitAmount = Annotated[
    Decimal,
    BeforeValidator(decimal_text_only),
    Field(ge=0, allow_inf_nan=False),
    PlainSerializer(lambda value: format(value, "f"), return_type=str),
]


class FundResponse(BaseModel):
    instrument_id: int
    symbol: str
    name: str
    isin: str | None


class FundRedemptionValueRequest(BaseModel):
    start_of_year_eur: UnitAmount
    end_of_year_eur: UnitAmount
    # Stated, never assumed: a pure accumulator's distributions are zero
    # because the Admin says so.
    distributions_eur: UnitAmount
    # Where the fund's figures were taken from — never entered uncited.
    source: Source


class FundRedemptionValueResponse(BaseModel):
    instrument_id: int
    year: int
    start_of_year_eur: UnitAmount
    end_of_year_eur: UnitAmount
    distributions_eur: UnitAmount
    source: str


class FundRedemptionValuesResponse(BaseModel):
    funds: list[FundResponse]
    values: list[FundRedemptionValueResponse]


@router.get(
    "/fund-redemption-values",
    summary="Each fund's entered redemption prices and distributions per year",
    response_model=FundRedemptionValuesResponse,
)
def list_fund_redemption_values(admin: AdminDep, engine: EngineDep) -> FundRedemptionValuesResponse:
    """What the Vorabpauschale (ticket 53) reads per fund and year: the first
    and last redemption price of the calendar year and the distributions
    within it, per unit in EUR, each with its source — beside the funds a
    row can be entered for."""
    return FundRedemptionValuesResponse(
        funds=[
            FundResponse(instrument_id=row.id, symbol=row.symbol, name=row.name, isin=row.isin)
            for row in fund_redemption_values.list_funds(engine)
        ],
        values=[
            FundRedemptionValueResponse(
                instrument_id=row.instrument_id,
                year=row.year,
                start_of_year_eur=row.start_of_year_eur,
                end_of_year_eur=row.end_of_year_eur,
                distributions_eur=row.distributions_eur,
                source=row.source,
            )
            for row in fund_redemption_values.list_values(engine)
        ],
    )


@router.put(
    "/fund-redemption-values/{instrument_id}/{year}",
    summary="Enter or correct one fund's redemption prices and distributions for a year",
    status_code=204,
)
def put_fund_redemption_value(
    instrument_id: int,
    year: int,
    request: FundRedemptionValueRequest,
    admin: AdminDep,
    engine: EngineDep,
) -> None:
    if not FIRST_YEAR <= year <= LAST_YEAR:
        raise HTTPException(
            status_code=422,
            detail=f"Redemption values cover {FIRST_YEAR} through {LAST_YEAR}.",
        )
    if not fund_redemption_values.is_fund(engine, instrument_id):
        raise HTTPException(status_code=404, detail="No such fund.")
    fund_redemption_values.upsert_value(
        engine,
        instrument_id=instrument_id,
        year=year,
        start_of_year_eur=request.start_of_year_eur,
        end_of_year_eur=request.end_of_year_eur,
        distributions_eur=request.distributions_eur,
        source=request.source,
    )


@router.delete(
    "/fund-redemption-values/{instrument_id}/{year}",
    summary="Unset one fund's redemption values for a year",
    status_code=204,
)
def delete_fund_redemption_value(
    instrument_id: int, year: int, admin: AdminDep, engine: EngineDep
) -> None:
    if not fund_redemption_values.delete_value(engine, instrument_id=instrument_id, year=year):
        raise HTTPException(
            status_code=404, detail="No redemption values are entered for that fund and year."
        )

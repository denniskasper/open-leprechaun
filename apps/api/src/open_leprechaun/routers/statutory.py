from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, BeforeValidator, Field, PlainSerializer, StringConstraints

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.repositories import statutory
from open_leprechaun.services.statutory import (
    KEYS,
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
    "loss_cap_aktien",
    "loss_cap_sonstige",
    "loss_cap_termingeschaefte",
    "opening_carryforward_aktien",
    "opening_carryforward_sonstige",
    "opening_carryforward_termingeschaefte",
]

# The elections that select which per-year values apply; the service holds
# the selection, and a test holds the vocabularies to each other.
FilingStatus = Literal["single", "joint"]
ChurchTax = Literal["none", "bavaria_bw", "other_laender"]


def _decimal_text_only(value: object) -> object:
    """Refuse a JSON number where a statutory value belongs: it has been
    through — or is one parse away from — a binary float, so only a string
    states the digits exactly. Decimals pass untouched; responses are built
    from them."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        raise ValueError(
            "a statutory value crosses JSON as a fixed-point decimal string, not a number"
        )
    return value


# Fixed-point end to end, including in JSON — like every monetary value and
# rate in this API. Non-negative; the unit-aware upper bound for rates is the
# service's judgement.
StatutoryDecimal = Annotated[
    Decimal,
    BeforeValidator(_decimal_text_only),
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

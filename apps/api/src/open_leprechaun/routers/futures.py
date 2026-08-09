from decimal import Decimal
from typing import Annotated, Literal, Self

from fastapi import APIRouter, HTTPException
from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    Field,
    PlainSerializer,
    model_validator,
)

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.repositories.futures import FuturesPosition, Refusal
from open_leprechaun.services import futures
from open_leprechaun.services.futures import (
    FundingOverview,
    FuturesOverview,
    IssueOverview,
    PositionOverview,
)

router = APIRouter(tags=["futures"])

PositionSide = Literal["long", "short"]

# Whether the derivation stated the position or the Admin entered it — the
# one difference the shared model keeps (ADR-0009).
Origin = Literal["manual", "derived"]


def _decimal_text_only(value: object) -> object:
    """Refuse a JSON number where an amount belongs: it has been through —
    or is one parse away from — a binary float, so only a string states the
    digits exactly. Decimals pass untouched; responses are built from them."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        raise ValueError("an amount crosses JSON as a fixed-point decimal string, not a number")
    return value


# Fixed-point end to end, as in the transaction ledger: parsed exactly from a
# decimal string, answered as one, never a float in either direction.
Quantity = Annotated[
    Decimal,
    BeforeValidator(_decimal_text_only),
    Field(gt=0, allow_inf_nan=False),
    PlainSerializer(lambda quantity: format(quantity, "f"), return_type=str),
]

# A settlement-currency amount that may honestly carry either sign: a losing
# position's realised result, a maker rebate among the fees, funding paid or
# received.
SignedAmount = Annotated[
    Decimal,
    BeforeValidator(_decimal_text_only),
    Field(allow_inf_nan=False),
    PlainSerializer(lambda amount: format(amount, "f"), return_type=str),
]


class ManualPositionRequest(BaseModel):
    """A position as the Admin declares it — the same shape the derivation
    stores, because only the origin differs."""

    account_id: int
    symbol: str
    side: PositionSide
    quantity: Quantity
    settlement_instrument_id: int
    opened_at: AwareDatetime
    # Absent means open: a position that counts in no Tax Year.
    closed_at: AwareDatetime | None = None
    realized: SignedAmount
    fees: SignedAmount

    @model_validator(mode="after")
    def _closes_after_opening(self) -> Self:
        if self.closed_at is not None and self.closed_at < self.opened_at:
            raise ValueError("A position cannot close before it opened.")
        return self


class RegisteredResponse(BaseModel):
    id: int


class PositionResponse(BaseModel):
    id: int
    origin: Origin
    source: str | None
    account_id: int
    symbol: str
    side: PositionSide
    quantity: Quantity
    settlement_instrument_id: int
    opened_at: AwareDatetime
    closed_at: AwareDatetime | None
    # Separately stored and summed (ticket 28): each stays traceable, and
    # `net` is the figure a close emits into the Termingeschäfte pot.
    realized: SignedAmount
    fees: SignedAmount
    funding: SignedAmount
    net: SignedAmount

    @classmethod
    def of(cls, position: PositionOverview) -> PositionResponse:
        return cls(**vars(position))


class UnattributableFundingResponse(BaseModel):
    """A payment no single position could claim — surfaced, never dropped."""

    id: int
    source: str
    account_id: int
    symbol: str
    amount: SignedAmount
    settlement_instrument_id: int
    occurred_at: AwareDatetime
    position_side: PositionSide | None

    @classmethod
    def of(cls, payment: FundingOverview) -> UnattributableFundingResponse:
        return cls(**vars(payment))


class DerivationIssueResponse(BaseModel):
    """A fill stream flagged for manual handling rather than guessed
    (ADR-0009)."""

    id: int
    source: str
    account_id: int
    symbol: str
    position_side: PositionSide | None
    reason: str

    @classmethod
    def of(cls, issue: IssueOverview) -> DerivationIssueResponse:
        return cls(**vars(issue))


class FuturesResponse(BaseModel):
    positions: list[PositionResponse]
    unattributable_funding: list[UnattributableFundingResponse]
    derivation_issues: list[DerivationIssueResponse]

    @classmethod
    def of(cls, overview: FuturesOverview) -> FuturesResponse:
        return cls(
            positions=[PositionResponse.of(position) for position in overview.positions],
            unattributable_funding=[
                UnattributableFundingResponse.of(payment)
                for payment in overview.unattributable_funding
            ],
            derivation_issues=[
                DerivationIssueResponse.of(issue) for issue in overview.derivation_issues
            ],
        )


@router.get(
    "/futures",
    summary="Every futures position with its net figure, plus what stands unresolved",
    response_model=FuturesResponse,
)
def futures_overview(admin: AdminDep, engine: EngineDep) -> FuturesResponse:
    return FuturesResponse.of(futures.overview(engine))


@router.post(
    "/futures/positions",
    summary="Enter a position manually, in the same model derived ones use",
    status_code=201,
    response_model=RegisteredResponse,
)
def record_position(
    request: ManualPositionRequest, admin: AdminDep, engine: EngineDep
) -> RegisteredResponse:
    created = futures.record_manual_position(engine, _manual(request))
    if isinstance(created, Refusal):
        raise HTTPException(status_code=404, detail=_REFUSED[created])
    return RegisteredResponse(id=created)


@router.put(
    "/futures/positions/{position_id}",
    summary="Revise a manually entered position wholesale",
    status_code=204,
)
def revise_position(
    position_id: int, request: ManualPositionRequest, admin: AdminDep, engine: EngineDep
) -> None:
    refused = futures.replace_manual_position(engine, position_id, _manual(request))
    if refused is not None:
        raise HTTPException(status_code=_STATUS[refused], detail=_REFUSED[refused])


@router.delete(
    "/futures/positions/{position_id}",
    summary="Remove a manually entered position",
    status_code=204,
)
def remove_position(position_id: int, admin: AdminDep, engine: EngineDep) -> None:
    refused = futures.delete_manual_position(engine, position_id)
    if refused is not None:
        raise HTTPException(status_code=_STATUS[refused], detail=_REFUSED[refused])


_REFUSED = {
    Refusal.no_such_account: "No such Account.",
    Refusal.no_such_instrument: "No such Instrument.",
    Refusal.no_such_position: "No such position.",
    Refusal.not_manual: (
        "This position was derived from fills — correct the fills, not the position."
    ),
}

_STATUS = {
    Refusal.no_such_account: 404,
    Refusal.no_such_instrument: 404,
    Refusal.no_such_position: 404,
    Refusal.not_manual: 409,
}


def _manual(request: ManualPositionRequest) -> FuturesPosition:
    return FuturesPosition(
        account_id=request.account_id,
        symbol=request.symbol,
        side=request.side,
        quantity=request.quantity,
        settlement_instrument_id=request.settlement_instrument_id,
        opened_at=request.opened_at,
        closed_at=request.closed_at,
        realized=request.realized,
        fees=request.fees,
    )

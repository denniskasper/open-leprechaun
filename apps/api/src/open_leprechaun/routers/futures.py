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

from open_leprechaun.adapters import VenueAdaptersDep
from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.repositories.futures import FuturesPosition, Refusal
from open_leprechaun.routers.fixed_point import decimal_text_only
from open_leprechaun.services import futures, futures_live
from open_leprechaun.services.futures import (
    FundingOverview,
    FuturesOverview,
    IssueOverview,
    PositionOverview,
)
from open_leprechaun.settings import SettingsDep

router = APIRouter(tags=["futures"])

PositionSide = Literal["long", "short"]

# Whether the derivation stated the position or the Admin entered it — the
# one difference the shared model keeps (ADR-0009).
Origin = Literal["manual", "derived"]


# Fixed-point end to end, as in the transaction ledger: parsed exactly from a
# decimal string, answered as one, never a float in either direction.
Quantity = Annotated[
    Decimal,
    BeforeValidator(decimal_text_only),
    Field(gt=0, allow_inf_nan=False),
    PlainSerializer(lambda quantity: format(quantity, "f"), return_type=str),
]

# A settlement-currency amount that may honestly carry either sign: a losing
# position's realised result, a maker rebate among the fees, funding paid or
# received.
SignedAmount = Annotated[
    Decimal,
    BeforeValidator(decimal_text_only),
    Field(allow_inf_nan=False),
    PlainSerializer(lambda amount: format(amount, "f"), return_type=str),
]


# A figure on the way out only — a price, a ratio, a venue's own statement:
# fixed-point as everywhere, a decimal string and never a float.
Figure = Annotated[Decimal, PlainSerializer(lambda value: format(value, "f"), return_type=str)]


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
    # The bot aggregate whose scope covers this position (ticket 30) — the
    # marker the summary presentation collapses on.
    aggregate_id: int | None
    settlement_symbol: str
    # A closed position's net in EUR by the stored rate of its close day —
    # null while open, and while nothing stored can value it.
    net_eur: Figure | None

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


class LivePositionResponse(BaseModel):
    """One open position as the venue states it right now (CONTEXT.md) —
    every figure the venue's own; one it left unstated is null."""

    symbol: str
    side: PositionSide
    quantity: Figure
    quantity_unit: str | None
    notional_usd: Figure | None
    leverage: Figure | None
    margin_mode: str | None
    entry_price: Figure | None
    mark_price: Figure | None
    liquidation_price: Figure | None
    breakeven_price: Figure | None
    floating_result: Figure | None
    floating_result_ratio: Figure | None
    margin: Figure | None
    margin_ratio: Figure | None
    settlement_symbol: str
    opened_at: AwareDatetime | None
    as_of: AwareDatetime
    # The ledger's open position for the same Account, symbol and side —
    # null where the ledger has no history for it.
    ledger_position_id: int | None


class KindLiveResponse(BaseModel):
    """One Connection's futures kind: its venue's Live Positions, or why
    there are none to show — the venue states none, or it failed."""

    connection_id: int
    connection_label: str
    venue: str
    adapter_kind: str
    account_id: int | None
    supported: bool
    error: str | None
    positions: list[LivePositionResponse]

    @classmethod
    def of(cls, result: futures_live.KindLive) -> KindLiveResponse:
        return cls(
            connection_id=result.connection_id,
            connection_label=result.connection_label,
            venue=result.venue,
            adapter_kind=result.adapter_kind,
            account_id=result.account_id,
            supported=result.supported,
            error=result.error,
            positions=[
                LivePositionResponse(
                    **vars(entry.stated), ledger_position_id=entry.ledger_position_id
                )
                for entry in result.positions
            ],
        )


@router.get(
    "/futures/live",
    summary="What every venue states about its open futures positions right now",
    response_model=list[KindLiveResponse],
)
def live_positions(
    admin: AdminDep, engine: EngineDep, settings: SettingsDep, adapters: VenueAdaptersDep
) -> list[KindLiveResponse]:
    """Asks the venues and stores nothing: a Live Position is shown, never
    an input to derivation or to any tax figure (ADR-0008)."""
    return [KindLiveResponse.of(result) for result in futures_live.live(engine, settings, adapters)]


class FillEventResponse(BaseModel):
    id: int
    external_id: str
    side: Literal["buy", "sell"]
    price: Figure
    size: Figure
    fee: Figure
    realized: Figure | None
    occurred_at: AwareDatetime


class FundingEventResponse(BaseModel):
    id: int
    amount: Figure
    occurred_at: AwareDatetime


class PositionEventsResponse(BaseModel):
    fills: list[FillEventResponse]
    funding: list[FundingEventResponse]


@router.get(
    "/futures/positions/{position_id}/events",
    summary="The fills a position was derived from and the funding attributed to it",
    response_model=PositionEventsResponse,
)
def position_events(position_id: int, admin: AdminDep, engine: EngineDep) -> PositionEventsResponse:
    found = futures.events(engine, position_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such position.")
    return PositionEventsResponse(
        fills=[FillEventResponse(**vars(fill)) for fill in found.fills],
        funding=[FundingEventResponse(**vars(payment)) for payment in found.funding],
    )


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

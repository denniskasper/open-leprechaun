from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    Field,
    PlainSerializer,
    StringConstraints,
)

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.routers.futures import PositionResponse
from open_leprechaun.routers.transactions import TransactionResponse
from open_leprechaun.services import aggregates
from open_leprechaun.services.aggregates import (
    BotConstituents,
    BotSummary,
    DustSweepSummary,
    FillOverview,
    SettlementTotals,
)

router = APIRouter(tags=["aggregates"])

PositionSide = Literal["long", "short"]

# A label is prose for the Admin — the summary line's name; trimmed so blank
# cannot pose as one.
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _decimal_text_only(value: object) -> object:
    """Refuse a JSON number where an amount belongs: it has been through —
    or is one parse away from — a binary float, so only a string states the
    digits exactly. Decimals pass untouched; responses are built from them."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        raise ValueError("an amount crosses JSON as a fixed-point decimal string, not a number")
    return value


# Fixed-point end to end, as everywhere: answered as decimal strings, never
# a float in either direction.
Amount = Annotated[
    Decimal,
    BeforeValidator(_decimal_text_only),
    Field(allow_inf_nan=False),
    PlainSerializer(lambda amount: format(amount, "f"), return_type=str),
]


class RecordBotRequest(BaseModel):
    """A bot aggregate's scope: the fill source it summarises, optionally
    narrowed to one symbol."""

    label: Label
    source: str
    symbol: str | None = None


class RecordDustSweepRequest(BaseModel):
    """A dust sweep over its constituent trades — the Transactions that each
    dispose one dust balance into the received Instrument."""

    label: Label
    transaction_ids: list[int] = Field(min_length=1)


class RegisteredResponse(BaseModel):
    id: int


class SettlementTotalsResponse(BaseModel):
    """One settlement currency's sums over the closed constituents — `net`
    is the very figure their emissions carry into the Termingeschäfte pot."""

    settlement_instrument_id: int
    realized: Amount
    fees: Amount
    funding: Amount
    net: Amount

    @classmethod
    def of(cls, totals: SettlementTotals) -> SettlementTotalsResponse:
        return cls(**vars(totals))


class BotSummaryResponse(BaseModel):
    id: int
    label: str
    source: str
    symbol: str | None
    fill_count: int
    open_positions: int
    closed_positions: int
    closed_totals: list[SettlementTotalsResponse]

    @classmethod
    def of(cls, summary: BotSummary) -> BotSummaryResponse:
        totals = [SettlementTotalsResponse.of(entry) for entry in summary.closed_totals]
        return cls(**{**vars(summary), "closed_totals": totals})


class DustSweepSummaryResponse(BaseModel):
    """One aggregate disposal into the received Instrument — the received
    side stated only while the members still agree on it."""

    id: int
    label: str
    constituent_count: int
    received_account_id: int | None
    received_instrument_id: int | None
    received_quantity: Amount | None
    first_occurred_at: AwareDatetime | None
    last_occurred_at: AwareDatetime | None

    @classmethod
    def of(cls, summary: DustSweepSummary) -> DustSweepSummaryResponse:
        return cls(**vars(summary))


class AggregatesResponse(BaseModel):
    bots: list[BotSummaryResponse]
    dust_sweeps: list[DustSweepSummaryResponse]


class FillResponse(BaseModel):
    """One constituent fill as stored — the immutable record behind a bot's
    summary."""

    id: int
    source: str
    external_id: str
    account_id: int
    symbol: str
    side: Literal["buy", "sell"]
    price: Amount
    size: Amount
    fee: Amount
    settlement_instrument_id: int
    occurred_at: AwareDatetime
    position_side: PositionSide | None
    reduce_only: bool | None
    realized: Amount | None
    inverse: bool | None

    @classmethod
    def of(cls, fill: FillOverview) -> FillResponse:
        return cls(**vars(fill))


class BotDetailResponse(BaseModel):
    kind: Literal["bot"] = "bot"
    summary: BotSummaryResponse
    fills: list[FillResponse]
    positions: list[PositionResponse]


class DustSweepDetailResponse(BaseModel):
    kind: Literal["dust_sweep"] = "dust_sweep"
    summary: DustSweepSummaryResponse
    transactions: list[TransactionResponse]


@router.get(
    "/aggregates",
    summary="Every aggregate as one summary line — figures are sums over constituents",
    response_model=AggregatesResponse,
)
def aggregates_overview(admin: AdminDep, engine: EngineDep) -> AggregatesResponse:
    overview = aggregates.overview(engine)
    return AggregatesResponse(
        bots=[BotSummaryResponse.of(summary) for summary in overview.bots],
        dust_sweeps=[DustSweepSummaryResponse.of(summary) for summary in overview.dust_sweeps],
    )


@router.get(
    "/aggregates/{aggregate_id}",
    summary="One aggregate's constituents, retrievable in full",
    response_model=BotDetailResponse | DustSweepDetailResponse,
)
def aggregate_constituents(
    aggregate_id: int, admin: AdminDep, engine: EngineDep
) -> BotDetailResponse | DustSweepDetailResponse:
    answered = aggregates.constituents(engine, aggregate_id)
    if answered is None:
        raise HTTPException(status_code=404, detail="No such aggregate.")
    if isinstance(answered, BotConstituents):
        return BotDetailResponse(
            summary=BotSummaryResponse.of(answered.summary),
            fills=[FillResponse.of(fill) for fill in answered.fills],
            positions=[PositionResponse.of(position) for position in answered.positions],
        )
    return DustSweepDetailResponse(
        summary=DustSweepSummaryResponse.of(answered.summary),
        transactions=[TransactionResponse.of(transaction) for transaction in answered.transactions],
    )


@router.post(
    "/aggregates/bots",
    summary="Summarise a bot-run strategy's fill source as one aggregate",
    status_code=201,
    response_model=RegisteredResponse,
)
def record_bot(request: RecordBotRequest, admin: AdminDep, engine: EngineDep) -> RegisteredResponse:
    created = aggregates.record_bot(
        engine, label=request.label, source=request.source, symbol=request.symbol
    )
    if isinstance(created, str):
        raise HTTPException(status_code=422, detail=created)
    return RegisteredResponse(id=created)


@router.post(
    "/aggregates/dust-sweeps",
    summary="Record a dust sweep as one aggregate disposal over its constituent trades",
    status_code=201,
    response_model=RegisteredResponse,
)
def record_dust_sweep(
    request: RecordDustSweepRequest, admin: AdminDep, engine: EngineDep
) -> RegisteredResponse:
    created = aggregates.record_dust_sweep(
        engine, label=request.label, transaction_ids=request.transaction_ids
    )
    if isinstance(created, str):
        raise HTTPException(status_code=422, detail=created)
    return RegisteredResponse(id=created)


@router.delete(
    "/aggregates/{aggregate_id}",
    summary="Disband an aggregate — its constituents stay exactly as they are",
    status_code=204,
)
def disband_aggregate(aggregate_id: int, admin: AdminDep, engine: EngineDep) -> None:
    if not aggregates.disband(engine, aggregate_id):
        raise HTTPException(status_code=404, detail="No such aggregate.")

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime, BaseModel, PlainSerializer

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.repositories import stances
from open_leprechaun.repositories.stances import Refusal
from open_leprechaun.services.instruments import InstrumentOverview, overview
from open_leprechaun.services.stances import InboxItem, inbox, settled_inflow_type

router = APIRouter(tags=["instruments"])

# Fixed-point on the way out, as everywhere: a summed quantity is answered as
# a decimal string, never a float.
Quantity = Annotated[
    Decimal, PlainSerializer(lambda quantity: format(quantity, "f"), return_type=str)
]


class ListingResponse(BaseModel):
    id: int
    venue: str
    quote_currency: str
    # Whether this Listing's market prices the Instrument (ticket 45).
    price_source: bool


class AccountStanceResponse(BaseModel):
    account_id: int
    stance: Literal["kept", "ignored"]


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
    # A fund's classification with its source shown, and the review flag an
    # import-created security wears until the Admin settles it (ticket 44).
    fund_category: str | None
    fund_category_source: str | None
    distribution_policy: str | None
    needs_review: bool
    listings: list[ListingResponse]
    # An ignored or dangerous position stays visible with a clear warning
    # rather than being hidden — the stance ships with every overview row.
    dangerous: bool
    stances: list[AccountStanceResponse]

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
            fund_category=instrument.fund_category,
            fund_category_source=instrument.fund_category_source,
            distribution_policy=instrument.distribution_policy,
            needs_review=instrument.needs_review,
            listings=[
                ListingResponse(
                    id=listing.id,
                    venue=listing.venue,
                    quote_currency=listing.quote_currency,
                    price_source=listing.price_source,
                )
                for listing in instrument.listings
            ],
            dangerous=instrument.dangerous,
            stances=[
                AccountStanceResponse(account_id=stance.account_id, stance=stance.stance)
                for stance in instrument.stances
            ],
        )


class InboxItemResponse(BaseModel):
    instrument_id: int
    family: str
    type: str
    symbol: str
    name: str
    chain: str | None
    contract_address: str | None
    isin: str | None
    account_id: int
    account_name: str
    platform_name: str
    unclassified_inflow_count: int
    unclassified_quantity: Quantity
    last_inflow_at: AwareDatetime

    @classmethod
    def of(cls, item: InboxItem) -> InboxItemResponse:
        return cls(
            instrument_id=item.instrument_id,
            family=item.family,
            type=item.type,
            symbol=item.symbol,
            name=item.name,
            chain=item.chain,
            contract_address=item.contract_address,
            isin=item.isin,
            account_id=item.account_id,
            account_name=item.account_name,
            platform_name=item.platform_name,
            unclassified_inflow_count=item.unclassified_inflow_count,
            unclassified_quantity=item.unclassified_quantity,
            last_inflow_at=item.last_inflow_at,
        )


class ClassifyRequest(BaseModel):
    stance: Literal["kept", "ignored", "dangerous"]
    # Kept and ignored are decisions about one Account; dangerous is global.
    account_id: int | None = None
    # The question acknowledging an unsolicited inflow asks, defaulting to
    # no. Only keeping settles the inflow, so only keeping may answer it.
    received_for_counter_performance: bool = False


class ClassifiedResponse(BaseModel):
    settled_transaction_ids: list[int]


@router.get(
    "/instruments",
    summary="Every Instrument with its identity attributes, Listings and Stances",
    response_model=list[InstrumentResponse],
)
def list_instruments(admin: AdminDep, engine: EngineDep) -> list[InstrumentResponse]:
    return [InstrumentResponse.of(instrument) for instrument in overview(engine)]


@router.get(
    "/inbox",
    summary="Unacknowledged arrivals awaiting a Stance, newest first",
    response_model=list[InboxItemResponse],
)
def list_inbox(admin: AdminDep, engine: EngineDep) -> list[InboxItemResponse]:
    return [InboxItemResponse.of(item) for item in inbox(engine)]


@router.put(
    "/instruments/{instrument_id}/stance",
    summary="Classify an Instrument: kept or ignored at an Account, or dangerous everywhere",
    response_model=ClassifiedResponse,
)
def classify_instrument(
    instrument_id: int, request: ClassifyRequest, admin: AdminDep, engine: EngineDep
) -> ClassifiedResponse:
    _refuse_ill_scoped(request)
    settled = stances.classify(
        engine,
        instrument_id,
        stance=request.stance,
        account_id=request.account_id,
        settle_inflows_as=settled_inflow_type(
            received_for_counter_performance=request.received_for_counter_performance
        )
        if request.stance == "kept"
        else None,
    )
    if settled is Refusal.marked_dangerous:
        raise HTTPException(
            status_code=409,
            detail="Marked dangerous everywhere — that verdict outranks a per-Account"
            " decision. Return the Instrument to unacknowledged first.",
        )
    if isinstance(settled, Refusal):
        raise HTTPException(status_code=404, detail=_MISSING[settled])
    return ClassifiedResponse(settled_transaction_ids=settled)


@router.delete(
    "/instruments/{instrument_id}/stance",
    summary="Remove a Stance decision, returning its scope to unacknowledged",
    status_code=204,
)
def unclassify_instrument(
    instrument_id: int, admin: AdminDep, engine: EngineDep, account_id: int | None = None
) -> None:
    if not stances.clear(engine, instrument_id, account_id=account_id):
        raise HTTPException(status_code=404, detail="No such Stance decision.")


_MISSING = {
    Refusal.no_such_instrument: "No such Instrument.",
    Refusal.no_such_account: "No such Account.",
}


def _refuse_ill_scoped(request: ClassifyRequest) -> None:
    """The scope is the stance (ADR-0012): kept and ignored name an Account,
    dangerous names none — and only keeping answers the question."""
    if request.stance == "dangerous":
        if request.account_id is not None:
            raise HTTPException(
                status_code=422,
                detail="Dangerous applies to the Instrument globally, not to an Account.",
            )
    elif request.account_id is None:
        raise HTTPException(
            status_code=422,
            detail=f"A {request.stance} stance is a decision about one Account.",
        )
    if request.received_for_counter_performance and request.stance != "kept":
        raise HTTPException(
            status_code=422,
            detail="Only keeping settles an inflow, so only keeping answers the"
            " counter-performance question.",
        )

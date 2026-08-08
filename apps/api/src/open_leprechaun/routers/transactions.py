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
from open_leprechaun.repositories import transactions
from open_leprechaun.repositories.transactions import Leg, Refusal
from open_leprechaun.services.transactions import (
    TransactionOverview,
    overview,
    structural_defect,
)

router = APIRouter(tags=["transactions"])

# The vocabulary of what happened, for crypto and securities both. The service
# holds which legs each type must carry; a test holds the two lists to each
# other.
TransactionType = Literal[
    "trade",
    "transfer_in",
    "transfer_out",
    "spend",
    "staking_reward",
    "lending_interest",
    "mining_reward",
    "airdrop",
    "windfall",
    "dividend",
    "distribution",
    "interest",
    "fee",
]

LegRole = Literal["in", "out", "fee"]


def _decimal_text_only(value: object) -> object:
    """Refuse a JSON number where a quantity belongs: it has been through —
    or is one parse away from — a binary float, so only a string states the
    digits exactly. Decimals pass untouched; responses are built from them."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        raise ValueError("a quantity crosses JSON as a fixed-point decimal string, not a number")
    return value


# Fixed-point end to end, including in JSON: a quantity is parsed exactly from
# a decimal string and answered as one, never a float in either direction.
Quantity = Annotated[
    Decimal,
    BeforeValidator(_decimal_text_only),
    Field(gt=0, allow_inf_nan=False),
    PlainSerializer(lambda quantity: format(quantity, "f"), return_type=str),
]

# A note is prose for the Admin; trimmed so blank cannot pose as one.
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None


class LegPayload(BaseModel):
    account_id: int
    instrument_id: int
    role: LegRole
    quantity: Quantity
    # A fee names the sibling leg it was charged against by its position in
    # this list; the response answers with the stored leg's id.
    charged_against: int | None = None


class RecordTransactionRequest(BaseModel):
    type: TransactionType
    occurred_at: AwareDatetime
    note: Note = None
    legs: list[LegPayload]


class RegisteredResponse(BaseModel):
    id: int


class LegResponse(BaseModel):
    id: int
    account_id: int
    instrument_id: int
    role: LegRole
    quantity: Quantity
    charged_against_leg_id: int | None


class TransactionResponse(BaseModel):
    id: int
    type: TransactionType
    occurred_at: AwareDatetime
    note: str | None
    legs: list[LegResponse]

    @classmethod
    def of(cls, transaction: TransactionOverview) -> TransactionResponse:
        return cls(
            id=transaction.id,
            type=transaction.type,
            occurred_at=transaction.occurred_at,
            note=transaction.note,
            legs=[
                LegResponse(
                    id=leg.id,
                    account_id=leg.account_id,
                    instrument_id=leg.instrument_id,
                    role=leg.role,
                    quantity=leg.quantity,
                    charged_against_leg_id=leg.charged_against_leg_id,
                )
                for leg in transaction.legs
            ],
        )


@router.get(
    "/transactions",
    summary="The ledger, newest first, each Transaction with its legs",
    response_model=list[TransactionResponse],
)
def list_transactions(admin: AdminDep, engine: EngineDep) -> list[TransactionResponse]:
    return [TransactionResponse.of(transaction) for transaction in overview(engine)]


@router.post(
    "/transactions",
    summary="Record an economic event as a set of balanced legs",
    status_code=201,
    response_model=RegisteredResponse,
)
def record_transaction(
    request: RecordTransactionRequest, admin: AdminDep, engine: EngineDep
) -> RegisteredResponse:
    legs = _balanced(request)
    created = transactions.create_transaction(
        engine, type=request.type, occurred_at=request.occurred_at, note=request.note, legs=legs
    )
    if isinstance(created, Refusal):
        raise HTTPException(status_code=404, detail=_MISSING[created])
    return RegisteredResponse(id=created)


@router.put(
    "/transactions/{transaction_id}",
    summary="Revise an event wholesale: header and legs together",
    status_code=204,
)
def revise_transaction(
    transaction_id: int, request: RecordTransactionRequest, admin: AdminDep, engine: EngineDep
) -> None:
    legs = _balanced(request)
    refused = transactions.replace_transaction(
        engine,
        transaction_id,
        type=request.type,
        occurred_at=request.occurred_at,
        note=request.note,
        legs=legs,
    )
    if refused is not None:
        raise HTTPException(status_code=404, detail=_MISSING[refused])


@router.delete(
    "/transactions/{transaction_id}",
    summary="Remove an event and its legs",
    status_code=204,
)
def remove_transaction(transaction_id: int, admin: AdminDep, engine: EngineDep) -> None:
    if not transactions.delete_transaction(engine, transaction_id):
        raise HTTPException(status_code=404, detail="No such Transaction.")


_MISSING = {
    Refusal.no_such_transaction: "No such Transaction.",
    Refusal.no_such_account: "No such Account.",
    Refusal.no_such_instrument: "No such Instrument.",
}


def _balanced(request: RecordTransactionRequest) -> list[Leg]:
    """The request's legs, refused with the service's own sentence when they
    do not balance for the type — so no route can write an unbalanced event."""
    legs = [
        Leg(
            account_id=leg.account_id,
            instrument_id=leg.instrument_id,
            role=leg.role,
            quantity=leg.quantity,
            charged_against=leg.charged_against,
        )
        for leg in request.legs
    ]
    defect = structural_defect(request.type, legs)
    if defect is not None:
        raise HTTPException(status_code=422, detail=defect)
    return legs

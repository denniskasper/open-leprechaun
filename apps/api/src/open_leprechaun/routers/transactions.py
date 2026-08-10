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
    declaration_defect,
    overview,
    retype_all,
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
    "opening_balance",
    "dividend",
    "distribution",
    "interest",
    "fee",
]

LegRole = Literal["in", "out", "fee"]

# What an Opening Balance declares as reconstructed; the service holds the
# same vocabulary and a test holds the two to each other.
Reconstructed = Literal["basis", "basis_and_date"]


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

# An estimated basis is a quantity that may honestly be zero — the most
# conservative estimate there is — but never negative.
EstimatedBasis = Annotated[
    Decimal,
    BeforeValidator(_decimal_text_only),
    Field(ge=0, allow_inf_nan=False),
    PlainSerializer(lambda basis: format(basis, "f"), return_type=str),
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
    # An Opening Balance's declarations (ticket 15): what is reconstructed,
    # and the declared estimate of the position's cost basis in EUR. Required
    # for an opening balance, refused on every other type — the service's
    # declaration_defect judges the pairing.
    reconstructed: Reconstructed | None = None
    estimated_basis_eur: EstimatedBasis | None = None
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
    reconstructed: Reconstructed | None
    estimated_basis_eur: EstimatedBasis | None
    # The dust-sweep aggregate this event belongs to (ticket 30) — the
    # marker the summary presentation collapses on.
    aggregate_id: int | None
    # Import provenance (ticket 31): the batch and source that created this
    # row, null on a hand-recorded event; manually_overridden marks an
    # imported row the Admin has edited, which a re-import never reverts.
    import_batch_id: int | None
    import_source: str | None
    manually_overridden: bool
    legs: list[LegResponse]

    @classmethod
    def of(cls, transaction: TransactionOverview) -> TransactionResponse:
        return cls(
            id=transaction.id,
            type=transaction.type,
            occurred_at=transaction.occurred_at,
            note=transaction.note,
            reconstructed=transaction.reconstructed,
            estimated_basis_eur=transaction.estimated_basis_eur,
            aggregate_id=transaction.aggregate_id,
            import_batch_id=transaction.import_batch_id,
            import_source=transaction.import_source,
            manually_overridden=transaction.manually_overridden,
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
        engine,
        type=request.type,
        occurred_at=request.occurred_at,
        note=request.note,
        legs=legs,
        reconstructed=request.reconstructed,
        estimated_basis_eur=request.estimated_basis_eur,
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
        reconstructed=request.reconstructed,
        estimated_basis_eur=request.estimated_basis_eur,
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


class BulkReassignmentRequest(BaseModel):
    transaction_ids: list[int] = Field(min_length=1)
    account_id: int


class BulkRetypingRequest(BaseModel):
    transaction_ids: list[int] = Field(min_length=1)
    type: TransactionType


@router.post(
    "/transactions/bulk-reassignment",
    summary="Move the chosen events' legs into another Account, in one act",
    status_code=204,
)
def bulk_reassignment(request: BulkReassignmentRequest, admin: AdminDep, engine: EngineDep) -> None:
    """The repair for a file imported against the wrong holding — a
    systematic error is one act, not a hundred edits. Imported rows among the
    chosen are marked manually overridden."""
    refused = transactions.reassign_account(
        engine, request.transaction_ids, account_id=request.account_id
    )
    if refused is not None:
        raise HTTPException(status_code=404, detail=_MISSING[refused])


@router.post(
    "/transactions/bulk-retyping",
    summary="Re-type the chosen events, in one act",
    status_code=204,
)
def bulk_retyping(request: BulkRetypingRequest, admin: AdminDep, engine: EngineDep) -> None:
    """Each event must balance for the new type by the same judgement as at
    recording; one that would not refuses the whole act, so a bulk repair
    never half-lands."""
    refused = retype_all(engine, request.transaction_ids, type=request.type)
    if isinstance(refused, str):
        raise HTTPException(status_code=422, detail=refused)
    if refused is not None:
        raise HTTPException(status_code=404, detail=_MISSING[refused])


_MISSING = {
    Refusal.no_such_transaction: "No such Transaction.",
    Refusal.no_such_account: "No such Account.",
    Refusal.no_such_instrument: "No such Instrument.",
}


def _balanced(request: RecordTransactionRequest) -> list[Leg]:
    """The request's legs, refused with the service's own sentence when they
    do not balance for the type or the declarations do not fit it — so no
    route can write an unbalanced or dishonestly-declared event."""
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
    defect = structural_defect(request.type, legs) or declaration_defect(
        request.type,
        reconstructed=request.reconstructed,
        estimated_basis_eur=request.estimated_basis_eur,
    )
    if defect is not None:
        raise HTTPException(status_code=422, detail=defect)
    return legs

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime, BaseModel

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.repositories import transfer_matches
from open_leprechaun.repositories.transfer_matches import Refusal

# Fixed-point end to end: a quantity is answered as a decimal string, the
# one convention the whole API speaks.
from open_leprechaun.routers.transactions import Quantity
from open_leprechaun.services.transfer_matches import (
    Candidate,
    Decision,
    TransferLeg,
    link_defect,
    matching_overview,
)

router = APIRouter(tags=["transfer-matches"])

Verdict = Literal["confirmed", "rejected"]


class TransferLegResponse(BaseModel):
    leg_id: int
    transaction_id: int
    occurred_at: AwareDatetime
    note: str | None
    quantity: Quantity
    account_id: int
    account_name: str
    platform_name: str
    instrument_id: int
    instrument_symbol: str
    instrument_name: str

    @classmethod
    def of(cls, leg: TransferLeg) -> TransferLegResponse:
        return cls(
            leg_id=leg.leg_id,
            transaction_id=leg.transaction_id,
            occurred_at=leg.occurred_at,
            note=leg.note,
            quantity=leg.quantity,
            account_id=leg.account_id,
            account_name=leg.account_name,
            platform_name=leg.platform_name,
            instrument_id=leg.instrument_id,
            instrument_symbol=leg.instrument_symbol,
            instrument_name=leg.instrument_name,
        )


class CandidateResponse(BaseModel):
    outgoing: TransferLegResponse
    incoming: TransferLegResponse

    @classmethod
    def of(cls, candidate: Candidate) -> CandidateResponse:
        return cls(
            outgoing=TransferLegResponse.of(candidate.outgoing),
            incoming=TransferLegResponse.of(candidate.incoming),
        )


class DecisionResponse(BaseModel):
    id: int
    verdict: Verdict
    decided_at: AwareDatetime
    outgoing: TransferLegResponse
    incoming: TransferLegResponse

    @classmethod
    def of(cls, decision: Decision) -> DecisionResponse:
        return cls(
            id=decision.id,
            verdict=decision.verdict,
            decided_at=decision.decided_at,
            outgoing=TransferLegResponse.of(decision.outgoing),
            incoming=TransferLegResponse.of(decision.incoming),
        )


class MatchingOverviewResponse(BaseModel):
    unmatched_outgoing: list[TransferLegResponse]
    unmatched_incoming: list[TransferLegResponse]
    candidates: list[CandidateResponse]
    decisions: list[DecisionResponse]


class DecideRequest(BaseModel):
    out_leg_id: int
    in_leg_id: int
    verdict: Verdict


class DecidedResponse(BaseModel):
    id: int


@router.get(
    "/transfer-matches",
    summary="The matching state: unmatched transfers, proposals, decisions",
    response_model=MatchingOverviewResponse,
)
def list_matching(admin: AdminDep, engine: EngineDep) -> MatchingOverviewResponse:
    overview = matching_overview(engine)
    return MatchingOverviewResponse(
        unmatched_outgoing=[TransferLegResponse.of(leg) for leg in overview.unmatched_outgoing],
        unmatched_incoming=[TransferLegResponse.of(leg) for leg in overview.unmatched_incoming],
        candidates=[CandidateResponse.of(candidate) for candidate in overview.candidates],
        decisions=[DecisionResponse.of(decision) for decision in overview.decisions],
    )


@router.post(
    "/transfer-matches",
    summary="Confirm or reject one proposed pair — the deliberate act",
    status_code=201,
    response_model=DecidedResponse,
)
def decide_match(request: DecideRequest, admin: AdminDep, engine: EngineDep) -> DecidedResponse:
    details = transfer_matches.leg_details(engine, [request.out_leg_id, request.in_leg_id])
    for leg_id in (request.out_leg_id, request.in_leg_id):
        if leg_id not in details:
            raise HTTPException(status_code=404, detail="No such leg.")
    defect = link_defect(details[request.out_leg_id], details[request.in_leg_id])
    if defect is not None:
        raise HTTPException(status_code=422, detail=defect)
    decided = transfer_matches.decide(
        engine,
        out_leg_id=request.out_leg_id,
        in_leg_id=request.in_leg_id,
        verdict=request.verdict,
    )
    if isinstance(decided, Refusal):
        raise HTTPException(status_code=_REFUSED_STATUS[decided], detail=_REFUSED[decided])
    return DecidedResponse(id=decided)


@router.delete(
    "/transfer-matches/{match_id}",
    summary="Undo a decision: unlink a match or make a rejected pair proposable",
    status_code=204,
)
def undo_decision(match_id: int, admin: AdminDep, engine: EngineDep) -> None:
    if not transfer_matches.undo(engine, match_id):
        raise HTTPException(status_code=404, detail="No such decision.")


_REFUSED = {
    Refusal.no_such_leg: "No such leg.",
    Refusal.already_matched: "A leg of this pair already belongs to a confirmed match —"
    " undo that link first.",
    Refusal.already_decided: "This pair is already decided — undo that decision first.",
}

_REFUSED_STATUS = {
    Refusal.no_such_leg: 404,
    Refusal.already_matched: 409,
    Refusal.already_decided: 409,
}

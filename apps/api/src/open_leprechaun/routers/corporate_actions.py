"""Corporate Actions (ticket 52): preview an issuer event against the lots
it would touch, apply it, read what each applied event did, mark a
fact-specific one reviewed, and reverse one by removing it."""

from decimal import Decimal
from typing import Annotated, Literal, Self

from fastapi import APIRouter, HTTPException
from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    Field,
    PlainSerializer,
    StringConstraints,
    model_validator,
)

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.routers.fixed_point import decimal_text_only
from open_leprechaun.services import corporate_actions
from open_leprechaun.services.corporate_actions import CorporateAction, Recorded, RefusedError
from open_leprechaun.services.lots import LotEffect, LotState

router = APIRouter(tags=["corporate actions"])

Kind = Literal["split", "spin_off", "merger", "capital_return"]

# Fixed-point end to end, including in JSON (routers/fixed_point): a ratio
# side, a share or an amount crosses as a decimal string, strictly positive.
Positive = Annotated[
    Decimal,
    BeforeValidator(decimal_text_only),
    Field(gt=0, allow_inf_nan=False),
    PlainSerializer(lambda value: format(value, "f"), return_type=str),
]
Fixed = Annotated[Decimal, PlainSerializer(lambda value: format(value, "f"), return_type=str)]

Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ActionRequest(BaseModel):
    """One event as the Admin states it. Each kind carries exactly its own
    fields — the same shape the schema holds — so a request cannot state a
    ratio the event has no use for."""

    kind: Kind
    instrument_id: int
    effective_at: AwareDatetime
    # `units_new` for every `units_old` held — of the target Instrument for
    # a spin-off or merger.
    units_new: Positive | None = None
    units_old: Positive | None = None
    target_instrument_id: int | None = None
    # The share of each lot's basis a spin-off moves to the target.
    basis_share: Positive | None = None
    amount_per_unit_eur: Positive | None = None
    note: Note | None = None

    @model_validator(mode="after")
    def carries_its_kinds_fields(self) -> Self:
        changes_units = self.kind != "capital_return"
        if changes_units != (self.units_new is not None and self.units_old is not None) or (
            not changes_units and (self.units_new is not None or self.units_old is not None)
        ):
            raise ValueError(
                "A split, spin-off or merger states its ratio — units_new for every"
                " units_old — and a capital return states none."
            )
        if (self.kind in ("spin_off", "merger")) != (self.target_instrument_id is not None):
            raise ValueError("A spin-off or merger — and only one — names its target Instrument.")
        if (self.kind == "spin_off") != (self.basis_share is not None):
            raise ValueError("A spin-off — and only one — states the share of basis it moves.")
        if self.basis_share is not None and self.basis_share >= 1:
            raise ValueError("The share of basis a spin-off moves lies strictly below one.")
        if (self.kind == "capital_return") != (self.amount_per_unit_eur is not None):
            raise ValueError("A capital return — and only one — states its amount per unit.")
        return self

    def stated(self) -> CorporateAction:
        # Field by field rather than through model_dump, which would hand the
        # decimals over already serialised to text.
        return CorporateAction(**{name: getattr(self, name) for name in type(self).model_fields})


class LotStateResponse(BaseModel):
    instrument_id: int
    quantity: Fixed
    # None while the basis awaits a valuation the lot engine cannot state.
    basis_eur: Fixed | None

    @classmethod
    def of(cls, state: LotState) -> Self:
        return cls(**vars(state))


class LotEffectResponse(BaseModel):
    """One open lot before the event and everything it became."""

    account_id: int
    acquired_at: AwareDatetime
    basis_source: str
    before: LotStateResponse
    after: list[LotStateResponse]
    # What a capital return exceeded the lot's basis by.
    excess_eur: Fixed

    @classmethod
    def of(cls, effect: LotEffect) -> Self:
        return cls(
            account_id=effect.account_id,
            acquired_at=effect.acquired_at,
            basis_source=effect.basis_source,
            before=LotStateResponse.of(effect.before),
            after=[LotStateResponse.of(state) for state in effect.after],
            excess_eur=effect.excess_eur,
        )


class ActionResponse(BaseModel):
    # None on a preview: nothing was recorded.
    id: int | None
    kind: Kind
    instrument_id: int
    effective_at: AwareDatetime
    units_new: Fixed | None
    units_old: Fixed | None
    target_instrument_id: int | None
    basis_share: Fixed | None
    amount_per_unit_eur: Fixed | None
    note: str | None
    reviewed_at: AwareDatetime | None
    # The treatment is fact-specific and the Admin has not yet stood by it.
    needs_review: bool
    lots: list[LotEffectResponse]

    @classmethod
    def of(cls, action: Recorded) -> Self:
        stated = {name: value for name, value in vars(action).items() if name != "effects"}
        return cls(**stated, lots=[LotEffectResponse.of(effect) for effect in action.effects])


class CreatedResponse(BaseModel):
    id: int


@router.get(
    "/corporate-actions",
    summary="Every recorded Corporate Action with what it did to the lots open at its instant",
    response_model=list[ActionResponse],
)
def list_corporate_actions(admin: AdminDep, engine: EngineDep) -> list[ActionResponse]:
    return [ActionResponse.of(action) for action in corporate_actions.recorded(engine)]


@router.post(
    "/corporate-actions/preview",
    summary="The before and after of every lot the event would touch — nothing is written",
    response_model=ActionResponse,
)
def preview_corporate_action(
    request: ActionRequest, admin: AdminDep, engine: EngineDep
) -> ActionResponse:
    try:
        return ActionResponse.of(corporate_actions.preview(engine, request.stated()))
    except RefusedError as refused:
        raise HTTPException(status_code=422, detail=str(refused)) from refused


@router.post(
    "/corporate-actions",
    status_code=201,
    summary="Apply a Corporate Action by recording the event",
    response_model=CreatedResponse,
)
def apply_corporate_action(
    request: ActionRequest, admin: AdminDep, engine: EngineDep
) -> CreatedResponse:
    try:
        return CreatedResponse(id=corporate_actions.record(engine, request.stated()))
    except RefusedError as refused:
        raise HTTPException(status_code=422, detail=str(refused)) from refused


@router.put(
    "/corporate-actions/{action_id}/review",
    status_code=204,
    summary="Mark a flagged Corporate Action as reviewed by the Admin",
)
def review_corporate_action(action_id: int, admin: AdminDep, engine: EngineDep) -> None:
    if not corporate_actions.mark_reviewed(engine, action_id):
        raise HTTPException(status_code=404, detail="No such Corporate Action.")


@router.delete(
    "/corporate-actions/{action_id}",
    status_code=204,
    summary="Reverse a Corporate Action: remove the event, and the lots rebuild without it",
)
def remove_corporate_action(action_id: int, admin: AdminDep, engine: EngineDep) -> None:
    if not corporate_actions.remove(engine, action_id):
        raise HTTPException(status_code=404, detail="No such Corporate Action.")

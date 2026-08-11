from decimal import Decimal
from typing import Annotated, Literal, Self

from fastapi import APIRouter, HTTPException
from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    PlainSerializer,
    StringConstraints,
    model_validator,
)

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.repositories import platforms
from open_leprechaun.repositories.platforms import Refusal
from open_leprechaun.routers.fixed_point import decimal_text_only
from open_leprechaun.services.platforms import PlatformOverview, overview

router = APIRouter(tags=["platforms"])

# The five kinds of place that hold value. "Exchange" appears here and nowhere
# more general — any other place is one of the other four.
PlatformKind = Literal["exchange", "cold_storage", "software_wallet", "broker", "bank"]

# Names are what the Admin reads a place and a holding by, so whitespace is
# trimmed before it can become an identity nobody can tell from another.
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# How a broker treats income at source (ticket 43): withheld already, or
# arriving gross with everything still to declare.
Withholding = Literal["at_source", "none"]

# The base currency a Depot keeps its cash reporting in — a code, not prose.
BaseCurrency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


# Fixed-point end to end, including in JSON — like every monetary value in
# this API. An exemption order of zero is expressible but means the same as
# none; negative is refused.
Money = Annotated[
    Decimal,
    BeforeValidator(decimal_text_only),
    Field(ge=0, allow_inf_nan=False),
    PlainSerializer(lambda value: format(value, "f"), return_type=str),
]


class AccountResponse(BaseModel):
    id: int
    name: str
    chain: str | None
    external_reference: str | None
    access_software: str | None
    # The one ingestion source that may write here (ticket 31); null until an
    # import declares itself or the Admin declares one.
    authoritative_source: str | None
    # This Account's exception to its Platform's withholding behaviour
    # (ticket 43); null means the Platform's word stands.
    withholding_override: Withholding | None
    base_currency: str | None


class PlatformResponse(BaseModel):
    id: int
    name: str
    kind: PlatformKind
    # Only ever set on a broker; the exemption order only where income is
    # withheld at source, and absent means none (ticket 43).
    withholding: Withholding | None
    exemption_order_eur: Money | None
    accounts: list[AccountResponse]

    @classmethod
    def of(cls, platform: PlatformOverview) -> PlatformResponse:
        return cls(
            id=platform.id,
            name=platform.name,
            kind=platform.kind,
            withholding=platform.withholding,
            exemption_order_eur=platform.exemption_order_eur,
            accounts=[
                AccountResponse(
                    id=account.id,
                    name=account.name,
                    chain=account.chain,
                    external_reference=account.external_reference,
                    access_software=account.access_software,
                    authoritative_source=account.authoritative_source,
                    withholding_override=account.withholding_override,
                    base_currency=account.base_currency,
                )
                for account in platform.accounts
            ],
        )


class RegisterPlatformRequest(BaseModel):
    name: Name
    kind: PlatformKind


class RegisteredResponse(BaseModel):
    id: int


class AddAccountRequest(BaseModel):
    name: Name
    chain: str | None = None
    # Address, IBAN or reference — metadata identifying the holding to a
    # human, never a data source.
    external_reference: str | None = None
    access_software: str | None = None
    base_currency: BaseCurrency | None = None


@router.get(
    "/platforms",
    summary="Every Platform with its Accounts nested under it",
    response_model=list[PlatformResponse],
)
def list_platforms(admin: AdminDep, engine: EngineDep) -> list[PlatformResponse]:
    return [PlatformResponse.of(platform) for platform in overview(engine)]


@router.post(
    "/platforms",
    summary="Register a place that holds value",
    status_code=201,
    response_model=RegisteredResponse,
)
def register_platform(
    request: RegisterPlatformRequest, admin: AdminDep, engine: EngineDep
) -> RegisteredResponse:
    platform_id = platforms.create_platform(engine, name=request.name, kind=request.kind)
    if platform_id is None:
        raise HTTPException(
            status_code=409, detail=f"{request.name!r} is already registered as this kind."
        )
    return RegisteredResponse(id=platform_id)


@router.post(
    "/platforms/{platform_id}/accounts",
    summary="Add a holding under a Platform",
    status_code=201,
    response_model=RegisteredResponse,
)
def add_account(
    platform_id: int, request: AddAccountRequest, admin: AdminDep, engine: EngineDep
) -> RegisteredResponse:
    created = platforms.create_account(
        engine,
        platform_id,
        name=request.name,
        chain=request.chain,
        external_reference=request.external_reference,
        access_software=request.access_software,
        base_currency=request.base_currency,
    )
    if created is Refusal.no_such_platform:
        raise HTTPException(status_code=404, detail="No such Platform.")
    if created is Refusal.name_taken:
        raise HTTPException(
            status_code=409,
            detail=f"{request.name!r} already exists under this Platform.",
        )
    return RegisteredResponse(id=created)


class WithholdingRequest(BaseModel):
    behaviour: Withholding
    exemption_order_eur: Money | None = None

    @model_validator(mode="after")
    def _order_only_where_withheld(self) -> Self:
        # A Freistellungsauftrag is lodged with a broker that withholds — on
        # a Platform that keeps nothing the amount would answer no question.
        if self.exemption_order_eur is not None and self.behaviour != "at_source":
            raise ValueError("an exemption order may only stand where income is withheld at source")
        return self


@router.put(
    "/platforms/{platform_id}/withholding",
    summary="Record how this broker treats income at source",
    status_code=204,
)
def record_withholding(
    platform_id: int, request: WithholdingRequest, admin: AdminDep, engine: EngineDep
) -> None:
    """Withholding behaviour and the exemption order lodged there are one act
    (ticket 43): the amount may only stand with the behaviour that gives it
    meaning, and a Depot may hold no position until the behaviour is set."""
    refused = platforms.set_withholding(
        engine,
        platform_id,
        behaviour=request.behaviour,
        exemption_order_eur=request.exemption_order_eur,
    )
    if refused is Refusal.no_such_platform:
        raise HTTPException(status_code=404, detail="No such Platform.")
    if refused is Refusal.not_a_broker:
        raise HTTPException(
            status_code=409, detail="Only a broker Platform carries withholding behaviour."
        )


class WithholdingOverrideRequest(BaseModel):
    # None clears the exception; the Platform's word stands again.
    behaviour: Withholding | None


@router.put(
    "/accounts/{account_id}/withholding-override",
    summary="State this one Depot's exception to its broker's withholding",
    status_code=204,
)
def record_withholding_override(
    account_id: int, request: WithholdingOverrideRequest, admin: AdminDep, engine: EngineDep
) -> None:
    """For a brand operating through several entities with different tax
    status (ticket 43): the Platform states the common case, the Account the
    exception."""
    refused = platforms.set_withholding_override(engine, account_id, behaviour=request.behaviour)
    if refused is Refusal.no_such_account:
        raise HTTPException(status_code=404, detail="No such Account.")
    if refused is Refusal.not_under_a_broker:
        raise HTTPException(
            status_code=409, detail="Only an Account under a broker carries an override."
        )
    if refused is Refusal.would_unset_a_held_depot:
        raise HTTPException(
            status_code=409,
            detail=(
                "This Depot holds positions on the strength of its override alone —"
                " set the broker Platform's withholding before clearing it."
            ),
        )


class AuthoritativeSourceRequest(BaseModel):
    # None clears the declaration; the next committed import declares itself.
    source: Name | None


@router.put(
    "/accounts/{account_id}/authoritative-source",
    summary="Declare which ingestion source may write into this Account",
    status_code=204,
)
def declare_authoritative_source(
    account_id: int, request: AuthoritativeSourceRequest, admin: AdminDep, engine: EngineDep
) -> None:
    """Exactly one ingestion mode is authoritative per Account (ticket 31);
    any other source may reconcile against it but may not write."""
    if not platforms.set_authoritative_source(engine, account_id, request.source):
        raise HTTPException(status_code=404, detail="No such Account.")

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StringConstraints

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.repositories import platforms
from open_leprechaun.repositories.platforms import Refusal
from open_leprechaun.services.platforms import PlatformOverview, overview

router = APIRouter(tags=["platforms"])

# The five kinds of place that hold value. "Exchange" appears here and nowhere
# more general — any other place is one of the other four.
PlatformKind = Literal["exchange", "cold_storage", "software_wallet", "broker", "bank"]

# Names are what the Admin reads a place and a holding by, so whitespace is
# trimmed before it can become an identity nobody can tell from another.
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class AccountResponse(BaseModel):
    id: int
    name: str
    chain: str | None
    external_reference: str | None
    access_software: str | None


class PlatformResponse(BaseModel):
    id: int
    name: str
    kind: PlatformKind
    accounts: list[AccountResponse]

    @classmethod
    def of(cls, platform: PlatformOverview) -> PlatformResponse:
        return cls(
            id=platform.id,
            name=platform.name,
            kind=platform.kind,
            accounts=[
                AccountResponse(
                    id=account.id,
                    name=account.name,
                    chain=account.chain,
                    external_reference=account.external_reference,
                    access_software=account.access_software,
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
    )
    if created is Refusal.no_such_platform:
        raise HTTPException(status_code=404, detail="No such Platform.")
    if created is Refusal.name_taken:
        raise HTTPException(
            status_code=409,
            detail=f"{request.name!r} already exists under this Platform.",
        )
    return RegisteredResponse(id=created)
